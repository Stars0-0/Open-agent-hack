"""Hardening tests: input limits, data-layer label, truncation warning, narrator fallback, no cross-request leakage."""
import json
import os

os.environ["SAMPLE_MODE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

import app.ringbreaker as rb  # noqa: E402
import run  # noqa: E402
from tests.test_ring import FakeModel  # noqa: E402


def test_input_validation_rejects_empty_blank_and_huge_queries():
    c = TestClient(run.app)
    for q in ["", "   ", "x" * 2001]:
        assert c.post("/run", json={"user_query": q}).status_code == 422
    assert c.post("/run", json={"user_query": "x" * 100, "request_id": "r" * 101}).status_code == 422


def test_response_labels_sample_data_layer_and_health_agrees():
    res = rb.run_ring({"user_query": "sweep"}, chat=FakeModel())
    assert "NOT Zetaris" in res["data_layer"]
    assert "NOT Zetaris" in TestClient(run.app).get("/health").json()["data_layer"]


def test_truncated_hop_marks_run_partial_with_warning(monkeypatch):
    monkeypatch.setattr(rb, "SQL_LIMIT", 100)  # shop hop returns thousands of pairs, so it must hit this
    res = rb.run_ring({"user_query": "sweep"}, chat=FakeModel())
    assert res["status"] == "partial" and res["result"]["warnings"]
    assert "limit" in open(os.path.join(os.path.dirname(res["log_path"]), "cases", res["trace_id"] + ".html")).read()


def test_warnings_do_not_leak_between_requests(monkeypatch):
    monkeypatch.setattr(rb, "SQL_LIMIT", 100)
    rb.run_ring({"user_query": "sweep"}, chat=FakeModel())
    monkeypatch.setattr(rb, "SQL_LIMIT", 20000)
    assert rb.run_ring({"user_query": "sweep"}, chat=FakeModel())["status"] == "success"


def test_narrator_falls_back_to_labelled_facts_when_model_returns_junk():
    class Junk(FakeModel):
        def __call__(self, m):
            if "case file" in m[0]["content"]:
                return {"content": "no json here", "model": "fake/test-model"}
            return super().__call__(m)
    res = rb.run_ring({"user_query": "sweep"}, chat=Junk())
    n = res["result"]["narrative"]
    assert res["status"] == "success" and n["narrated_by"] == "fallback" and n["confidence"] is None
    assert any(json.loads(l)["action"] == "narrator_fallback" for l in open(res["log_path"]))


def test_run_binds_localhost_by_default():
    assert "127.0.0.1" in open(os.path.join(os.path.dirname(run.__file__), "run.py")).read()
