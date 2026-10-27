"""Zetaris data layer. run_sql() is the only way agents touch data."""
import csv
import glob
import os
import sqlite3
import threading
import uuid

import requests

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sample")
_sample_db = None
_lock = threading.Lock()  # one shared sqlite connection, hops run in threads


def _sample_conn() -> sqlite3.Connection:
    """SAMPLE_MODE only: load the sample CSV inputs into in-memory SQLite (inputs, never answers)."""
    global _sample_db
    if _sample_db is None:
        _sample_db = sqlite3.connect(":memory:", check_same_thread=False)
        for path in glob.glob(os.path.join(SAMPLE_DIR, "*.csv")):
            table = os.path.splitext(os.path.basename(path))[0]
            with open(path, newline="") as f:
                rows = list(csv.reader(f))
            cols = rows[0]
            _sample_db.execute(f'CREATE TABLE "{table}" ({",".join(cols)})')
            _sample_db.executemany(
                f'INSERT INTO "{table}" VALUES ({",".join("?" * len(cols))})', rows[1:]
            )
            # CSV values are text; cast numeric-looking ones so SUM() works like it does in Zetaris
            for c in cols:
                _sample_db.execute(
                    f'UPDATE "{table}" SET {c}=CAST({c} AS REAL) '
                    f'WHERE {c} GLOB "[0-9]*.[0-9]*" AND {c} NOT GLOB "*[^0-9.]*"'
                )
    return _sample_db


def run_sql(sql: str, limit: int = 1000) -> list:
    """Send one SQL statement to Zetaris and return its rows. Raises on any failure."""
    if os.getenv("SAMPLE_MODE", "false").lower() == "true":
        with _lock:
            cur = _sample_conn().execute(sql)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchmany(limit)]
    response = requests.post(
        os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
        headers={
            "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"],
            "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
            "X-Request-ID": str(uuid.uuid4()),
        },
        json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def scalar(rows: list) -> float:
    """First value of the first row as a float. Handles dict rows and list rows."""
    if not rows:
        raise ValueError("query returned no rows")
    first = rows[0]
    value = next(iter(first.values())) if isinstance(first, dict) else first[0]
    return 0.0 if value is None else float(value)
