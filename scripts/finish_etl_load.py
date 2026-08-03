#!/usr/bin/env python3
"""
finish_etl_load.py — Finish / repair a split-pipeline ETL load whose aggregate
stage did not complete.

Failure this repairs (observed on version 7 / run 4):
  Pairs were loaded into screen_gene_raw, but the run died before
  build_fact_screen_gene / build_dim_screen / build_dim_gene ran — so
  fact_screen_gene and dim_* have NO rows for the version, and
  etl_pipeline_run is stuck 'running'. It also normalizes gene.organism, which
  the loader hardcoded (e.g. 'mus_musculus' even for human data).

What it does, server-side (no bulk data movement — the 26M pairs stay put):
  1. Preflight: log row counts; abort if screen_gene_raw is empty for the version.
  2. Normalize screen.organism / gene.organism to data_load_version.organism.
  3. Run the aggregate build functions for (run_id, version_id).
  4. Mark the run 'completed' and the version 'valid' + current.
  5. Verify: log final fact/dim row counts.

Idempotent and re-runnable: the build_* functions upsert (ON CONFLICT DO UPDATE),
and the organism/completion updates are safe to repeat. Run it as many times as
you need.

Usage (from the scripts/ directory, or via slurm/reticle-etl-finish.sh):
  python3 finish_etl_load.py --version 7
  python3 finish_etl_load.py --version 7 --run-id 4
  python3 finish_etl_load.py --version 7 --dry-run     # log SQL + counts, change nothing

Every SQL statement and row count is logged to the console AND to
  $LOG_DIR/etl-finish-v<version>-run<run>.log
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import psycopg2

from config import Config

logger = logging.getLogger("finish_etl_load")

# fact_screen_gene is built in screen_id batches (build_fact_batched) because the
# monolithic build_fact_screen_gene over tens of millions of screen_gene_raw rows
# exceeds the job wall-clock (observed: 4h SLURM TIMEOUT on version 7 / 26.2M rows).
# The dimension builds emit few rows (one per screen / per gene) and stay whole.
# screen_gene_raw is already populated by the load phase, so build_screen_gene_raw
# is intentionally NOT called here.
DIM_STEPS = ['build_dim_screen', 'build_dim_gene']
VERSION_TABLES = ['screen', 'gene', 'screen_gene_raw',
                  'fact_screen_gene', 'dim_screen', 'dim_gene']


def setup_logging(version_id: int, run_id) -> Path:
    log_dir = Path(os.getenv('LOG_DIR', 'logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"etl-finish-v{version_id}-run{run_id}.log"
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return log_file


class ETLFinisher:
    def __init__(self, version_id: int, run_id=None, dry_run: bool = False,
                 fact_batch_size: int = 50):
        self.version_id = version_id
        self.run_id = run_id
        self.dry_run = dry_run
        self.fact_batch_size = fact_batch_size
        self.conn = None
        self.organism = None

    # -- helpers -----------------------------------------------------------
    def _log_sql(self, label: str, sql: str, params=None):
        flat = ' '.join(sql.split())
        suffix = f"  params={params}" if params is not None else ""
        logger.info(f"[SQL] {label}: {flat}{suffix}")

    def _count(self, table: str) -> int:
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE version_id = %s", (self.version_id,))
        return cur.fetchone()[0]

    def _exec(self, label: str, sql: str, params=None, commit: bool = True):
        self._log_sql(label, sql, params)
        if self.dry_run:
            logger.info("  (dry-run: not executed)")
            return 0
        cur = self.conn.cursor()
        t0 = time.time()
        cur.execute(sql, params)
        rc = cur.rowcount
        if commit:
            self.conn.commit()
        logger.info(f"  -> rows affected={rc}  ({time.time() - t0:.1f}s)")
        return rc

    # -- lifecycle ---------------------------------------------------------
    def connect(self):
        params = Config.get_psycopg2_params()
        params['sslmode'] = 'require'
        self.conn = psycopg2.connect(**params)
        self.conn.autocommit = False
        # Disable the per-statement timeout: build_fact_screen_gene GROUP BYs over
        # tens of millions of screen_gene_raw rows and must not be cut off.
        cur = self.conn.cursor()
        cur.execute("SET statement_timeout = 0")     # aggregate builds run long; don't cap
        cur.execute("SET work_mem = '256MB'")        # speed up the GROUP BY sorts/hashes
        cur.execute("SET maintenance_work_mem = '512MB'")
        self.conn.commit()
        logger.info("Connected (statement_timeout=0, work_mem=256MB, maintenance_work_mem=512MB)")

    def resolve(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id = %s", (self.version_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"version_id {self.version_id} not found in data_load_version")
        self.organism = row[0]

        if self.run_id is None:
            cur.execute("SELECT MAX(run_id) FROM etl_pipeline_run WHERE data_load_version_id = %s",
                        (self.version_id,))
            self.run_id = cur.fetchone()[0]
            if self.run_id is None:
                raise SystemExit(f"No etl_pipeline_run exists for version {self.version_id}")
        logger.info(f"Resolved: version_id={self.version_id}  organism={self.organism}  run_id={self.run_id}")

    def preflight(self):
        logger.info("=== PREFLIGHT ROW COUNTS (version %s) ===" % self.version_id)
        counts = {t: self._count(t) for t in VERSION_TABLES}
        for t in VERSION_TABLES:
            logger.info(f"  {t:<18} = {counts[t]:>12,}")
        if counts['screen_gene_raw'] == 0:
            raise SystemExit(
                "ABORT: screen_gene_raw is EMPTY for this version. Run the load "
                "(split phase 2) first — there is nothing to aggregate.")
        return counts

    def fix_organism(self):
        logger.info("=== NORMALIZE ORGANISM -> '%s' ===" % self.organism)
        for table in ('screen', 'gene'):
            self._exec(
                f"normalize {table}.organism",
                f"UPDATE {table} SET organism = %s "
                f"WHERE version_id = %s AND organism IS DISTINCT FROM %s",
                (self.organism, self.version_id, self.organism),
            )

    # SELECT body of build_fact_screen_gene, but filtered to a batch of screen_ids
    # and committed per batch so the build makes incremental, resumable progress.
    FACT_BATCH_SQL = """
        INSERT INTO fact_screen_gene
            (version_id, run_id, screen_id, gene_id, hit_count, hit_percentage,
             avg_raw_score, total_publications, condition_count, is_current)
        SELECT %s, %s, sgr.screen_id, sgr.gene_id,
               COUNT(CASE WHEN sgr.hit_flag THEN 1 END)::INT AS hit_count,
               ROUND(100.0 * COUNT(CASE WHEN sgr.hit_flag THEN 1 END)
                     / NULLIF(COUNT(*), 0), 2)::NUMERIC AS hit_percentage,
               AVG(sgr.raw_score)::NUMERIC AS avg_raw_score,
               0, 1, TRUE
        FROM screen_gene_raw sgr
        WHERE sgr.version_id = %s AND sgr.screen_id = ANY(%s)
        GROUP BY sgr.screen_id, sgr.gene_id
        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
            hit_count = EXCLUDED.hit_count,
            hit_percentage = EXCLUDED.hit_percentage,
            avg_raw_score = EXCLUDED.avg_raw_score,
            is_current = TRUE
    """

    def build_fact_batched(self):
        """Build fact_screen_gene in screen_id batches.

        The monolithic build_fact_screen_gene aggregates + inserts ~26M rows in one
        statement and exceeded the job wall-clock. Here each batch of screens is a
        small INSERT that commits on its own, so progress survives a restart. Screens
        already present in fact_screen_gene for this version are skipped (resume).
        """
        cur = self.conn.cursor()
        cur.execute("SELECT screen_id FROM screen WHERE version_id = %s ORDER BY screen_id",
                    (self.version_id,))
        all_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT screen_id FROM fact_screen_gene WHERE version_id = %s",
                    (self.version_id,))
        done = {r[0] for r in cur.fetchall()}
        todo = [sid for sid in all_ids if sid not in done]
        logger.info(f"build_fact (batched): {len(all_ids)} screens, {len(done)} already done, "
                    f"{len(todo)} to process, batch_size={self.fact_batch_size}")
        self._log_sql("build_fact batch template", self.FACT_BATCH_SQL,
                      "(version, run, version, <screen_id batch>)")
        if self.dry_run:
            logger.info("  (dry-run: not executed)")
            return
        if not todo:
            logger.info("  fact already complete for all screens — nothing to do")
            return

        total = 0
        n_batches = (len(todo) + self.fact_batch_size - 1) // self.fact_batch_size
        for i in range(0, len(todo), self.fact_batch_size):
            batch = todo[i:i + self.fact_batch_size]
            t0 = time.time()
            cur.execute(self.FACT_BATCH_SQL,
                        (self.version_id, self.run_id, self.version_id, batch))
            self.conn.commit()
            total += cur.rowcount
            logger.info(f"  fact batch {i // self.fact_batch_size + 1}/{n_batches}: "
                        f"screens[{batch[0]}..{batch[-1]}] +{cur.rowcount:,} rows "
                        f"(cumulative {total:,}, {time.time() - t0:.1f}s)")
        logger.info(f"✓ build_fact (batched): {total:,} fact rows for version {self.version_id}")

    def build_aggregates(self):
        logger.info("=== BUILD AGGREGATES (run_id=%s, version_id=%s) ===" % (self.run_id, self.version_id))
        self.build_fact_batched()
        for fn in DIM_STEPS:
            self._log_sql(fn, f"SELECT {fn}(%s, %s)", (self.run_id, self.version_id))
            if self.dry_run:
                logger.info("  (dry-run: not executed)")
                continue
            cur = self.conn.cursor()
            t0 = time.time()
            cur.execute(f"SELECT {fn}(%s, %s)", (self.run_id, self.version_id))
            cur.fetchone()
            self.conn.commit()
            logger.info(f"  -> {fn} completed ({time.time() - t0:.1f}s)")

    def mark_complete(self):
        logger.info("=== MARK RUN COMPLETE / VERSION CURRENT ===")
        num_screens = self._count('screen')
        num_genes = self._count('gene')
        num_gene_hits = self._count('screen_gene_raw')

        # Demote other runs/versions for the same organism, promote this one.
        self._exec(
            "demote other runs (same organism)",
            "UPDATE etl_pipeline_run SET is_current = FALSE "
            "WHERE is_current = TRUE AND data_load_version_id IN "
            "(SELECT version_id FROM data_load_version WHERE organism = %s AND version_id <> %s)",
            (self.organism, self.version_id),
        )
        self._exec(
            "demote other versions (same organism)",
            "UPDATE data_load_version SET is_current = FALSE "
            "WHERE organism = %s AND version_id <> %s AND is_current = TRUE",
            (self.organism, self.version_id),
        )
        self._exec(
            "mark run completed",
            "UPDATE etl_pipeline_run SET status = 'completed', is_current = TRUE, "
            "completed_at = CURRENT_TIMESTAMP, "
            "total_duration_seconds = COALESCE(total_duration_seconds, "
            "  EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at))) "
            "WHERE run_id = %s",
            (self.run_id,),
        )
        self._exec(
            "mark version valid + current",
            "UPDATE data_load_version SET status = 'valid', is_current = TRUE, "
            "num_screens = %s, num_genes = %s, num_gene_hits = %s WHERE version_id = %s",
            (num_screens, num_genes, num_gene_hits, self.version_id),
        )

    def verify(self):
        logger.info("=== FINAL ROW COUNTS (version %s) ===" % self.version_id)
        ok = True
        for t in VERSION_TABLES:
            n = self._count(t)
            logger.info(f"  {t:<18} = {n:>12,}")
            if t in ('fact_screen_gene', 'dim_screen', 'dim_gene') and n == 0 and not self.dry_run:
                logger.error(f"  !! {t} is still EMPTY for version {self.version_id}")
                ok = False
        return ok

    def run(self) -> bool:
        self.connect()
        try:
            self.resolve()
            self.preflight()
            self.fix_organism()
            self.build_aggregates()
            self.mark_complete()
            ok = self.verify()
            if self.dry_run:
                logger.info("DRY-RUN complete — no changes were made.")
                return True
            if ok:
                logger.info("✓ ETL finish completed successfully.")
            else:
                logger.error("✗ ETL finish ran but some aggregate tables are still empty.")
            return ok
        except Exception as e:
            self.conn.rollback()
            logger.error(f"ETL finish failed: {e}", exc_info=True)
            return False
        finally:
            self.conn.close()
            logger.info("Database connection closed")


def main():
    parser = argparse.ArgumentParser(description="Finish/repair a stalled split-pipeline ETL load")
    parser.add_argument('--version', type=int, required=True, help='Data load version ID')
    parser.add_argument('--run-id', type=int, default=None,
                        help='ETL run ID (default: latest run for the version)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Log SQL + counts but make no changes')
    parser.add_argument('--fact-batch-size', type=int, default=50,
                        help='Screens per fact_screen_gene batch (default: 50)')
    parser.add_argument('--log-level', default='INFO', help='Logging level')
    args = parser.parse_args()

    log_file = setup_logging(args.version, args.run_id if args.run_id is not None else 'latest')
    logger.setLevel(getattr(logging, args.log_level.upper(), logging.INFO))
    logger.info(f"Log file: {log_file}")
    logger.info(f"Args: version={args.version} run_id={args.run_id} dry_run={args.dry_run}")

    finisher = ETLFinisher(args.version, run_id=args.run_id, dry_run=args.dry_run,
                           fact_batch_size=args.fact_batch_size)
    sys.exit(0 if finisher.run() else 1)


if __name__ == '__main__':
    main()
