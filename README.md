# Open-agent-hack: "Why do these two numbers disagree?"

Track: The Agent That Can Explain Why (Open Agent Hackathon 2026).

An agent that takes a question like "why doesn't sales revenue match finance revenue for March?",
queries three disconnected systems (orders, payments, refunds) through Zetaris, splits the gap into
causes with the SQL behind each number, and only approves when the unexplained remainder is within 3%.

## Status (honest)
- Done: planner/executor/evaluator loop with rejection and revision, SQL self-repair, JSONL traces with the model logged, FastAPI `POST /run`, sample data with planted causes, offline tests.
- Meterless World Model engine (Python port of the spec core, see app/engines/README.md) is shared state for all three agents, with tests.
- NOT done yet: real output_examples, Docker run check, live test against Zetaris and Nightshift.

## Agents
- PlannerAgent: plans metrics and hypotheses; re-plans with NEW hypotheses when rejected.
- ExecutorAgent: runs SQL via Zetaris (repairs failing SQL), drafts the explanation.
- EvaluatorAgent: deterministic arithmetic check plus a model critique of the summary.

## Setup
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in Zetaris and Nightshift values
    python scripts/make_data.py   # writes data/sample/*.csv (load these into Zetaris as three sources)
    python run.py
    curl -X POST localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json

Edit data/schema.md so table names match your Zetaris catalog. SAMPLE_MODE=true reads the sample CSVs
locally instead of Zetaris; model calls still need Nightshift.

## Tests
    python -m pytest -q tests
The tests use a scripted stand-in for the model (tests only) to check the loop against ground truth.

## Limitations
Reconciles two numeric metrics over one period; schema is described in data/schema.md; model-written SQL can be wrong (the evaluator and SQL repair are there for that).
