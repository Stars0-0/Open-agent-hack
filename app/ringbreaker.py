"""Ringbreaker: a federated fraud-ring investigator (referrals for a human investigator, never accusations).

Loop: Router (intent) -> Planner (which hops) -> Executor swarm (parallel federated SQL via Zetaris)
-> Critic (tries to prove each link is coincidence; drops weak ones) -> if some claims are only weakly
attached, Planner escalates with new hops -> Graph builder -> Narrator.
Shared state is the Meterless World Model (app/engines/world_model.py). All model calls go through Nightshift.
"""
from __future__ import annotations
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .adapters import zetaris
from .engines.world_model import WorldModel
from .llm import chat as nightshift_chat, extract_json
from .tracing import Tracer

MAX_ROUNDS = 3
BUSY_SHARE = 0.10     # a shop with >10% of ALL claims explains any two claims sharing it
BLOCK_UNITS = 10      # an address with >=10 units explains any two claims sharing it
SQL_LIMIT = 20000

# Table names as they appear in your Zetaris catalog (defaults match the sample CSV names).
T = {k: os.getenv(f"RB_TABLE_{k.upper()}", d) for k, d in
     [("a", "insurer_a_claims"), ("b", "insurer_b_claims"), ("c", "insurer_c_claims"),
      ("shops", "repair_shops"), ("addresses", "address_directory")]}
UNION = " UNION ALL ".join(
    f"SELECT '{i.upper()}' AS insurer, claim_id, claimant_name, phone, address, vin, shop_id, amount FROM {T[i]}" for i in "abc")
HOPS = {  # kind -> (column, what the planner is told)
    "shared_phone": ("phone", "claims by different people or insurers that share a phone number"),
    "shared_address": ("address", "claims that share a home address"),
    "shared_vehicle": ("vin", "claims on the same vehicle (VIN), possibly by different claimants"),
    "shared_shop": ("shop_id", "claims repaired at the same shop"),
}
DEFAULT_HOPS = ["shared_phone", "shared_address", "shared_shop"]
INTENTS = ["sweep", "connections", "audit_shop"]


def _src(kind: str, ref: str | None = None) -> dict:
    """Provenance for a World Model write: who observed it, when, and the evidence (SQL)."""
    return {"kind": kind, "at": datetime.now(timezone.utc).isoformat(timespec="microseconds"), "ref": ref}


def data_layer() -> str:
    """Which data source answers queries. Reported in every response so sample runs are never mistaken for Zetaris."""
    return "sample-csv (SAMPLE_MODE=true, NOT Zetaris)" if os.getenv("SAMPLE_MODE", "false").lower() == "true" else "zetaris"


def _esc(value: str) -> str:
    return str(value).replace("'", "''")


def hop_sql(kind: str) -> str:
    col = HOPS[kind][0]
    return (f"SELECT a.claim_id AS aid, b.claim_id AS bid, a.claimant_name AS an, b.claimant_name AS bn, "
            f"a.amount AS aamt, b.amount AS bamt, a.insurer AS ai, b.insurer AS bi, a.{col} AS value "
            f"FROM ({UNION}) a JOIN ({UNION}) b ON a.{col} = b.{col} AND a.claim_id < b.claim_id "
            f"WHERE a.{col} <> ''")


class Agent:
    def __init__(self, name: str, tracer: Tracer, chat):
        self.name, self.tracer, self.chat = name, tracer, chat

    def ask(self, action: str, system: str, user: str, target: str | None = None) -> dict:
        """One model call that must return JSON; logs the model that answered."""
        r = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        try:
            data = extract_json(r["content"])
        except ValueError as e:
            self.tracer.log(self.name, action, user, f"bad JSON: {e}", target, r["model"], status="error")
            raise
        self.tracer.log(self.name, action, user, json.dumps(data), target, r["model"])
        return data


class RouterAgent(Agent):
    def route(self, query: str) -> dict:
        """Classify what the user is asking. Unknown or invalid answers fall back to a full sweep."""
        try:
            out = self.ask("classify_intent",
                           "Classify a fraud investigator's request. Reply with ONE JSON object: "
                           '{"intent": "sweep" | "connections" | "audit_shop", "target": string or null}. '
                           "sweep = look for rings across all claims. connections = who is connected to a named person "
                           "(target = the person's name). audit_shop = investigate a repair shop (target = shop name).",
                           query, "PlannerAgent")
            intent = out.get("intent") if out.get("intent") in INTENTS else "sweep"
            target = out.get("target") if isinstance(out.get("target"), str) else None
        except Exception:  # model unavailable or garbled: a sweep is always a safe answer
            intent, target = "sweep", None
        if intent != "sweep" and not target:
            intent = "sweep"
        return {"intent": intent, "target": re.sub(r"[^A-Za-z0-9 .'-]", "", target)[:60] if target else None}


