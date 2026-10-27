"""Check each connection on its own: python scripts/smoke_test.py  (reads .env). Prints PASS/FAIL per check."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv

load_dotenv()
from app import llm
from app.adapters import zetaris
from app.ringbreaker import T, UNION


def check(name, fn):
    try:
        print(f"PASS  {name}: {fn()}")
        return True
    except Exception as e:  # show the exact error so it can be fixed
        print(f"FAIL  {name}: {type(e).__name__}: {e}")
        return False


ok = [
    check("Nightshift model call", lambda: llm.chat([{"role": "user", "content": "Reply with the single word: ready"}])),
    check("Zetaris SELECT 1", lambda: zetaris.run_sql("SELECT 1 AS one")),
    check("Zetaris sees insurer A claims", lambda: zetaris.scalar(zetaris.run_sql(f"SELECT COUNT(*) AS n FROM {T['a']}"))),
    check("Zetaris union of 3 insurers", lambda: zetaris.scalar(zetaris.run_sql(f"SELECT COUNT(*) AS n FROM ({UNION})"))),
    check("Zetaris directory tables", lambda: (zetaris.scalar(zetaris.run_sql(f"SELECT COUNT(*) AS n FROM {T['shops']}")),
                                               zetaris.scalar(zetaris.run_sql(f"SELECT COUNT(*) AS n FROM {T['addresses']}")))),
]
sys.exit(0 if all(ok) else 1)
