"""World Model engine tests: the rulings ported from Meterless/engines/world-model, plus use inside the agent loop."""
import json
import os

os.environ["SAMPLE_MODE"] = "true"

from app.engines.world_model import WorldModel, entity_id, normalize_name  # noqa: E402
from tests.test_loop import FakeModel  # noqa: E402

S = {"kind": "test", "at": "2026-03-01T00:00:00+00:00", "ref": "SELECT 1"}


def test_stable_ids_and_normalization():
    assert normalize_name("  José   GARCÍA​ ") == "jose garcia"
    assert entity_id("cause", "Jose Garcia") == entity_id("cause", "  josé  garcia ")
    assert entity_id("cause", "Acme Corp") != entity_id("cause", "Acme Corporation")  # no over-normalization
    assert entity_id("cause", "x") != entity_id("metric", "x")


def test_reingest_is_idempotent():
    def ingest(wm):
        c = wm.upsert_entity("cause", "refunds", S, {"explanation": "e"})
        g = wm.upsert_entity("gap", "gap march", S)
        wm.assert_fact(c, "amount", 10.5, S)
        wm.relate(c, "explains", g, S)
    wm = WorldModel("t")
    ingest(wm)
    before = wm.snapshot()
    ingest(wm)
    assert wm.snapshot() == before


def test_new_open_edge_with_different_target_supersedes_old_one():
    wm = WorldModel("t")
    a, b, c = (wm.upsert_entity("cause", n, S) for n in "abc")
    wm.relate(a, "explains", b, S)
    wm.relate(a, "explains", c, {**S, "at": "2026-03-02T00:00:00+00:00"})
    open_ = wm.open_relationships(a, "explains")
    assert [r["to"] for r in open_] == [c]
    assert len(wm.relationships) == 2  # nothing deleted


def test_persistence_replays_to_same_state(tmp_path):
    wm = WorldModel("t", str(tmp_path))
    wm.assert_fact(wm.upsert_entity("cause", "x", S), "amount", 1, S)
    again = WorldModel("t", str(tmp_path))
    assert again.snapshot() == wm.snapshot()


def test_agents_share_state_through_world_model():
    from app.agents import run_agent
    res = run_agent({"user_query": "Why do the two revenue numbers differ in March 2026?"}, chat=FakeModel())
    stats = res["world_model"]
    assert stats["entities"] >= 4 and stats["facts"] >= 7 and stats["relationships"] >= 3
    saved = json.load(open(os.path.join(os.path.dirname(res["log_path"]), "world", res["trace_id"] + ".json")))
    actors = {a["actor"] for a in saved["audit"]}
    assert {"PlannerAgent", "ExecutorAgent", "EvaluatorAgent"} <= actors  # all three agents wrote to it
