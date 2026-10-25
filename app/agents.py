"""Planner / Executor / Evaluator loop that explains why two business numbers disagree.

Flow: Planner plans -> Executor queries Zetaris and drafts -> Evaluator critiques ->
if the gap is not explained, Planner proposes NEW hypotheses -> Executor revises -> Evaluator re-reviews.
All model calls go through llm.chat (Meterless Nightshift); all data through adapters.zetaris.
"""
import json
import os
from datetime import datetime, timezone

from .adapters import zetaris
from .engines.world_model import WorldModel
from .llm import chat as nightshift_chat, extract_json
from .tracing import Tracer

TOLERANCE = 0.03   # evaluator approves when unexplained <= 3% of the gap
MAX_ROUNDS = 3
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schema.md")

PLAN_FORMAT = """Reply with ONE JSON object only:
{"objective": str, "period": str,
 "sales_sql": "SQL returning one number named value: the first metric the user compares",
 "finance_sql": "SQL returning one number named value: the second metric the user compares",
 "hypotheses": [{"name": str, "explanation": str,
   "sql": "SQL returning one number named amount: how much this cause adds to (first metric - second metric); signed"}]}
Use only tables and columns in the schema. Hypotheses must not overlap (each euro explained once)."""


def _src(kind: str, ref: str | None = None) -> dict:
    """Provenance for a world-model write: who observed it, when, and the evidence (SQL)."""
    return {"kind": kind, "at": datetime.now(timezone.utc).isoformat(timespec="microseconds"), "ref": ref}


def findings(wm: WorldModel) -> list[dict]:
    """Causes the agents have recorded in the shared World Model, with their latest amount and SQL."""
    out = []
    for e in wm.entities_of("cause"):
        amt = wm.latest_fact(e["id"], "amount")
        if amt:
            out.append({"name": e["name"], "explanation": e["attrs"].get("explanation", ""),
                        "amount": amt["value"], "sql": amt["source"]["ref"]})
    return out


class Agent:
    def __init__(self, name: str, tracer: Tracer, chat):
        self.name, self.tracer, self.chat = name, tracer, chat

    def ask(self, action: str, system: str, user: str, target: str | None = None, retry: int = 0) -> dict:
        """One model call that must return JSON; logs the model that answered."""
        r = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        try:
            data = extract_json(r["content"])
        except ValueError as e:
            self.tracer.log(self.name, action, user, f"bad JSON: {e}", target, r["model"], status="error", retry_count=retry)
            raise
        self.tracer.log(self.name, action, user, json.dumps(data)[:300], target, r["model"], retry_count=retry)
        return data


class PlannerAgent(Agent):
    def plan(self, query: str) -> dict:
        schema = open(SCHEMA_PATH).read()
        return self.ask("create_plan", "You are a data investigator. Plan how to explain a disagreement between two numbers.\n"
                        + PLAN_FORMAT, f"Schema:\n{schema}\n\nQuestion: {query}", "ExecutorAgent")

    def replan(self, query: str, plan: dict, state: dict, critique: dict) -> list[dict]:
        """Propose NEW hypotheses for the unexplained part; never repeat tried ones."""
        schema = open(SCHEMA_PATH).read()
        out = self.ask(
            "revise_plan",
            "You revise an investigation plan after the evaluator found gaps. Reply with ONE JSON object: "
            '{"hypotheses": [{"name": str, "explanation": str, "sql": "SQL returning one number named amount (signed)"}]}. '
            "Do not repeat hypotheses already tried. Fix overlaps the evaluator reported.",
            f"Schema:\n{schema}\n\nQuestion: {query}\nGap: {state['gap']}\nExplained so far: {state['explained']}\n"
            f"Tried: {[h['name'] for h in findings(state['wm'])]}\nEvaluator critique: {json.dumps(critique)}",
            "ExecutorAgent")
        return out.get("hypotheses", [])

    def finalise(self, state: dict, review: dict) -> dict:
        unexplained = state["unexplained"]
        confidence = max(0.0, round(1 - abs(unexplained) / abs(state["gap"]), 2)) if state["gap"] else 1.0
        self.tracer.log(self.name, "finalise", f"approved={review['approved']}", f"confidence={confidence}",
                        "User", confidence=confidence)
        return {"summary": state["summary"], "gap": state["gap"], "explained": state["explained"],
                "unexplained": unexplained, "confidence": confidence, "findings": findings(state["wm"])}


