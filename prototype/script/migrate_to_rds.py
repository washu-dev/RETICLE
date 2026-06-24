"""
RETICLE — migrate the local SQLite harmonized DB into the team's AWS RDS (PostgreSQL).
=====================================================================================
Loads the prototype's tables into a DEDICATED schema `reticle` so they are fully
isolated from the team's warehouse (the `public.*` tables). This script ONLY
creates / drops tables inside the `reticle` schema — it never touches anyone
else's tables.

Tables loaded (introspected from SQLite, so columns always match):
  screen_metadata           (~2,157 rows)
  screen_metadata_curated   (~2,157 rows)
  harmonized_scores         (~28.2 M rows)   <- the big one, streamed via COPY

Runtime metrics are captured throughout (load time, throughput, index build time,
post-index query latency, final sizes) and written to:
  processed_data/rds_migration_metrics.json   (machine-readable)
  documentation/rds_runtime_metrics.md        (report for the team)

  python3 script/migrate_to_rds.py            # all three + indexes + benchmark
  python3 script/migrate_to_rds.py --meta-only   # just the two small tables (quick test)
"""

import argparse
import io
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
import psycopg2

SCHEMA = "reticle"
SMALL = ["screen_metadata", "screen_metadata_curated"]
BIG = ["harmonized_scores"]
CHUNK = 250_000
BENCH_GENES = ["TP53", "KRAS", "EGFR", "BRCA1", "MYC"]
METRICS_PATH = paths.PROCESSED_DATA / "rds_migration_metrics.json"
REPORT_PATH = Path(__file__).resolve().parent.parent / "documentation" / "rds_runtime_metrics.md"

# keepalives: keep the TCP connection alive through the long COPY / index build so a
# NAT/firewall idle-timeout can't drop it mid-operation (the SSL-EOF we hit before).
KEEPALIVE = dict(connect_timeout=15, keepalives=1, keepalives_idle=20,
                 keepalives_interval=10, keepalives_count=6)

_PG = {"INTEGER": "integer", "INT": "integer", "BIGINT": "bigint",
       "REAL": "double precision", "FLOAT": "double precision",
       "NUMERIC": "numeric", "TEXT": "text"}


def load_env():
    cfg = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def pg_type(t):
    return _PG.get((t or "TEXT").upper().split("(")[0], "text")


def _esc(v):
    if v is None:
        return r"\N"
    return (str(v).replace("\\", "\\\\").replace("\t", " ")
            .replace("\n", " ").replace("\r", " "))


def migrate_table(slite, pg, cur, table, metrics):
    info = slite.execute(f"PRAGMA table_info({table})").fetchall()  # cid,name,type,notnull,dflt,pk
    cols = [(c[1].lower(), pg_type(c[2])) for c in info]
    src_cols = [c[1] for c in info]
    coldef = ", ".join(f'"{n}" {ty}' for n, ty in cols)
    n = slite.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table}")          # only our own schema
    cur.execute(f"CREATE TABLE {SCHEMA}.{table} ({coldef})")
    pg.commit()
    print(f"[{table}] created ({len(cols)} cols); loading {n:,} rows...", flush=True)

    collist = ",".join(f'"{c}"' for c, _ in cols)
    copy_sql = f"COPY {SCHEMA}.{table} ({collist}) FROM STDIN"
    sc = slite.execute(f"SELECT {','.join(src_cols)} FROM {table}")
    total = 0
    t0 = time.time()
    while True:
        rows = sc.fetchmany(CHUNK)
        if not rows:
            break
        buf = io.StringIO()
        for r in rows:
            buf.write("\t".join(_esc(v) for v in r) + "\n")
        buf.seek(0)
        cur.copy_expert(copy_sql, buf)
        total += len(rows)
        print(f"   ... {total:,}/{n:,}", flush=True)
    pg.commit()
    elapsed = time.time() - t0

    cur.execute(f"SELECT pg_total_relation_size('{SCHEMA}.{table}')")
    size_mb = cur.fetchone()[0] / 1e6
    rps = int(total / elapsed) if elapsed else 0
    mbps = size_mb / elapsed if elapsed else 0
    metrics["tables"][table] = {"rows": total, "seconds": round(elapsed, 1),
                                "rows_per_sec": rps, "size_mb": round(size_mb, 1),
                                "mb_per_sec": round(mbps, 2)}
    print(f"[{table}] done: {total:,} rows in {elapsed:.1f}s  "
          f"({rps:,} rows/s, {mbps:.1f} MB/s, {size_mb:.0f} MB)", flush=True)


def build_index(pg, cur, name, table, col, metrics):
    print(f"building index {name} on {table}({col}) ...", flush=True)
    t0 = time.time()
    cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {SCHEMA}.{table} ({col})")
    pg.commit()
    el = time.time() - t0
    metrics["indexes"][name] = {"target": f"{table}({col})", "seconds": round(el, 1)}
    print(f"  {name}: {el:.1f}s", flush=True)


