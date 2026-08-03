"""
migrate_net_to_rds.py — sync the co-essentiality network tables to RDS.
=======================================================================
The network is built locally into reticle_net.db / reticle_net_mouse.db by compute_coessential.py and
explore_mouse_coessential.py, but web/app.py reads it from RDS whenever AWS_DB_HOST is set
(net_fetchall -> reticle.net_edge / reticle.net_edge_mouse). Until this script existed there was NO
committed path for that sync — the RDS copies had been loaded out of band, so rebuilding the network
locally silently left the cloud serving a stale graph.

Table name mapping (matches web/app.py::_net_edge_table):
  local reticle_net.db        net_edge  ->  reticle.net_edge
  local reticle_net_mouse.db  net_edge  ->  reticle.net_edge_mouse   (mouse is suffixed on RDS
                                            because both species share one schema there, while
                                            locally they live in separate files under one name)
  local reticle_net.db        net_screen -> reticle.net_screen

Only ever creates/drops inside the `reticle` schema — never public.*.

  /opt/anaconda3/bin/python3 script/migrate_net_to_rds.py
  /opt/anaconda3/bin/python3 script/migrate_net_to_rds.py --human-only
"""
import argparse
import io
import sqlite3
import time

import psycopg2

import paths
from build_gene_fitness_lean import rds_params

SCHEMA = "reticle"

# (local db file, local table, rds table, index columns)
JOBS = [
    (paths.PROCESSED_DATA / "reticle_net.db", "net_edge", "net_edge",
     [("ix_ne_a", "gene_a"), ("ix_ne_b", "gene_b"), ("ix_ne_ctx", "context")]),
    (paths.PROCESSED_DATA / "reticle_net.db", "net_screen", "net_screen",
     [("ix_nscr_dom", "assay_domain")]),
    (paths.PROCESSED_DATA / "reticle_net_mouse.db", "net_edge", "net_edge_mouse",
     [("ix_nem_a", "gene_a"), ("ix_nem_b", "gene_b"), ("ix_nem_ctx", "context")]),
]

# sqlite declared type -> postgres type
PGTYPE = {"INTEGER": "BIGINT", "REAL": "DOUBLE PRECISION", "TEXT": "TEXT", "": "TEXT"}


def esc(v):
    if v is None:
        return r"\N"
    return str(v).replace("\\", r"\\").replace("\t", r"\t").replace("\n", r"\n").replace("\r", r"\r")


def sync(cur, sqlite_path, local_table, rds_table, indexes):
    if not sqlite_path.exists():
        print(f"  SKIP {rds_table}: {sqlite_path.name} not found")
        return
    lite = sqlite3.connect(sqlite_path)
    cols = [(r[1], (r[2] or "").upper()) for r in
            lite.execute(f'PRAGMA table_info("{local_table}")')]
    if not cols:
        print(f"  SKIP {rds_table}: {sqlite_path.name} has no table {local_table}")
        lite.close()
        return
    n_src = lite.execute(f'SELECT COUNT(*) FROM "{local_table}"').fetchone()[0]

    coldef = ", ".join(f'"{c}" {PGTYPE.get(t, "TEXT")}' for c, t in cols)
    collist = ", ".join(f'"{c}"' for c, _ in cols)
    cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{rds_table}")       # only our own schema
    cur.execute(f"CREATE TABLE {SCHEMA}.{rds_table} ({coldef})")

    t0 = time.time()
    buf, sent = io.StringIO(), 0
    for row in lite.execute(f'SELECT {collist} FROM "{local_table}"'):
        buf.write("\t".join(esc(v) for v in row) + "\n")
        if buf.tell() > 32_000_000:
            buf.seek(0)
            cur.copy_expert(f"COPY {SCHEMA}.{rds_table} ({collist}) FROM STDIN", buf)
            sent += 1
            buf = io.StringIO()
    if buf.tell():
        buf.seek(0)
        cur.copy_expert(f"COPY {SCHEMA}.{rds_table} ({collist}) FROM STDIN", buf)
    lite.close()

    for name, col in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {SCHEMA}.{rds_table} ({col})")
    cur.execute(f"ANALYZE {SCHEMA}.{rds_table}")
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{rds_table}")
    n_dst = cur.fetchone()[0]
    flag = "OK" if n_dst == n_src else f"MISMATCH (local {n_src:,})"
    print(f"  {rds_table:16s} {n_dst:>9,} rows  {time.time()-t0:>6.1f}s  {flag}")
    if n_dst != n_src:
        raise SystemExit(f"row-count mismatch on {rds_table}: local {n_src} vs rds {n_dst}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--human-only", action="store_true")
    args = ap.parse_args()

    con = psycopg2.connect(**rds_params())
    con.autocommit = True
    cur = con.cursor()
    cur.execute(f"SET search_path TO {SCHEMA}, public")
    cur.execute("SET statement_timeout = '1800s'")
    cur.execute("SET temp_file_limit = '4GB'")

    print(f"syncing network tables -> RDS schema {SCHEMA}")
    for sqlite_path, local_table, rds_table, indexes in JOBS:
        if args.human_only and rds_table.endswith("_mouse"):
            continue
        sync(cur, sqlite_path, local_table, rds_table, indexes)
    con.close()
    print("ALL DONE.")


if __name__ == "__main__":
    main()
