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
import threading
from contextlib import contextmanager
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
        # Force UTF-8 decoding of text; otherwise psycopg2 falls back to the
        # client's locale encoding (Latin-1/CP1252 on Windows), which turns
        # UTF-8 data like "17β-estradiol" into mojibake ("17Î²-estradiol").
        "client_encoding": "utf-8",
        # 15 s was chosen when every query opened its own connection, and it is what made a
        # degraded RDS produce a 47 s response: 14 sequential connects that were slow but never
        # slow enough to trip the cap. Pooling removes 13 of those 14, so the cap now bounds
        # roughly one connect per request and can be tightened. A successful connect measured
        # 4.0 s at the worst point of an observed RDS slowdown, so 10 s still clears it.
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 20,
        "keepalives_interval": 10,
        "keepalives_count": 6,
        # search_path baked into the connection instead of a per-query
        # `SET search_path TO reticle, public`. That SET was the FIRST statement of every
        # query, so it cost a full round-trip each time — 14 of them on one /api/gene_wiki.
        # NO SPACE after the comma: libpq splits the options string on unescaped spaces, so
        # "reticle, public" would be read as a second option " public" and the connect fails.
        "options": "-c search_path=reticle,public",
    }
    if USE_PG
    else None
)

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------
# Every query used to open its own connection. Measured against the live RDS instance that is
# ~41 ms of TCP+TLS+auth per query from inside AWS, which is 82% of the wall clock for a request
# like /api/gene_wiki (14 queries -> 14 connects -> ~0.57 s of the 0.75 s response).
#
# Sizing. max_connections on the instance is 81 and roughly 9 backends are in use by other
# clients. The ECS service runs a single task (inferred from concurrency: 4 simultaneous
# /api/gene_wiki requests return as a 4-step staircase, implying ~1.3 effective workers).
# The four routes in routers/llm_aaron.py already dispatch through starlette's
# run_in_threadpool, whose anyio limiter defaults to 40 — so TODAY, without a pool, up to 40
# threads can each hold their own connection. maxconn=16 therefore LOWERS the ceiling rather
# than raising it: worst case 16 + 9 = 25, comfortably under 81.
#
# Note that getconn RAISES PoolError("connection pool exhausted") at maxconn rather than
# blocking, so a burst past 16 surfaces as a 500 rather than as queueing. That is the correct
# trade at this size — the alternative is an unbounded queue in front of a 1 GiB database — but
# it is the number to raise first if the threadpool limiter is ever widened.
#
_POOL_WARM = int(os.getenv("RETICLE_PG_POOL_WARM", "1"))
_POOL_MAX = int(os.getenv("RETICLE_PG_POOL_MAX", "16"))

_pg_pool: Any = None
_pg_pool_lock = threading.Lock()


def _get_pool() -> Any:
    """Process-wide pool, built on first use.

    Lazy, never at import: tests run with AWS_DB_HOST unset and must not open a socket, and
    config.py loads AWS secrets into the environment *after* this module is imported.
    """
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:  # re-check under the lock
                from psycopg2.pool import ThreadedConnectionPool

                assert _PG_PARAMS is not None
                pool = ThreadedConnectionPool(_POOL_WARM, _POOL_MAX, **_PG_PARAMS)
                # psycopg2 overloads `minconn` with two unrelated jobs: how many connections to
                # open eagerly in __init__, and the size the idle list is allowed to reach before
                # _putconn starts CLOSING returned connections instead of keeping them. We want
                # those decoupled — open as few as possible up front (a large eager batch is just
                # more ways for the first request to fail while RDS is refusing connections), but
                # then retain everything the load actually needed. Raising minconn after
                # construction does exactly that: __init__ has already run, and minconn is read
                # nowhere else except that retention check.
                # Without this the pool silently degrades to connect-per-query above the warm
                # size — measured: 12 concurrent threads caused 57 fresh connects, one of which
                # timed out, which is the failure this whole change exists to remove.
                pool.minconn = _POOL_MAX
                _pg_pool = pool
    return _pg_pool

# Path to local SQLite — only relevant when USE_PG is False.
_SQLITE_PATH = Path(__file__).resolve().parents[2] / "prototype" / "data" / "reticle.db"


@contextmanager
def _checkout() -> Any:
    """Hand out a pooled connection and guarantee it goes back exactly once.

    The return lives in `finally`, not in `except psycopg2.Error`. Building the result rows
    happens after the query has already succeeded, so a failure there is not a psycopg2 error at
    all — but it would still leak a pool slot permanently if the return were tied to the except
    clause. Over a long-lived process that leak is fatal: the pool empties and every later
    request gets a PoolError.

    autocommit is set on checkout because psycopg2 otherwise opens an implicit transaction on
    the first statement. With connect-per-query that was invisible (closing the socket aborted
    it); pooled, it would hand back an `idle in transaction` backend, which pins the xmin
    horizon and blocks vacuum across the whole database.
    """
    import psycopg2

    pool = _get_pool()
    con = pool.getconn()
    broken = False
    try:
        con.autocommit = True
        yield con
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True  # the socket itself is suspect — do not put it back in the pool
        raise
    finally:
        pool.putconn(con, close=broken)


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

        stmt = sql.replace("?", "%s")
        for attempt in (0, 1):
            try:
                with _checkout() as con:
                    with con.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(stmt, params)
                        return [_Row(r) for r in cur.fetchall()]
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                # A pooled connection that RDS closed while it sat idle fails on first USE, not
                # on checkout — the pool has no way to know before handing it over. _checkout
                # has already discarded it, so one retry lands on a fresh one.
                # Only connection-level errors are retried: a ProgrammingError or DataError is
                # the query's own fault and would fail identically the second time.
                if attempt:
                    raise

    con = sqlite3.connect(str(_SQLITE_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
        return [_Row(dict(r)) for r in rows]
    finally:
        con.close()


def db_execute(sql: str, params: tuple = ()) -> None:
    """Run a write (INSERT/UPDATE/DDL) against the configured backend and commit.

    Same `?`-placeholder convention as db_fetchall. Callers that must not fail on
    a write (e.g. best-effort caching) should wrap this in try/except.
    """
    if USE_PG:
        import psycopg2

        stmt = sql.replace("?", "%s")
        for attempt in (0, 1):
            try:
                with _checkout() as con:
                    with con.cursor() as cur:
                        # No explicit commit: _checkout sets autocommit, so the statement is
                        # already durable when execute() returns. All three callers
                        # (external_sources.py) are single idempotent statements, so there is
                        # no multi-statement transaction to preserve.
                        cur.execute(stmt, params)
                return
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                if attempt:
                    raise

    con = sqlite3.connect(str(_SQLITE_PATH))
    try:
        con.execute(sql, params)
        con.commit()
    finally:
        con.close()


