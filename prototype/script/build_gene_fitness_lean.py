"""
build_gene_fitness_lean.py — precompute the per-gene fitness "lean" served by the network viewer.
=================================================================================================
The network viewer colours each node by whether knocking the gene out is, on average, costly
(essential), neutral (mixed), or advantageous across FITNESS screens. That colour comes from one
number per gene: the mean PERCENTILE_SCORE over every fitness screen the gene was measured in.

Originally web/app.py computed this at request time by aggregating harmonized_scores (28M rows).
Even with a correct index-scan plan and a MATERIALIZED CTE it pulls ~24k rows out of the big table,
and once the RDS buffer cache goes cold that measured 92s (EXPLAIN: 22,423 block reads, 83.6s of
shared-read I/O — the plan was optimal, the disk was the wall). It is a FIXED aggregate over FIXED
data, so it belongs in a tiny lookup table, not in the hot path. This script materialises it:

  reticle.gene_fitness_lean(gene_symbol, organism, mean_percentile, n_screens)

one row per (gene, organism), for Homo sapiens and Mus musculus. web/app.py::_net_fitness_lean reads
it with a single indexed lookup (92s -> 0.06s), and falls back to the live aggregate only on sqlite
(no such table locally, and the local file makes the aggregate cheap anyway).

Re-run this whenever harmonized_scores or the fitness-domain tagging changes. Values are verified
bit-for-bit identical to the live aggregate it replaces.

  /opt/anaconda3/bin/python3 script/build_gene_fitness_lean.py
"""
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
import app  # noqa: E402  — reuse the app's RDS credentials


def rds_params():
    """RDS connection params, independent of whether the APP is currently pointed at RDS.

    app._PG_PARAMS is None whenever AWS_DB_HOST is commented out in .env (i.e. the app is running in
    local-sqlite mode) — but this is a BUILD script whose whole job is to write to RDS, so it reads
    the credentials directly rather than inheriting the app's serving mode."""
    if app._PG_PARAMS:
        return dict(app._PG_PARAMS)
    raw = {}
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            raw[k.strip()] = v.strip()
    missing = [k for k in ("AWS_DB_HOST", "AWS_DB_USER", "AWS_DB_PASSWORD", "AWS_DB_NAME") if not raw.get(k)]
    if missing:
        raise SystemExit(f"missing RDS credentials in .env: {', '.join(missing)}")
    return dict(host=raw["AWS_DB_HOST"], port=raw.get("AWS_DB_PORT", "5432"),
                user=raw["AWS_DB_USER"], password=raw["AWS_DB_PASSWORD"],
                dbname=raw["AWS_DB_NAME"], connect_timeout=15,
                options="-c search_path=reticle,public")


def main():
    con = psycopg2.connect(**rds_params())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("SET search_path TO reticle, public")

    cur.execute("DROP TABLE IF EXISTS reticle.gene_fitness_lean")
    cur.execute("""CREATE TABLE reticle.gene_fitness_lean (
        gene_symbol     TEXT,
        organism        TEXT,
        mean_percentile DOUBLE PRECISION,
        n_screens       INTEGER)""")

    t0 = time.time()
    # One aggregate over the whole table: each gene's mean percentile in FITNESS screens, by species.
    # The fitness gate (assay_domain='fitness') is the same one the app's node colouring assumes, so
    # the precomputed value matches _net_fitness_lean's old live query exactly.
    cur.execute("""INSERT INTO reticle.gene_fitness_lean (gene_symbol, organism, mean_percentile, n_screens)
        SELECT h.gene_symbol, sm.organism_official, AVG(h.percentile_score), COUNT(*)
        FROM harmonized_scores h
        JOIN screen_metadata_curated c ON c.screen_id = h.screen_id
        JOIN screen_metadata sm         ON sm.screen_id = h.screen_id
        WHERE c.assay_domain = 'fitness'
          AND h.percentile_score IS NOT NULL
          AND sm.organism_official IN ('Homo sapiens', 'Mus musculus')
        GROUP BY h.gene_symbol, sm.organism_official""")
    n = cur.rowcount

    cur.execute("CREATE INDEX ix_gfl ON reticle.gene_fitness_lean (organism, gene_symbol)")
    cur.execute("ANALYZE reticle.gene_fitness_lean")
    print(f"gene_fitness_lean: {n:,} rows ({time.time()-t0:.1f}s incl. index)", flush=True)

    cur.execute("SELECT organism, COUNT(*) FROM reticle.gene_fitness_lean GROUP BY organism ORDER BY organism")
    for org, c in cur.fetchall():
        print(f"   {org}: {c:,} genes", flush=True)
    con.close()


if __name__ == "__main__":
    main()