class PlannerAgent(Agent):
    def plan(self, query: str, route: dict) -> list[str]:
        menu = {k: v[1] for k, v in HOPS.items()}
        try:
            out = self.ask("plan_hops", "You plan a fraud-ring investigation over federated claims data. Pick the hops to run "
                           'first. Start cheap; you can escalate later. Reply with ONE JSON object: {"hops": [names], "reason": str}.',
                           json.dumps({"request": query, "intent": route, "available_hops": menu}), "ExecutorAgent")
            hops = [h for h in out.get("hops", []) if h in HOPS]
        except Exception:
            hops = []
        return hops or DEFAULT_HOPS  # an empty or invalid plan must not stop the investigation

    def escalate(self, feedback: dict, tried: list[str]) -> list[str]:
        """The Critic found claims it can't corroborate: choose new hops that could."""
        untried = {k: v[1] for k, v in HOPS.items() if k not in tried}
        if not untried:
            return []
        try:
            out = self.ask("escalate_plan", "The Critic could not corroborate some claims. Choose from the untried hops those "
                           'that could give independent evidence. Reply with ONE JSON object: {"hops": [names], "reason": str}.',
                           json.dumps({"feedback": feedback, "untried_hops": untried}), "ExecutorAgent")
            return [h for h in out.get("hops", []) if h in untried]
        except Exception:
            return list(untried)


class ExecutorAgent(Agent):
    def __init__(self, *a):
        super().__init__(*a)
        self.truncated = []  # per-request list; a class-level list would leak between requests

    def swarm(self, hops: list[str]) -> list[dict]:
        """Run every hop in parallel as federated SQL through Zetaris; return candidate links."""
        def one(kind):
            sql = hop_sql(kind)
            try:
                rows = zetaris.run_sql(sql, SQL_LIMIT)
                if len(rows) >= SQL_LIMIT:  # a capped result silently hides links, so say so
                    self.truncated.append(kind)
                    self.tracer.log(self.name, "query_zetaris", kind, f"hit the {SQL_LIMIT}-row limit: results may be incomplete", "CriticAgent", status="partial")
                self.tracer.log(self.name, "query_zetaris", kind, f"{len(rows)} candidate pairs", "CriticAgent")
                return kind, sql, rows, None
            except Exception as e:
                self.tracer.log(self.name, "query_zetaris", kind, str(e), status="error")
                return kind, sql, [], e
        with ThreadPoolExecutor(max_workers=len(hops)) as pool:
            results = list(pool.map(one, hops))
        if all(r[3] for r in results):
            raise RuntimeError("every hop failed: " + str(results[0][3]))
        links = []
        for kind, sql, rows, err in results:
            for r in rows:
                r = dict(r) if isinstance(r, dict) else dict(zip(["aid", "bid", "an", "bn", "aamt", "bamt", "ai", "bi", "value"], r))
                links.append({"kind": kind, "a": r["aid"], "b": r["bid"], "an": r["an"], "bn": r["bn"], "value": r["value"],
                              "aamt": float(r["aamt"]), "bamt": float(r["bamt"]), "ai": r["ai"], "bi": r["bi"], "sql": sql})
        return links