class ExecutorAgent(Agent):
    def _run(self, label: str, sql: str, column: str) -> tuple[float, str]:
        """Run SQL through Zetaris; on error ask the model to repair it (max 2 repairs)."""
        for attempt in range(3):
            try:
                value = zetaris.scalar(zetaris.run_sql(sql))
                self.tracer.log(self.name, "query_zetaris", label, f"{column}={value}", "EvaluatorAgent", retry_count=attempt)
                return value, sql
            except Exception as e:  # any data-layer failure is fed back to the model
                self.tracer.log(self.name, "query_zetaris", label, str(e), status="error", retry_count=attempt)
                if attempt == 2:
                    raise
                sql = self.ask("repair_sql", f"Fix the SQL. Reply with ONE JSON object: {{\"sql\": str}}. "
                               f"It must return one number named {column}.",
                               f"Schema:\n{open(SCHEMA_PATH).read()}\nSQL:\n{sql}\nError: {e}", retry=attempt + 1)["sql"]
        raise RuntimeError("unreachable")

    def run_hypotheses(self, hypotheses: list[dict], wm: WorldModel, gap_id: str) -> None:
        """Query each hypothesis and record cause, amount (with its SQL as provenance) and link in the World Model."""
        for h in hypotheses:
            try:
                amount, sql = self._run(h["name"], h["sql"], "amount")
            except Exception as e:
                self.tracer.log(self.name, "drop_hypothesis", h["name"], str(e), status="error")
                continue
            src = _src("ExecutorAgent", sql)
            cid = wm.upsert_entity("cause", h["name"], src, {"explanation": h.get("explanation", "")})
            wm.assert_fact(cid, "amount", round(amount, 2), src)
            wm.relate(cid, "explains", gap_id, src)

    def draft(self, query: str, plan: dict, state: dict) -> dict:
        """Compute totals in code and have the model write the summary from those exact numbers."""
        if "metrics" not in state:
            first, sql_a = self._run("first metric", plan["sales_sql"], "value")
            second, sql_b = self._run("second metric", plan["finance_sql"], "value")
            state["metrics"] = {"first": round(first, 2), "second": round(second, 2), "sql_first": sql_a, "sql_second": sql_b}
        m = state["metrics"]
        state["gap"] = round(m["first"] - m["second"], 2)
        found = findings(state["wm"])
        state["explained"] = round(sum(f["amount"] for f in found), 2)
        state["unexplained"] = round(state["gap"] - state["explained"], 2)
        out = self.ask("write_summary", "Write a short plain-English explanation of why the two numbers differ. "
                       'Use ONLY the numbers given. Reply with ONE JSON object: {"summary": str}.',
                       json.dumps({"question": query, "metrics": m, "gap": state["gap"], "causes": found,
                                   "unexplained": state["unexplained"]}), "EvaluatorAgent")
        state["summary"] = out["summary"]
        state["wm"].assert_fact(state["gap_id"], "gap", state["gap"], _src("ExecutorAgent", m["sql_first"] + " ; " + m["sql_second"]))
        return state


class EvaluatorAgent(Agent):
    def review(self, query: str, state: dict) -> dict:
        """Deterministic arithmetic/evidence checks first, then a model critique of the written summary."""
        issues = []
        gap = state["gap"]
        if gap and abs(state["unexplained"]) / abs(gap) > TOLERANCE:
            issues.append(f"unexplained amount {state['unexplained']} is {abs(state['unexplained']) / abs(gap):.0%} of the gap {gap}; "
                          f"find the missing cause(s)")
        seen = {}
        found = findings(state["wm"])
        for f in found:
            if f["amount"] != 0 and f["amount"] in seen:
                issues.append(f"'{f['name']}' and '{seen[f['amount']]}' have identical amounts {f['amount']}: likely double counting")
            seen[f["amount"]] = f["name"]
            if not f.get("sql"):
                issues.append(f"'{f['name']}' has no SQL evidence")
        critique = self.ask("critique_summary", "You are a strict reviewer. Check that every number and claim in the summary "
                            "matches the causes given. Reply with ONE JSON object: {\"unsupported_claims\": [str]}.",
                            json.dumps({"summary": state["summary"], "causes": found, "gap": gap}), "PlannerAgent")
        issues += [f"unsupported claim: {c}" for c in critique.get("unsupported_claims", [])]
        review = {"approved": not issues, "requires_revision": bool(issues), "issues": issues}
        state["wm"].assert_fact(state["gap_id"], "evaluation", review, _src("EvaluatorAgent"))
        self.tracer.log(self.name, "review", f"unexplained={state['unexplained']}", json.dumps(review)[:300], "PlannerAgent",
                        status="approved" if review["approved"] else "rejected")
        return review


def run_agent(request: dict, chat=nightshift_chat) -> dict:
    tracer = Tracer()
    planner, executor, evaluator = (cls(n, tracer, chat) for cls, n in
                                    [(PlannerAgent, "PlannerAgent"), (ExecutorAgent, "ExecutorAgent"), (EvaluatorAgent, "EvaluatorAgent")])
    query = request["user_query"]
    tracer.log("PlannerAgent", "receive_request", query, "", "PlannerAgent")
    plan = planner.plan(query)
    wm = WorldModel(tracer.trace_id, directory=os.path.join(os.path.dirname(tracer.path), "world"))
    gap_id = wm.upsert_entity("gap", f"gap {plan.get('period', query)}", _src("PlannerAgent"), {"question": query})
    state = {"wm": wm, "gap_id": gap_id}
    executor.run_hypotheses(plan.get("hypotheses", []), wm, gap_id)
    revisions, evaluator_findings = 0, []
    for round_ in range(MAX_ROUNDS):
        executor.draft(query, plan, state)
        review = evaluator.review(query, state)
        if review["approved"]:
            break
        evaluator_findings += review["issues"]
        if round_ == MAX_ROUNDS - 1:
            break
        revisions += 1
        new = planner.replan(query, plan, state, review)
        known = {f["name"] for f in findings(wm)}
        executor.run_hypotheses([h for h in new if h["name"] not in known], wm, gap_id)
    result = planner.finalise(state, review)
    return {"request_id": request.get("request_id"), "trace_id": tracer.trace_id,
            "status": "success" if review["approved"] else "partial",
            "agents_used": ["PlannerAgent", "ExecutorAgent", "EvaluatorAgent"],
            "result": result,
            "collaboration": {"feedback_loop_completed": revisions > 0 or review["approved"], "revision_count": revisions,
                              "evaluator_findings": evaluator_findings},
            "world_model": wm.stats(),
            "log_path": os.path.relpath(tracer.path)}
