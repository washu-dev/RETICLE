"""
Database access layer for RETICLE FastAPI.

Mirrors the dual-backend pattern in prototype/web/app.py:
  - AWS_DB_HOST set in environment → Postgres (schema `reticle` on AWS RDS)
  - AWS_DB_HOST absent → local SQLite fallback

Usage (from a service module):
    from services.db_service import db_fetchall

    rows = db_fetchall(
        "SELECT * FROM harmonized_scores WHERE gene_symbol = ?",
        ("TP53",),
    )

Placeholders: always use `?` — translated to `%s` for Postgres automatically.
Column access: rows support both exact-case and lowercase key access.
"""

import os
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables from .env file (if present)
load_dotenv()

_AWS_HOST = os.getenv("AWS_DB_HOST", "")
USE_PG = bool(_AWS_HOST)

_PG_PARAMS = (
    {
        "host": _AWS_HOST,
        "port": os.getenv("AWS_DB_PORT", "5432"),
        "user": os.getenv("AWS_DB_USER"),
        "password": os.getenv("AWS_DB_PASSWORD"),
        "dbname": os.getenv("AWS_DB_NAME"),
        "connect_timeout": 15,
        "keepalives": 1,
        "keepalives_idle": 20,
        "keepalives_interval": 10,
        "keepalives_count": 6,
    }
    if USE_PG
    else None
)

# Path to local SQLite — only relevant when USE_PG is False.
_SQLITE_PATH = Path(__file__).resolve().parents[2] / "prototype" / "data" / "reticle.db"


class _Row(dict):
    """Dict row with case-insensitive key access (Postgres returns lowercase column
    names; SQLite column names may be mixed-case from the CREATE TABLE statement)."""

    def __getitem__(self, k: str) -> Any:
        try:
            return dict.__getitem__(self, k)
        except KeyError:
            return dict.__getitem__(self, k.lower())


def db_fetchall(sql: str, params: tuple = ()) -> list[_Row]:
    """Run a SELECT against the configured backend.

    Parameters
    ----------
    sql:
        SQL query using `?` as the placeholder character (works for both backends).
    params:
        Positional parameters to bind.

    Returns
    -------
    List of _Row dicts — supports both exact-case and lowercase key access.
    """
    if USE_PG:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        assert _PG_PARAMS is not None
        con = psycopg2.connect(**_PG_PARAMS)
        try:
            cur = con.cursor(cursor_factory=RealDictCursor)
            cur.execute("SET search_path TO reticle, public")
            cur.execute(sql.replace("?", "%s"), params)
            return [_Row(r) for r in cur.fetchall()]
        finally:
            con.close()

    con = sqlite3.connect(str(_SQLITE_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
        return [_Row(dict(r)) for r in rows]
    finally:
        con.close()