class CriticAgent(Agent):
    """Tries to prove each candidate link is coincidence. Deterministic rules decide; each rule cites its SQL."""

    def __init__(self, *a):
        super().__init__(*a)
        self.cache, self.total = {}, None

    def _scalar(self, sql: str):
        if sql not in self.cache:
            try:
                self.cache[sql] = zetaris.scalar(zetaris.run_sql(sql))
            except Exception:
                self.cache[sql] = None
        return self.cache[sql]

    def review(self, links: list[dict]) -> tuple[list[dict], list[dict]]:
        """Return (kept links with strength, rejected groups with reason and evidence)."""
        kept, groups = [], {}

        def reject(l, key, reason, sql):
            g = groups.setdefault(key, {"kind": l["kind"], "value": l["value"], "reason": reason, "evidence_sql": sql, "count": 0, "examples": []})
            g["count"] += 1
            if len(g["examples"]) < 3:
                g["examples"].append(f"{l['a']} / {l['b']}")

        for l in links:
            kind, v = l["kind"], l["value"]
            if kind == "shared_phone" and l["an"].split()[-1].lower() == l["bn"].split()[-1].lower() and l["an"] != l["bn"]:
                reject(l, (kind, v), "same surname: a family sharing a phone is innocent", None)
            elif kind == "shared_address":
                sql = f"SELECT unit_count FROM {T['addresses']} WHERE address = '{_esc(v)}'"
                units = self._scalar(sql)
                if units is not None and units >= BLOCK_UNITS:
                    reject(l, (kind, v), f"multi-unit building ({int(units)} units): sharing it is normal", sql)
                else:
                    kept.append({**l, "strength": "strong"})
            elif kind == "shared_shop":
                sql = f"SELECT COUNT(*) AS n FROM ({UNION}) WHERE shop_id = '{_esc(v)}'"
                n = self._scalar(sql)
                if self.total is None:
                    self.total = self._scalar(f"SELECT COUNT(*) AS n FROM ({UNION})") or 1
                share = (n or 0) / self.total
                if share > BUSY_SHARE:
                    reject(l, (kind, v), f"busy shop ({int(n)} claims, {share:.0%} of all claims): sharing it proves nothing", sql)
                else:
                    kept.append({**l, "strength": "weak"})
            elif kind == "shared_vehicle" and l["an"] == l["bn"]:
                reject(l, (kind, v), "same claimant re-claiming the same vehicle is a duplicate, not a ring", None)
            else:
                kept.append({**l, "strength": "strong"})
        for g in groups.values():
            self.tracer.log(self.name, "reject_links", f"{g['kind']} {g['value']}", f"{g['count']} links: {g['reason']}",
                            "PlannerAgent", status="rejected")
        return kept, list(groups.values())

    def challenge(self, rings: list[dict], rejected: list[dict]) -> list[str]:
        """Adversarial model pass over the surviving rings: what innocent explanation is still possible?"""
        if not rings:
            return []
        brief = [{"claims": r["claims"], "link_kinds": sorted({l["kind"] for l in r["links"]}), "people": r["people"]} for r in rings]
        try:
            out = self.ask("challenge_rings", "You are an adversarial fraud reviewer. For each surviving ring, state the most plausible "
                           'INNOCENT explanation that the evidence does not rule out. Reply with ONE JSON object: {"doubts": [str]}.',
                           json.dumps({"rings": brief, "already_rejected_patterns": [g["reason"] for g in rejected][:8]}), "NarratorAgent")
            return [str(d) for d in out.get("doubts", [])][:5]
        except Exception:
            return []


class NarratorAgent(Agent):
    def narrate(self, rings: list[dict], leads: list[dict], rejected: list[dict], doubts: list[str]) -> dict:
        brief = {"rings": [{"id": r["id"], "claims": r["claims"], "people": r["people"], "exposure": r["exposure"],
                            "link_counts": {k: sum(1 for l in r["links"] if l["kind"] == k) for k in {l["kind"] for l in r["links"]}}}
                           for r in rings],
                 "unconfirmed_leads": leads, "rejected": [{k: g[k] for k in ("kind", "reason", "count")} for g in rejected], "critic_doubts": doubts}
        try:
            return self._narrate_with_model(brief)
        except Exception as e:  # model down or garbled: still hand the investigator the facts, labelled as not model-written
            self.tracer.log(self.name, "narrator_fallback", "", f"{type(e).__name__}: {e}", "User", status="error")
            n = len(rings)
            return {"headline": f"{n} possible ring(s) found" if n else "No ring survived the Critic",
                    "summary": f"{n} ring(s) with {sum(len(r['claims']) for r in rings)} claims; {len(leads)} unconfirmed lead(s); "
                               f"{sum(g['count'] for g in rejected)} links rejected as coincidence. Written without the model.",
                    "recommended_action": "Review the evidence for each link below before acting.", "confidence": None,
                    "confidence_reasoning": "not scored: model unavailable", "narrated_by": "fallback"}

    def _narrate_with_model(self, brief: dict) -> dict:
        return self.ask("write_case_file", "Write a short case file for a human fraud investigator. Use ONLY the facts given. Never accuse "
                        "anyone: say these are referrals needing human review. Reply with ONE JSON object: "
                        '{"headline": str, "summary": str, "recommended_action": str, "confidence": number between 0 and 1, '
                        '"confidence_reasoning": str}.', json.dumps(brief), "User")


