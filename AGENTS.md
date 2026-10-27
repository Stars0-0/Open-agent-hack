# Project rules (read before editing)
- Open Agent Hackathon 2026, Track 2 "The Agent That Can Explain Why". Deadline 27 Oct 23:45 UTC.
- Secrets only from .env. Never commit .env or keys. Keep .env.example in sync with the code.
- All model calls go through app/llm.py (Meterless Nightshift). Log the returned model on every call.
- All data goes through app/adapters/zetaris.py. Never mock Zetaris outside SAMPLE_MODE and tests.
- No hardcoded outputs. output_examples/ must never be read by runtime code.
- The Critic's rejection rules stay deterministic and cite their SQL; the model only plans, narrates and raises doubts.
- After any change run: python -m pytest -q tests
- Keep code small and readable; one comment per non-obvious function saying what and why.
