# Meterless Engine: World Model

`world_model.py` is a Python port of the core of the open World Model spec
(github.com/Meterless/Meterless, engines/world-model). Subset only: stable content-addressed IDs,
append-only event log folded into entities, relationships and facts, superseding edges, provenance-derived
timestamps (idempotent re-ingest), audit log, JSON persistence. Not ported: fuzzy entity merge, contexts,
stories, scoring, control plane. The TypeScript conformance suite was not run against it.

How the app uses it (app/ringbreaker.py): the shared evidence ledger.
- ExecutorAgent writes claims (entities) and each link as a relationship whose provenance is the SQL that found it.
- CriticAgent writes a verdict fact per link (strong or weak) and a fact per rejected pattern with the rule and its SQL.
- The graph builder reads relationships and verdicts back from the World Model to cluster rings.
Each run persists to logs/world/<trace_id>.json. Tests: tests/test_world_model.py.
