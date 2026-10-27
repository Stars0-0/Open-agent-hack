"""Meterless World Model engine, Python port of the core of the open spec.

Source: github.com/Meterless/Meterless/engines/world-model (AGENTS.md + reference/). This is a SUBSET:
content-addressed stable IDs, an append-only event log folded into entities/relationships/facts,
superseding relationships, provenance-derived timestamps (so re-ingest is idempotent), an audit log,
and JSON persistence (save()). NOT ported: fuzzy entity resolution/merge queue, contexts, stories, scoring,
control plane. It does not run the TypeScript conformance suite; tests/test_world_model.py checks the
ported rulings directly.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import unicodedata


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def normalize_name(name: str) -> str:
    """NFKD, strip combining marks and zero-width chars, lowercase, collapse whitespace."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub("[​-‍﻿]", "", s)
    return re.sub(r"\s+", " ", s.lower()).strip()


def entity_id(type_: str, name: str) -> str:
    return f"ent_{_h(f'{type_}:{normalize_name(name)}')}"


def relationship_id(frm, type_, to, context=None, valid_from=None) -> str:
    return "rel_" + _h("|".join([str(frm), str(type_), str(to), context or "", valid_from or ""]))


def fact_id(about, predicate, value, at, source_kind, source_ref=None) -> str:
    return "fact_" + _h("|".join([str(about), str(predicate), canonical_json(value), str(at), str(source_kind), source_ref or ""]))


class WorldModel:
    """Shared state for all agents. Writes append events; reads are folds over the log."""

    def __init__(self, namespace: str, directory: str | None = None):
        self.events, self.audit = [], []
        self.entities, self.relationships, self.facts = {}, {}, {}
        self._file = None
        if directory:
            os.makedirs(directory, exist_ok=True)
            self._file = os.path.join(directory, f"{namespace}.json")
            if os.path.exists(self._file):
                for e in json.load(open(self._file)).get("events", []):
                    self._apply(e)

    # ---- writes (every write needs provenance: source = {"kind", "at", "ref"?}) ----
    def upsert_entity(self, type_: str, name: str, source: dict, attrs: dict | None = None) -> str:
        eid = entity_id(type_, name)
        self._append("upsertEntity", {"id": eid, "type": type_, "name": name, "attrs": attrs or {},
                                      "updatedAt": source["at"], "source": source}, f"upsert {type_} {name}")
        return eid

    def relate(self, frm: str, type_: str, to: str, source: dict, context: str | None = None) -> str:
        rid = relationship_id(frm, type_, to, context, source["at"])
        self._append("relate", {"id": rid, "from": frm, "type": type_, "to": to, "context": context,
                                "validFrom": source["at"], "source": source}, f"relate {frm} {type_} {to}")
        return rid

    def assert_fact(self, about: str, predicate: str, value, source: dict, confidence: float | None = None) -> str:
        fid = fact_id(about, predicate, value, source["at"], source["kind"], source.get("ref"))
        self._append("assertFact", {"id": fid, "about": about, "predicate": predicate, "value": value,
                                    "confidence": confidence, "assertedAt": source["at"], "source": source},
                     f"fact {predicate} about {about}")
        return fid

    # ---- reads ----
    def entities_of(self, type_: str) -> list[dict]:
        return [e for e in self.entities.values() if e["type"] == type_]

    def facts_about(self, about: str, predicate: str | None = None) -> list[dict]:
        return [f for f in self.facts.values() if f["about"] == about and (predicate is None or f["predicate"] == predicate)]

    def latest_fact(self, about: str, predicate: str) -> dict | None:
        found = self.facts_about(about, predicate)
        return max(found, key=lambda f: f["assertedAt"]) if found else None  # max keeps the later insert on ties

    def open_relationships(self, frm: str | None = None, type_: str | None = None) -> list[dict]:
        return [r for r in self.relationships.values() if not r.get("validTo")
                and (frm is None or r["from"] == frm) and (type_ is None or r["type"] == type_)]

    def snapshot(self) -> str:
        """Canonical dump of folded state; two equal snapshots mean identical world state."""
        return canonical_json({"entities": self.entities, "relationships": self.relationships, "facts": self.facts})

    def stats(self) -> dict:
        return {"events": len(self.events), "entities": len(self.entities),
                "relationships": len(self.relationships), "facts": len(self.facts)}

    # ---- internals ----
    def _append(self, kind: str, payload: dict, summary: str) -> None:
        event = {"id": f"evt_{len(self.events) + 1}", "seq": len(self.events) + 1, "kind": kind,
                 "payload": payload, "at": payload.get("updatedAt") or payload.get("validFrom") or payload.get("assertedAt")}
        self._apply(event)
        self.audit.append({"seq": len(self.audit) + 1, "kind": kind, "actor": payload["source"]["kind"], "summary": summary})

    def save(self) -> None:
        """Persist the event log (call once per batch of writes; rewriting per event is quadratic)."""
        if self._file:
            with open(self._file, "w") as f:
                json.dump({"events": self.events, "audit": self.audit}, f)

    def _apply(self, event: dict) -> None:
        """Fold one event into state. Re-applying the same facts or edges changes nothing."""
        self.events.append(event)
        p = event["payload"]
        if event["kind"] == "upsertEntity":
            cur = self.entities.get(p["id"])
            if cur:
                cur["attrs"] = {**cur["attrs"], **p["attrs"]}
                cur["updatedAt"], cur["source"], cur["name"] = p["updatedAt"], p["source"], p["name"]
            else:
                self.entities[p["id"]] = json.loads(json.dumps({**p, "aliases": []}))
        elif event["kind"] == "relate":
            for other in self.relationships.values():  # a new open edge with a different target closes the old one
                if (other["from"], other["type"], other.get("context") or "") == (p["from"], p["type"], p.get("context") or "") \
                        and other["to"] != p["to"] and not other.get("validTo"):
                    other["validTo"], other["supersededBy"] = p["validFrom"], p["id"]
            self.relationships.setdefault(p["id"], json.loads(json.dumps(p)))
        elif event["kind"] == "assertFact":
            self.facts.setdefault(p["id"], json.loads(json.dumps(p)))