# ---- graph building (plain code over World Model contents) ----
def _components(nodes, edges):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        parent[find(a)] = find(b)
    comp = {}
    for n in nodes:
        comp.setdefault(find(n), []).append(n)
    return list(comp.values())


def build_graph(kept: list[dict]) -> tuple[list[dict], list[dict]]:
    """Rings = claims joined by strong links; non-busy-shop links bridge groups that are already corroborated.
    Claims attached to a group only by a weak shop link are unconfirmed leads, not part of the ring."""
    strong = [l for l in kept if l["strength"] == "strong"]
    weak = [l for l in kept if l["strength"] == "weak"]
    claims = {c for l in kept for c in (l["a"], l["b"])}
    cores = [c for c in _components(claims, [(l["a"], l["b"]) for l in strong]) if len(c) > 1]
    in_core = {c for core in cores for c in core}
    bridges = [(l["a"], l["b"]) for l in weak if l["a"] in in_core and l["b"] in in_core]
    ring_claims = [sorted(c) for c in _components(in_core, [(l["a"], l["b"]) for l in strong] + bridges)]
    rings = []
    for i, cl in enumerate(sorted(ring_claims, key=lambda c: -len(c)), 1):
        s = set(cl)
        links = [l for l in kept if l["a"] in s and l["b"] in s]
        names, amounts = {}, {}
        for l in links:
            names[l["a"]], names[l["b"]] = l["an"], l["bn"]
            amounts[l["a"]], amounts[l["b"]] = l["aamt"], l["bamt"]
        rings.append({"id": i, "claims": cl, "people": sorted(set(names.values())), "claim_people": names,
                      "exposure": round(sum(amounts.values()), 2), "links": links})
    attached = {}
    for l in weak:  # a claim outside every group that shares a shop with a claim inside one
        for c, other in ((l["a"], l["b"]), (l["b"], l["a"])):
            if c not in in_core and other in in_core:
                attached.setdefault(l["value"], set()).add(c)
    leads = [{"shop": shop, "claims": sorted(cl), "why": "linked to a ring only by a shared repair shop; no corroborating link"}
             for shop, cl in attached.items()]
    return rings, leads


def relevant(links: list[dict]) -> list[dict]:
    """Links worth keeping as evidence: every strong link, plus weak links touching a corroborated group.
    A shop link between two otherwise unrelated claims is explained by the shop, so it is dropped."""
    strong = [l for l in links if l["strength"] == "strong"]
    core = {c for comp in _components({c for l in strong for c in (l["a"], l["b"])}, [(l["a"], l["b"]) for l in strong])
            if len(comp) > 1 for c in comp}
    return [l for l in links if l["strength"] == "strong" or l["a"] in core or l["b"] in core]


def record(wm: WorldModel, links: list[dict], rejected: list[dict]) -> None:
    """Write links (with their SQL as provenance) and rejection groups into the shared World Model."""
    for l in links:
        src = _src("ExecutorAgent", l["sql"])
        a = wm.upsert_entity("claim", l["a"], src, {"claimant": l["an"], "amount": l["aamt"], "insurer": l["ai"]})
        b = wm.upsert_entity("claim", l["b"], src, {"claimant": l["bn"], "amount": l["bamt"], "insurer": l["bi"]})
        rid = wm.relate(a, l["kind"], b, src, context=l["b"])
        wm.assert_fact(rid, "critic_verdict", {"strength": l["strength"], "value": l["value"]}, _src("CriticAgent"))
    for g in rejected:
        gid = wm.upsert_entity("rejected_pattern", f"{g['kind']} {g['value']}", _src("CriticAgent", g["evidence_sql"]), {"reason": g["reason"]})
        wm.assert_fact(gid, "rejected_links", {"count": g["count"], "reason": g["reason"]}, _src("CriticAgent", g["evidence_sql"]))


def links_from_wm(wm: WorldModel) -> list[dict]:
    """Rebuild the surviving links from the World Model (the graph builder reads shared state, not local variables)."""
    out = []
    for r in wm.open_relationships():
        verdict = wm.latest_fact(r["id"], "critic_verdict")
        a, b = wm.entities[r["from"]], wm.entities[r["to"]]
        if verdict:
            out.append({"kind": r["type"], "a": a["name"], "b": b["name"], "an": a["attrs"]["claimant"], "bn": b["attrs"]["claimant"],
                        "aamt": a["attrs"]["amount"], "bamt": b["attrs"]["amount"], "ai": a["attrs"]["insurer"], "bi": b["attrs"]["insurer"],
                        "value": verdict["value"]["value"], "strength": verdict["value"]["strength"], "sql": r["source"]["ref"]})
    return out


