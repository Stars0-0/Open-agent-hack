# Ringbreaker: federated fraud-ring investigator

Open Agent Hackathon 2026, track "The Agent That Can Explain Why".

Fraud rings look like unrelated one-off claims inside each insurer. Ringbreaker queries several insurers' claim
databases and shared directories in place through Zetaris (nothing is centralised), finds claims linked by phone,
address, vehicle or repair shop, then tries to prove every link is coincidence before keeping it. Output is a
referral for a human investigator with the SQL behind every link, never an accusation.
**All data in this repo is synthetic.**

## How it works
1. RouterAgent: model classifies the request (sweep the book / who is connected to a person / audit a shop).
2. PlannerAgent: model picks which hops to run (shared phone, address, vehicle, shop).
3. ExecutorAgent: runs the hops in parallel as federated SQL through Zetaris (one query unions the three insurers).
4. CriticAgent: rules that cite their own SQL reject innocent coincidences (apartment block, family phone, busy shop);
   claims attached to a ring only by a shop are "unconfirmed leads" and the Critic sends the Planner back for corroborating hops (feedback loop).
5. Graph builder reads the surviving links back from the World Model and clusters rings.
6. NarratorAgent writes the case file; the Critic also asks the model for the strongest remaining innocent explanation.
Output: JSON plus an HTML case file at `GET /case/<trace_id>` (print to PDF from the browser).

## Meterless engine
World Model (Python port of the spec core, see app/engines/README.md) is the shared evidence ledger: the Executor and Critic write
claims, links, SQL provenance and verdicts; the graph builder reads them back. Tests: tests/test_world_model.py.
Not claimed: Scout Intent (the router is a plain model call), full World Model conformance.

## Setup
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env              # fill Zetaris and Nightshift values; set RB_TABLE_* if your catalog names differ
    python scripts/make_ring_data.py  # writes data/sample/*.csv; load them into Zetaris as separate sources
    python run.py
    curl -X POST localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json

Models: every call goes through Meterless Nightshift; the model that answered is logged on each call in logs/<trace_id>.jsonl.
SAMPLE_MODE=true reads the sample CSVs locally instead of Zetaris (models still need Nightshift).

## Tests
    python -m pytest -q tests
Tests use a scripted stand-in for the model (tests only) to check the loop against planted ground truth: exactly the 14 ring
claims and 9 people are found, innocent look-alikes are rejected with reasons, and the vehicle-linked claims only appear after the Critic-driven second round.

## Safety measures
- /run validates input (1 to 2000 chars, not blank); the server binds to 127.0.0.1 unless HOST is set (Docker sets 0.0.0.0). /run has no authentication: keep it local.
- Every response states its data layer (`zetaris`, or `sample-csv ... NOT Zetaris`), so sample runs are never presented as Zetaris.
- A capped SQL result marks the run `partial` with a warning instead of silently dropping links.
- If the model is down or returns bad JSON: the Router and Planner fall back to a full sweep; the Narrator falls back to a plain facts summary labelled `narrated_by: fallback`.
- Model-derived text used in SQL is sanitised or escaped; /case/<id> blocks path traversal; error bodies never contain tokens.

## Status and limitations (honest)
- Not yet verified against live Zetaris and Nightshift; output_examples/ must be generated from a real run.
- The Zetaris SQL dialect is assumed ANSI (subqueries, UNION ALL, joins, COUNT); table names configurable via RB_TABLE_*.
- Hops are SQL templates chosen by the model, not model-written SQL. Rejection rules are deterministic.
- Synthetic data only. Real use needs data-sharing agreements and a legal review; the system only produces referrals.
