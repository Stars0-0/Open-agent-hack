"""Ringbreaker tests. FakeModel stands in for Nightshift ONLY in tests so the loop runs offline; real SQL runs on the sample data."""
import json
import os

os.environ["SAMPLE_MODE"] = "true"

from app.ringbreaker import run_ring  # noqa: E402

TRUTH = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "ground_truth.json")))


class FakeModel:
    """Plans only phone/address/shop first, so the vehicle ring members need the Critic-driven escalation."""
    def __call__(self, messages):
        s = messages[0]["content"]
        if "Classify a fraud" in s:
            out = {"intent": "sweep", "target": None}
        elif "plan a fraud-ring" in s:
            out = {"hops": ["shared_phone", "shared_address", "shared_shop"], "reason": "cheap first"}
        elif "could not corroborate" in s:
            out = {"hops": ["shared_vehicle"], "reason": "independent evidence"}
        elif "adversarial" in s:
            out = {"doubts": ["Claims could cluster at one shop by coincidence of geography."]}
        else:
            out = {"headline": "One ring found", "summary": "Linked claims.", "recommended_action": "Refer to SIU.",
                   "confidence": 0.8, "confidence_reasoning": "multiple independent link types"}
        return {"content": json.dumps(out), "model": "fake/test-model"}


def _run(query="Sweep the whole book for fraud rings", model=None):
    return run_ring({"request_id": "t", "user_query": query}, chat=model or FakeModel())


def test_finds_exactly_the_planted_ring_after_escalation():
    res = _run()
    rings = res["result"]["rings"]
    assert len(rings) == 1
    assert rings[0]["claims"] == TRUTH["ring_claims"]
    assert sorted(rings[0]["people"]) == TRUTH["ring_people"]
    assert abs(rings[0]["exposure"] - TRUTH["ring_exposure"]) < 0.01
    assert res["collaboration"]["revision_count"] == 1, "vehicle-linked claims must need a Critic-driven second round"


def test_innocent_lookalikes_are_rejected_with_reasons_and_near_ring_stays_a_lead():
    res = _run()["result"]
    reasons = " | ".join(g["reason"] for g in res["rejected"])
    assert "multi-unit building" in reasons and "same surname" in reasons and "busy shop" in reasons
    in_ring = set(res["rings"][0]["claims"])
    assert not in_ring & {c for l in res["unconfirmed_leads"] for c in l["claims"]}  # leads are claims NOT in the ring
    assert all(l["shop"] == TRUTH["ring_shop"] for l in res["unconfirmed_leads"])  # other claims at the ring shop stay unconfirmed


def test_different_requests_route_differently():
    class Conn(FakeModel):
        def __call__(self, m):
            if "Classify a fraud" in m[0]["content"]:
                return {"content": json.dumps({"intent": "connections", "target": TRUTH["ring_people"][0]}), "model": "fake/test-model"}
            return super().__call__(m)
    assert len(_run("who is connected to " + TRUTH["ring_people"][0], Conn())["result"]["rings"]) == 1

    class Nobody(Conn):
        def __call__(self, m):
            if "Classify a fraud" in m[0]["content"]:
                return {"content": json.dumps({"intent": "connections", "target": "Nobody Atall"}), "model": "fake/test-model"}
            return FakeModel.__call__(self, m)
    assert _run("who is connected to Nobody Atall", Nobody())["result"]["rings"] == []


def test_audit_shop_returns_only_rings_touching_that_shop():
    def shop_model(target):
        class M(FakeModel):
            def __call__(self, m):
                if "Classify a fraud" in m[0]["content"]:
                    return {"content": json.dumps({"intent": "audit_shop", "target": target}), "model": "fake/test-model"}
                return FakeModel.__call__(self, m)
        return M()
    assert len(_run("audit Quickfix", shop_model("Quickfix"))["result"]["rings"]) == 1
    assert _run("audit Central", shop_model("Central Motors"))["result"]["rings"] == []
    assert _run("audit injection", shop_model("x' OR '1'='1"))["result"]["rings"] == []  # input is sanitised


def test_garbled_model_output_falls_back_instead_of_crashing():
    class Junk(FakeModel):
        def __call__(self, m):
            if "Classify a fraud" in m[0]["content"] or "plan a fraud-ring" in m[0]["content"]:
                return {"content": "not json at all", "model": "fake/test-model"}
            return super().__call__(m)
    assert len(_run(model=Junk())["result"]["rings"]) == 1  # default hops + sweep still find the ring (escalate falls back to untried)


def test_log_shows_agents_rejections_and_models_and_case_file_exists():
    res = _run()
    events = [json.loads(line) for line in open(res["log_path"])]
    assert {"RouterAgent", "PlannerAgent", "ExecutorAgent", "CriticAgent", "NarratorAgent"} <= {e["agent_name"] for e in events}
    assert any(e["status"] == "rejected" for e in events) and any(e["model"] == "fake/test-model" for e in events)
    case = os.path.join(os.path.dirname(res["log_path"]), "cases", res["trace_id"] + ".html")
    assert "Referral for human review" in open(case).read()


def test_no_secrets_in_repo_files():
    root = os.path.join(os.path.dirname(__file__), "..")
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", "logs"}]
        for f in files:
            if f.endswith((".py", ".md", ".txt", ".example")):
                assert "s" + "k-" not in open(os.path.join(dirpath, f), errors="ignore").read(), f
