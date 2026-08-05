"""
migrate_gene_search.py — put the search box's type-ahead index on RDS.
======================================================================
build_gene_search.py writes gene_search into the local kb.db. The cloud reads the same table
through db_fetchall, so without this the box works locally and silently offers nothing in the
deployed app — which is the failure mode gene_wiki_aaron.get_gene_suggest() is written to absorb
(it logs once and returns an empty list rather than 500ing under the cursor). Absorbing it is not
the same as fixing it.

366,611 rows: one per canonical symbol plus one per alias that does not collide with a real symbol,
for human and mouse. Small enough to load in one pass.

THE INDEX IS THE WHOLE POINT. Every keystroke runs `term LIKE 'PO%'` filtered by taxid, so
(taxid, term) is the access path and a sequential scan of 366k rows per character is not a thing
a search box can afford. Postgres will use a plain btree for a LEFT-anchored LIKE only when the
column's collation is C — otherwise it needs text_pattern_ops, so that is what is created here.
Getting this wrong does not break the feature, it just quietly makes it slow, which is worse.

Only ever creates/drops inside the `reticle` schema — never public.*.

  /opt/anaconda3/bin/python3 script/migrate_gene_search.py
"""
import argparse
import io
import sqlite3
import time

import psycopg2

import paths
from build_gene_fitness_lean import rds_params

SCHEMA = "reticle"
TABLE = "gene_search"
SRC = paths.PROCESSED_DATA / "kb.db"


def esc(v):
    if v is None:
        return r"\N"
    return str(v).replace("\\", r"\\").replace("\t", r"\t").replace("\n", r"\n").replace("\r", r"\r")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(SRC))
    args = ap.parse_args()

    lite = sqlite3.connect(args.db)
    cols = [(r[1], (r[2] or "").upper()) for r in lite.execute(f'PRAGMA table_info("{TABLE}")')]
    if not cols:
        raise SystemExit(f"{args.db} has no {TABLE} — run script/build_gene_search.py first")
    n_src = lite.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]

    pgtype = {"INTEGER": "BIGINT", "REAL": "DOUBLE PRECISION", "TEXT": "TEXT", "": "TEXT"}
    coldef = ", ".join(f'"{c}" {pgtype.get(t, "TEXT")}' for c, t in cols)
    collist = ", ".join(f'"{c}"' for c, _ in cols)

    con = psycopg2.connect(**rds_params())
    con.autocommit = True
    cur = con.cursor()
    t0 = time.time()
    cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{TABLE}")        # only our own schema
    cur.execute(f"CREATE TABLE {SCHEMA}.{TABLE} ({coldef})")

    buf, sent = io.StringIO(), 0
    for row in lite.execute(f"SELECT {collist} FROM {TABLE}"):
        buf.write("\t".join(esc(v) for v in row) + "\n")
        if buf.tell() > 32_000_000:
            buf.seek(0)
            cur.copy_expert(f"COPY {SCHEMA}.{TABLE} ({collist}) FROM STDIN", buf)
            sent += 1
            buf = io.StringIO()
    if buf.tell():
        buf.seek(0)
        cur.copy_expert(f"COPY {SCHEMA}.{TABLE} ({collist}) FROM STDIN", buf)
    lite.close()

    # text_pattern_ops so a left-anchored LIKE can use the index under any collation; see the
    # module docstring. taxid leads because every query filters species first.
    cur.execute(f"CREATE INDEX ix_gs_term ON {SCHEMA}.{TABLE} (taxid, term text_pattern_ops)")
    cur.execute(f"ANALYZE {SCHEMA}.{TABLE}")
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{TABLE}")
    n_dst = cur.fetchone()[0]
    print(f"  {TABLE:16s} {n_dst:>9,} rows  {time.time()-t0:>6.1f}s  "
          f"{'OK' if n_dst == n_src else f'MISMATCH (local {n_src:,})'}", flush=True)
    if n_dst != n_src:
        raise SystemExit(f"row-count mismatch: local {n_src} vs rds {n_dst}")

    # Prove the index is actually used, rather than assuming it. A seq scan here is the silent
    # failure this script exists to avoid.
    cur.execute(
        f"EXPLAIN SELECT symbol FROM {SCHEMA}.{TABLE} "
        f"WHERE taxid = 9606 AND term LIKE 'PO%' LIMIT 40")
    plan = " ".join(r[0] for r in cur.fetchall())
    print(f"  plan: {'INDEX' if 'Index' in plan else 'SEQ SCAN — the LIKE is not using ix_gs_term'}",
          flush=True)
    con.close()


if __name__ == "__main__":
    main()
