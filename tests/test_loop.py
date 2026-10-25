"""Loop tests. FakeModel stands in for Nightshift ONLY in tests so the loop runs offline; real data (sample CSVs) is queried."""
import json
import os

os.environ["SAMPLE_MODE"] = "true"

from app.agents import run_agent  # noqa: E402

TRUTH = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "ground_truth.json")))
M = "order_date >= '2026-03-01' AND order_date < '2026-04-01'"
CANCELLED = f"SELECT SUM(amount) AS amount FROM orders WHERE status='cancelled' AND {M}"
REFUNDS = "SELECT SUM(amount) AS amount FROM refunds WHERE refund_date >= '2026-03-01' AND refund_date < '2026-04-01'"
TIMING = ("SELECT (SELECT COALESCE(SUM(o.amount),0) FROM orders o JOIN payments p ON p.order_id=o.order_id "
          "WHERE o.order_date >= '2026-03-01' AND o.order_date < '2026-04-01' AND NOT (p.paid_date >= '2026-03-01' AND p.paid_date < '2026-04-01')) "
          "- (SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN orders o ON o.order_id=p.order_id "
          "WHERE p.paid_date >= '2026-03-01' AND p.paid_date < '2026-04-01' AND o.order_date < '2026-03-01') AS amount")


class FakeModel:
    """First plan misses refunds and timing; revise_plan supplies them; critic always passes."""
    def __init__(self):
        self.calls = []

    def __call__(self, messages):
        sys_prompt = messages[0]["content"]
        self.calls.append(sys_prompt[:30])
        if "Plan how to explain" in sys_prompt:
            out = {"objective": "x", "period": "2026-03",
                   "sales_sql": f"SELECT SUM(amount) AS value FROM orders WHERE {M}",
                   "finance_sql": ("SELECT (SELECT SUM(amount) FROM payments WHERE paid_date >= '2026-03-01' AND paid_date < '2026-04-01') "
                                   "- (SELECT SUM(amount) FROM refunds WHERE refund_date >= '2026-03-01' AND refund_date < '2026-04-01') AS value"),
                   "hypotheses": [{"name": "cancelled orders", "explanation": "no payment", "sql": CANCELLED}]}
        elif "revise an investigation" in sys_prompt:
            out = {"hypotheses": [{"name": "refunds", "explanation": "finance subtracts", "sql": REFUNDS},
                                  {"name": "month boundary timing", "explanation": "paid next month", "sql": TIMING}]}
        elif "short plain-English" in sys_prompt:
            out = {"summary": "gap explained by listed causes"}
        elif "strict reviewer" in sys_prompt:
            out = {"unsupported_claims": []}
        else:
            out = {"sql": "SELECT 1 AS amount"}
        return {"content": json.dumps(out), "model": "fake/test-model"}


def test_evaluator_rejects_then_agent_recovers_and_matches_ground_truth():
    res = run_agent({"request_id": "t1", "user_query": "Why does sales revenue differ from finance revenue for March 2026?"}, chat=FakeModel())
    assert res["collaboration"]["revision_count"] == 1, "first draft must be rejected once"
    assert res["status"] == "success"
    found = {f["name"]: f["amount"] for f in res["result"]["findings"]}
    assert found["cancelled orders"] == TRUTH["causes"]["cancelled_orders"]
    assert found["refunds"] == TRUTH["causes"]["refunds"]
    assert found["month boundary timing"] == TRUTH["causes"]["month_boundary_timing"]
    assert abs(res["result"]["gap"] - TRUTH["gap"]) < 0.01


def test_log_has_three_agents_a_rejection_and_the_model():
    res = run_agent({"user_query": "Why do the two revenue numbers differ in March 2026?"}, chat=FakeModel())
    events = [json.loads(line) for line in open(res["log_path"])]
    assert {"PlannerAgent", "ExecutorAgent", "EvaluatorAgent"} <= {e["agent_name"] for e in events}
    assert any(e["action"] == "review" and e["status"] == "rejected" for e in events)
    assert any(e["model"] == "fake/test-model" for e in events)


def test_no_secrets_in_repo_files():
    root = os.path.join(os.path.dirname(__file__), "..")
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", "logs"}]
        for f in files:
            if f.endswith((".py", ".md", ".txt", ".example")):
                assert "s" + "k-" not in open(os.path.join(dirpath, f), errors="ignore").read(), f