def _filter(rings, route):
    """Narrow rings for 'connections' (a named person) or 'audit_shop' (a shop) requests."""
    t = (route.get("target") or "").lower()
    if route["intent"] == "connections":
        return [r for r in rings if any(t in p.lower() for p in r["people"])]
    if route["intent"] == "audit_shop":
        row = zetaris.run_sql(f"SELECT shop_id FROM {T['shops']} WHERE lower(name) LIKE '%{_esc(t)}%' OR lower(shop_id) = '{_esc(t)}'")
        ids = {list(r.values())[0] if isinstance(r, dict) else r[0] for r in row}
        if not ids:
            return []
        keep = []
        for r in rings:
            claim_sql = f"SELECT COUNT(*) AS n FROM ({UNION}) WHERE shop_id IN ({','.join(repr(i) for i in ids)}) AND claim_id IN ({','.join(repr(c) for c in r['claims'])})"
            if zetaris.scalar(zetaris.run_sql(claim_sql)) > 0:
                keep.append(r)
        return keep
    return rings


def run_ring(request: dict, chat=nightshift_chat) -> dict:
    tracer = Tracer()
    router, planner, executor, critic, narrator = (cls(n, tracer, chat) for cls, n in [
        (RouterAgent, "RouterAgent"), (PlannerAgent, "PlannerAgent"), (ExecutorAgent, "ExecutorAgent"),
        (CriticAgent, "CriticAgent"), (NarratorAgent, "NarratorAgent")])
    query = request["user_query"]
    tracer.log("RouterAgent", "receive_request", query, f"data layer: {data_layer()}", "RouterAgent")
    route = router.route(query)
    wm = WorldModel(tracer.trace_id, directory=os.path.join(os.path.dirname(tracer.path), "world"))
    hops, tried, all_kept, all_rejected, findings, revisions, seen = planner.plan(query, route), [], [], [], [], 0, set()
    for round_ in range(MAX_ROUNDS):
        tried += hops
        candidates = executor.swarm(hops)
        kept, rejected = critic.review(candidates)
        all_kept += kept
        all_rejected += rejected
        fresh = [l for l in relevant(all_kept) if (l["a"], l["b"], l["kind"]) not in seen]
        seen.update((l["a"], l["b"], l["kind"]) for l in fresh)
        record(wm, fresh, rejected)
        rings, leads = build_graph(all_kept)
        if not leads:
            break
        findings.append(f"round {round_ + 1}: {sum(len(l['claims']) for l in leads)} claims linked only weakly (shop); needs corroboration")
        feedback = {"unconfirmed_leads": leads, "tried_hops": tried}
        more = planner.escalate(feedback, tried)
        tracer.log("CriticAgent", "request_corroboration", json.dumps(leads)[:200], f"hops={more}", "PlannerAgent",
                   status="rejected" if more else "success")
        if not more:
            break
        hops, revisions = more, revisions + 1
    wm.save()
    rings, leads = build_graph(links_from_wm(wm))  # final graph is read back from shared state
    rings = _filter(rings, route)
    doubts = critic.challenge(rings, all_rejected)
    narrative = narrator.narrate(rings, leads, all_rejected, doubts)
    tracer.log("NarratorAgent", "finalise", f"{len(rings)} rings", narrative.get("headline", ""), "User",
               confidence=narrative.get("confidence"))
    warnings = [f"hop '{k}' hit the {SQL_LIMIT}-row limit; results may be incomplete" for k in sorted(set(executor.truncated))]
    result = {"intent": route, "rings": rings, "unconfirmed_leads": leads, "rejected": all_rejected,
              "critic_doubts": doubts, "narrative": narrative, "warnings": warnings}
    from .casefile import write_case
    write_case(tracer.trace_id, result)
    return {"request_id": request.get("request_id"), "trace_id": tracer.trace_id, "status": "partial" if warnings else "success",
            "data_layer": data_layer(),
            "agents_used": ["RouterAgent", "PlannerAgent", "ExecutorAgent", "CriticAgent", "NarratorAgent"],
            "result": result,
            "collaboration": {"feedback_loop_completed": revisions > 0 or not leads, "revision_count": revisions,
                              "evaluator_findings": findings},
            "world_model": wm.stats(), "case_file_url": f"/case/{tracer.trace_id}",
            "log_path": os.path.relpath(tracer.path)}
