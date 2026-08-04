"""
migrate_net_to_rds.py — sync the co-essentiality network tables to RDS.
=======================================================================
The network is built locally into reticle_net.db / reticle_net_mouse.db by compute_coessential.py and
explore_mouse_coessential.py, but web/app.py reads it from RDS whenever AWS_DB_HOST is set
(net_fetchall -> reticle.net_edge / reticle.net_edge_mouse). Until this script existed there was NO
committed path for that sync — the RDS copies had been loaded out of band, so rebuilding the network
locally silently left the cloud serving a stale graph.

Table name mapping (matches web/app.py::_net_edge_table and ::_cohit_table):
  local reticle_net.db        net_edge            ->  reticle.net_edge
  local reticle_net_mouse.db  net_edge            ->  reticle.net_edge_mouse   (mouse is suffixed on
                                                      RDS because both species share one schema
                                                      there, while locally they live in separate
                                                      files under one name)
  local reticle_net.db        net_screen          ->  reticle.net_screen
  local reticle_net.db        hit_only_connection ->  reticle.hit_only_connection
  local reticle_net_mouse.db  hit_only_connection ->  reticle.hit_only_connection_mouse

The two hit_only_connection jobs are newer than the rest: channel 2 was built by compute_hit_only.py
and then sat unread for months, so nothing had ever needed it in the cloud. The evidence-tier feature
reads it, which is what made the gap matter. Until this sync has RUN, the cloud degrades to grading
edges on channel 1 alone — coessential_network_aaron.cohit_among() latches the missing table and
logs once rather than raising, so a stale deployment serves a coarser graph rather than a 500.

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
    # Channel 2. The composite is the one that matters: the only query that reads these tables is
    # cohit_among()'s symmetric `gene_a IN (...) AND gene_b IN (...)`, which a leading-column btree
    # on gene_a serves directly. The single-column pair is kept to mirror the local schema and to
    # keep an ad-hoc "what does this gene co-hit with" lookup on gene_b cheap — the pair is stored in
    # ONE direction only, so gene_b is a genuine second access path, not a duplicate of gene_a.
    # Index names must be unique per SCHEMA in Postgres, hence the distinct mouse prefix.
    (paths.PROCESSED_DATA / "reticle_net.db", "hit_only_connection", "hit_only_connection",
     [("ix_hoc_ab", "gene_a, gene_b"), ("ix_hoc_a", "gene_a"), ("ix_hoc_b", "gene_b")]),
    (paths.PROCESSED_DATA / "reticle_net_mouse.db", "hit_only_connection", "hit_only_connection_mouse",
     [("ix_hocm_ab", "gene_a, gene_b"), ("ix_hocm_a", "gene_a"), ("ix_hocm_b", "gene_b")]),
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
