# Meterless Engine: World Model

`world_model.py` is a Python port of the core of the open World Model spec
(github.com/Meterless/Meterless, engines/world-model). Subset only: stable content-addressed IDs,
append-only event log folded into entities, relationships and facts, superseding edges, provenance-derived
timestamps (idempotent re-ingest), audit log, JSON persistence. Not ported: fuzzy entity merge, contexts,
stories, scoring, control plane. The TypeScript conformance suite was not run against it.

How the app uses it (app/agents.py): all three agents share it as their working state.
- ExecutorAgent writes each cause as an entity, its amount as a fact whose provenance is the SQL it ran, and an `explains` edge to the gap.
- EvaluatorAgent writes each verdict as an `evaluation` fact and reads causes back to check the arithmetic.
- PlannerAgent reads it to avoid repeating tried hypotheses.
Each run persists to logs/world/<trace_id>.json. Tests: tests/test_world_model.py.