def benchmark(cur, metrics):
    print("query-latency benchmark (post-index, WHERE gene_symbol = ?) ...", flush=True)
    res = {}
    for g in BENCH_GENES:
        times, nrows = [], 0
        for _ in range(3):
            t0 = time.time()
            cur.execute(f"SELECT * FROM {SCHEMA}.harmonized_scores WHERE gene_symbol = %s", (g,))
            nrows = len(cur.fetchall())
            times.append((time.time() - t0) * 1000)
        res[g] = {"rows": nrows, "first_ms": round(times[0], 1), "warm_ms": round(min(times[1:]), 1)}
        print(f"  {g}: {nrows:,} rows  first {times[0]:.0f}ms  warm {min(times[1:]):.0f}ms", flush=True)
    metrics["query_benchmark"] = res


def env_info(cur):
    cur.execute("SELECT version()")
    info = {"version": cur.fetchone()[0].split(" on ")[0]}
    for s in ["shared_buffers", "work_mem", "maintenance_work_mem",
              "effective_cache_size", "max_connections"]:
        cur.execute("SELECT current_setting(%s)", (s,))
        info[s] = cur.fetchone()[0]
    return info


def write_report(m):
    L = ["# RETICLE → AWS RDS — migration runtime metrics", ""]
    L.append(f"- **Run (UTC):** {m['started']} → {m.get('finished', '?')}")
    L.append(f"- **Total wall time:** {m.get('total_seconds', 0):.0f}s")
    L.append(f"- **DB size after load:** {m.get('db_size_after', '?')}")
    e = m.get("env", {})
    L.append(f"- **Server:** {e.get('version', '?')}")
    L.append(f"- **Tuning:** shared_buffers={e.get('shared_buffers')}, "
             f"maintenance_work_mem={e.get('maintenance_work_mem')}, "
             f"effective_cache_size={e.get('effective_cache_size')}")
    L += ["", "## Table load", "",
          "| table | rows | size | load time | throughput |",
          "|---|---:|---:|---:|---:|"]
    for t, d in m["tables"].items():
        L.append(f"| `{t}` | {d['rows']:,} | {d['size_mb']:.0f} MB | {d['seconds']:.0f}s | "
                 f"{d['rows_per_sec']:,} rows/s · {d['mb_per_sec']:.1f} MB/s |")
    if m.get("indexes"):
        L += ["", "## Index build", "", "| index | target | build time |", "|---|---|---:|"]
        for name, d in m["indexes"].items():
            L.append(f"| `{name}` | `{d['target']}` | {d['seconds']:.0f}s |")
    if m.get("query_benchmark"):
        L += ["", "## Query latency — `WHERE gene_symbol = ?` (post-index)", "",
              "| gene | rows | first query | warm |", "|---|---:|---:|---:|"]
        for g, d in m["query_benchmark"].items():
            L.append(f"| {g} | {d['rows']:,} | {d['first_ms']:.0f} ms | {d['warm_ms']:.0f} ms |")
    L += ["", "_Infra-level metrics (CPU, IOPS, FreeStorageSpace) live in CloudWatch and "
          "need team-account access; the above is captured from the DB connection._", ""]
    REPORT_PATH.write_text("\n".join(L))
    METRICS_PATH.write_text(json.dumps(m, indent=2))
    print(f"\nmetrics -> {REPORT_PATH}\n         {METRICS_PATH}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-only", action="store_true", help="只灌两张小表(快速验证)")
    args = ap.parse_args()

    cfg = load_env()
    slite = sqlite3.connect(str(paths.DB))
    pg = psycopg2.connect(host=cfg["AWS_DB_HOST"], port=cfg["AWS_DB_PORT"],
                          user=cfg["AWS_DB_USER"], password=cfg["AWS_DB_PASSWORD"],
                          dbname=cfg["AWS_DB_NAME"], **KEEPALIVE)
    cur = pg.cursor()
    # Protect the shared instance: cap temp-sort size + statement runtime so an index
    # build that overruns fails CLEANLY (clean error) instead of filling the disk and
    # taking the DB down. (Learned the hard way — the unbounded build dropped the
    # connection / DiskFull'd twice before this.)
    cur.execute("SET statement_timeout = '1800s'")
    cur.execute("SET temp_file_limit = '4GB'")
    pg.commit()

    metrics = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "tables": {}, "indexes": {}}
    metrics["env"] = env_info(cur)
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    pg.commit()

    overall0 = time.time()
    tables = SMALL if args.meta_only else SMALL + BIG
    for t in tables:
        migrate_table(slite, pg, cur, t, metrics)

    if not args.meta_only:
        build_index(pg, cur, "idx_hs_gene", "harmonized_scores", "gene_symbol", metrics)
        build_index(pg, cur, "idx_hs_screen", "harmonized_scores", "screen_id", metrics)
        build_index(pg, cur, "idx_smc", "screen_metadata_curated", "screen_id", metrics)
        benchmark(cur, metrics)

    metrics["total_seconds"] = round(time.time() - overall0, 1)
    cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
    metrics["db_size_after"] = cur.fetchone()[0]
    metrics["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pg.close()
    slite.close()
    write_report(metrics)
    print("ALL DONE.", flush=True)


if __name__ == "__main__":
    main()
