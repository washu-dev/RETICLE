#!/usr/bin/env python3
"""
CPU-Only ETL Transformation Phase for RETICLE.

Reads deduplicated CSV files from GPU phase and loads directly to production tables.
This is Phase 2 of the split GPU/CPU pipeline.

The GPU phase (gpu_etl_dedup_only.py) produces deduplicated data in CSV files:
  - staging_screen_v{VERSION_ID}.csv (deduplicated screens)
  - staging_screen_gene_v{VERSION_ID}.csv (deduplicated pairs)
  - dedup_metadata_v{VERSION_ID}.json (statistics)

This phase:
  1. Loads screens → production screen table
  2. Loads genes → production gene table (deduplicated)
  3. Loads pairs → production screen_gene_raw table
  4. Builds fact and dimension tables via stored procedures
  5. No staging tables involved (they're in CSV for debugging only)

Performance:
  - Load 500 screens: ~2 seconds
  - Load 6M deduplicated pairs: ~30 seconds
  - Build aggregates: ~20 seconds
  - Total: ~1 minute

Usage:
  python cpu_etl_load_only.py --version 2

Prerequisites:
  - gpu_etl_dedup_only.py must have completed successfully
  - CSV files must exist in ${STAGING_DIR} or /tmp/reticle_staging/
  - Production tables (screen, gene, screen_gene_raw) must exist
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import psycopg2
import psycopg2.extras

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    class tqdm:
        def __init__(self, iterable=None, **kwargs):
            self.iterable = iterable or []
        def __iter__(self):
            return iter(self.iterable)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

from config import Config

logger = logging.getLogger(__name__)

PIPE_DELIMITER = '|'
TEMP_DIR = Config.STAGING_OUTPUT_DIR

# Screens per batch for the pair load and the fact build. Both operate over tens
# of millions of screen_gene_raw rows; batching by screen and committing per batch
# keeps each statement small, makes progress resumable, and avoids the 4h+ wall
# clock that a single monolithic statement hit on the human load (version 7).
SCREEN_BATCH_SIZE = 50


class CPUTransformPhase:
    """CPU-based ETL transformation phase - CSV to production tables."""

    def __init__(self, version_id: int):
        self.version_id = version_id
        self.conn = None
        self.run_id = None
        self.stats = {
            'screens_loaded': 0,
            'genes_loaded': 0,
            'pairs_loaded': 0,
            'aggregates_built': False,
        }

    def run(self) -> bool:
        """Execute CPU transformation phase."""
        logger.info("="*80)
        logger.info("CPU TRANSFORMATION PHASE")
        logger.info("="*80)
        logger.info(f"Version ID: {self.version_id}")
        logger.info("")

        start_time = time.time()

        try:
            # Connect to database
            self.conn = psycopg2.connect(**Config.get_psycopg2_params())
            logger.info("✓ Connected to database")

            # Long, set-based aggregate/join statements must not be capped, and the
            # 26M-row GROUP BYs/joins want more memory than the default.
            cur0 = self.conn.cursor()
            cur0.execute("SET statement_timeout = 0")
            cur0.execute("SET work_mem = '256MB'")
            cur0.execute("SET maintenance_work_mem = '512MB'")
            self.conn.commit()

            # Create run record
            self._create_run_record()

            # Load metadata from GPU phase
            metadata = self._load_metadata()
            if not metadata:
                logger.error("GPU dedup metadata not found. Run gpu_etl_dedup_only.py first.")
                return False

            logger.info(f"  GPU dedup completed: {metadata['timestamp']}")
            logger.info(f"  GPU dedup elapsed: {metadata['elapsed_seconds']:.1f}s")
            logger.info("")

            # Load screens to production table
            if not self._load_screens_csv():
                logger.error("Failed to load screens")
                return False

            # Load genes to production table
            if not self._load_genes_csv():
                logger.error("Failed to load genes")
                return False

            # Load pairs to production table
            if not self._load_pairs_csv():
                logger.error("Failed to load pairs")
                return False

            # Build aggregates (fact and dimension tables)
            if not self._build_aggregates():
                logger.error("Failed to build aggregates")
                return False

            elapsed = time.time() - start_time

            logger.info("\n" + "="*80)
            logger.info("CPU TRANSFORMATION PHASE COMPLETE")
            logger.info("="*80)
            logger.info(f"Elapsed time: {elapsed:.1f}s")
            logger.info(f"Screens loaded: {self.stats['screens_loaded']:,}")
            logger.info(f"Genes loaded: {self.stats['genes_loaded']:,}")
            logger.info(f"Pairs loaded: {self.stats['pairs_loaded']:,}")
            logger.info(f"Aggregates: {'BUILT' if self.stats['aggregates_built'] else 'FAILED'}")
            logger.info("="*80 + "\n")

            # Mark run as completed in database
            self._mark_run_completed(elapsed)

            return True

        except Exception as e:
            logger.error(f"CPU transform phase failed: {e}", exc_info=True)
            if self.conn:
                self._mark_run_failed(str(e))
            return False
        finally:
            if self.conn:
                self.conn.close()
                logger.info("✓ Database connection closed")

    def _create_run_record(self) -> None:
        """Create ETL pipeline run record."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO etl_pipeline_run (
                data_load_version_id, pipeline_version, started_at, status
            ) VALUES (%s, %s, CURRENT_TIMESTAMP, 'running')
            RETURNING run_id
        """, (self.version_id, '2.0-split-gpu-cpu'))
        self.run_id = cursor.fetchone()[0]
        self.conn.commit()
        logger.info(f"✓ Created run record (run_id: {self.run_id})")

        # Initialize progress tracking for resumable pipeline
        self._init_checkpoint()

    def _init_checkpoint(self) -> None:
        """Initialize progress checkpoint for resumable pipeline."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO etl_progress (run_id, stage, rows_processed)
            VALUES (%s, 'screens', 0)
            ON CONFLICT (run_id) DO UPDATE SET stage = 'screens', rows_processed = 0
        """, (self.run_id,))
        self.conn.commit()

    def _get_checkpoint(self, stage: str) -> int:
        """Get last checkpoint for a stage (rows already processed)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT rows_processed FROM etl_progress
            WHERE run_id = %s AND stage = %s
        """, (self.run_id, stage))
        result = cursor.fetchone()
        return result[0] if result else 0

    def _update_checkpoint(self, stage: str, rows_processed: int, error_msg: Optional[str] = None) -> None:
        """Update progress checkpoint for a stage."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO etl_progress (run_id, stage, rows_processed, error_message, last_updated)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (run_id) DO UPDATE SET
                stage = EXCLUDED.stage,
                rows_processed = EXCLUDED.rows_processed,
                error_message = EXCLUDED.error_message,
                last_updated = CURRENT_TIMESTAMP
        """, (self.run_id, stage, rows_processed, error_msg))
        self.conn.commit()

    def _load_metadata(self) -> Optional[dict]:
        """Load deduplication metadata from GPU phase."""
        metadata_file = TEMP_DIR / f'dedup_metadata_v{self.version_id}.json'
        try:
            if not metadata_file.exists():
                logger.error(f"Metadata file not found: {metadata_file}")
                return None

            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            if metadata['version_id'] != self.version_id:
                logger.error(f"Version mismatch: {metadata['version_id']} != {self.version_id}")
                return None

            return metadata

        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
            return None

    def _load_screens_csv(self) -> bool:
        """Load screens from CSV to production screen table with checkpoint resumption."""
        logger.info("Loading screens to production table...")

        csv_file = TEMP_DIR / f'staging_screen_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Screen CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Check for checkpoint (resumable pipeline)
            resume_from = self._get_checkpoint('screens')
            if resume_from > 0:
                logger.info(f"  Resuming from row {resume_from:,} (checkpoint found)")

            # Count rows
            with open(csv_file, 'r', encoding='utf-8') as f:
                total_rows = sum(1 for _ in f)

            logger.info(f"  Total screens: {total_rows:,}")

            # Load screens from CSV
            # CSV format: version_id|screen_id|biogrid_screen_id|organism|annotation_source|moi|notes
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)

                if TQDM_AVAILABLE:
                    pbar = tqdm(total=total_rows, desc='  Loading screens', unit=' rows', ncols=80)

                screens = []
                row_num = 0
                for row in reader:
                    # Skip rows before checkpoint
                    if row_num < resume_from:
                        row_num += 1
                        if TQDM_AVAILABLE:
                            pbar.update(1)
                        continue

                    if len(row) >= 4:  # Need at least version_id, screen_id, biogrid_screen_id, organism
                        version_id = int(row[0])
                        biogrid_screen_id = row[2]
                        organism = row[3]
                        annotation_source = row[4] if len(row) > 4 and row[4] else None

                        screens.append((version_id, biogrid_screen_id, organism, annotation_source, True))

                    if TQDM_AVAILABLE:
                        pbar.update(1)
                    row_num += 1

                if TQDM_AVAILABLE:
                    pbar.close()

            # Batch insert
            for i in range(0, len(screens), 1000):
                batch = screens[i:i + 1000]
                psycopg2.extras.execute_batch(cursor, """
                    INSERT INTO screen (version_id, biogrid_screen_id, organism, annotation_source, is_current)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (version_id, biogrid_screen_id) DO UPDATE SET is_current = TRUE
                """, batch)

            self.conn.commit()
            self.stats['screens_loaded'] = len(screens)
            self._update_checkpoint('screens', row_num)

            logger.info(f"✓ Loaded {len(screens):,} screens to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            self._update_checkpoint('screens', row_num, str(e))
            logger.error(f"Failed to load screens: {e}")
            return False

    def _load_genes_csv(self) -> bool:
        """Load genes from CSV to production gene table (deduplicated) with checkpoint resumption."""
        logger.info("Loading genes to production table...")

        csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Pair CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Check for checkpoint
            resume_from = self._get_checkpoint('genes')
            if resume_from > 0:
                logger.info(f"  Resuming from row {resume_from:,} (checkpoint found)")

            # Read genes from CSV (extract unique genes from pairs)
            # CSV format: version_id|screen_id|biogrid_screen_id|identifier_id|gene_symbol|official_symbol|hit_flag|...
            genes_dict = {}  # identifier_id -> gene_symbol

            logger.info("  Extracting unique genes from pairs...")
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)
                row_num = 0
                for row in reader:
                    # Skip rows before checkpoint
                    if row_num < resume_from:
                        row_num += 1
                        continue

                    if len(row) >= 5:
                        identifier_id = row[3]
                        gene_symbol = row[4]

                        # Store if not seen before
                        if identifier_id not in genes_dict:
                            genes_dict[identifier_id] = gene_symbol

                    row_num += 1

            logger.info(f"  Total unique genes: {len(genes_dict):,}")

            # Organism from the version record (do NOT hardcode — this loader is
            # used for both mus_musculus and homo_sapiens).
            organism = self._get_organism() or 'unknown'
            logger.info(f"  Organism: {organism}")
            genes = [
                (self.version_id, identifier_id, gene_symbol, organism, True)
                for identifier_id, gene_symbol in genes_dict.items()
            ]

            # Batch insert
            for i in range(0, len(genes), 1000):
                batch = genes[i:i + 1000]
                psycopg2.extras.execute_batch(cursor, """
                    INSERT INTO gene (version_id, identifier_id, gene_symbol, organism, is_current)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (version_id, identifier_id) DO UPDATE SET is_current = TRUE
                """, batch)

            self.conn.commit()
            self.stats['genes_loaded'] = len(genes)
            self._update_checkpoint('genes', row_num)

            logger.info(f"✓ Loaded {len(genes):,} genes to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            self._update_checkpoint('genes', row_num, str(e))
            logger.error(f"Failed to load genes: {e}")
            return False

    # CSV column order (from gpu_etl_dedup_only.py):
    #   version_id | src_screen_id | biogrid_screen_id | identifier_id | gene_symbol
    #   | official_symbol | hit_flag | score_1..5 | tsv_filename | tsv_row_number
    PAIRS_INSERT_SQL = """
        INSERT INTO screen_gene_raw
            (version_id, run_id, screen_id, gene_id, biogrid_screen_id, identifier_id,
             hit_flag, score_1, score_2, score_3, score_4, score_5, raw_score, is_current)
        SELECT tp.version_id, %s, s.screen_id, g.gene_id, tp.biogrid_screen_id, tp.identifier_id,
               (lower(coalesce(tp.hit_flag, '')) = 'true'),
               tp.score_1, tp.score_2, tp.score_3, tp.score_4, tp.score_5,
               COALESCE(tp.score_1, 0), TRUE
        FROM tmp_pairs tp
        JOIN screen s ON s.version_id = tp.version_id
                     AND s.biogrid_screen_id = tp.biogrid_screen_id
        JOIN gene   g ON g.version_id = tp.version_id
                     AND g.identifier_id = tp.identifier_id
        WHERE s.screen_id = ANY(%s)
        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
            hit_flag = EXCLUDED.hit_flag, raw_score = EXCLUDED.raw_score, is_current = TRUE
    """

    def _load_pairs_csv(self) -> bool:
        """Load screen-gene pairs into screen_gene_raw.

        Bulk-COPYs the deduped CSV into a temp table, then resolves surrogate keys
        with a set-based INSERT ... SELECT JOIN, batched by screen (commit per
        batch). This replaces a row-by-row execute_batch loop that took 3h+ and was
        killed at the wall-clock. Resumable: screens already present in
        screen_gene_raw for this version are skipped.
        """
        logger.info("Loading screen-gene pairs to production table...")

        csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Pair CSV not found: {csv_file}")
            return False

        try:
            cur = self.conn.cursor()

            # 1. Bulk-load the CSV into a session temp table (no ON COMMIT DROP, so it
            #    survives the per-batch commits; dropped explicitly at the end).
            cur.execute("""
                CREATE TEMP TABLE IF NOT EXISTS tmp_pairs (
                    version_id INT, src_screen_id INT, biogrid_screen_id VARCHAR(100),
                    identifier_id VARCHAR(250), gene_symbol TEXT, official_symbol TEXT,
                    hit_flag TEXT, score_1 NUMERIC, score_2 NUMERIC, score_3 NUMERIC,
                    score_4 NUMERIC, score_5 NUMERIC, tsv_filename TEXT, tsv_row_number INT
                )
            """)
            cur.execute("TRUNCATE tmp_pairs")
            logger.info("  COPYing deduped pairs CSV into temp table...")
            with open(csv_file, 'r', encoding='utf-8') as f:
                cur.copy_expert(
                    "COPY tmp_pairs FROM STDIN WITH (FORMAT text, DELIMITER '|', NULL '')", f)
            cur.execute("SELECT COUNT(*) FROM tmp_pairs")
            staged = cur.fetchone()[0]
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tmp_pairs_bsid ON tmp_pairs (biogrid_screen_id)")
            self.conn.commit()
            logger.info(f"  Staged {staged:,} pairs; resolving surrogate keys in screen batches...")

            # 2. Resume: skip screens already loaded into screen_gene_raw.
            all_screens = self._screen_ids()
            cur.execute("SELECT DISTINCT screen_id FROM screen_gene_raw WHERE version_id = %s",
                        (self.version_id,))
            done = {r[0] for r in cur.fetchall()}
            todo = [s for s in all_screens if s not in done]
            logger.info(f"  {len(all_screens)} screens, {len(done)} already loaded, "
                        f"{len(todo)} to process, batch_size={SCREEN_BATCH_SIZE}")

            total = 0
            n_batches = (len(todo) + SCREEN_BATCH_SIZE - 1) // SCREEN_BATCH_SIZE
            for i in range(0, len(todo), SCREEN_BATCH_SIZE):
                batch = todo[i:i + SCREEN_BATCH_SIZE]
                t0 = time.time()
                cur.execute(self.PAIRS_INSERT_SQL, (self.run_id, batch))
                self.conn.commit()
                total += cur.rowcount
                logger.info(f"  pairs batch {i // SCREEN_BATCH_SIZE + 1}/{n_batches}: "
                            f"+{cur.rowcount:,} rows (cumulative {total:,}, {time.time() - t0:.1f}s)")

            cur.execute("DROP TABLE IF EXISTS tmp_pairs")
            self.conn.commit()

            cur.execute("SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = %s", (self.version_id,))
            self.stats['pairs_loaded'] = cur.fetchone()[0]
            self._update_checkpoint('pairs', self.stats['pairs_loaded'])
            logger.info(f"✓ Loaded {self.stats['pairs_loaded']:,} pairs to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            self._update_checkpoint('pairs', 0, str(e))
            logger.error(f"Failed to load pairs: {e}", exc_info=True)
            return False

    def _get_organism(self):
        cur = self.conn.cursor()
        cur.execute("SELECT organism FROM data_load_version WHERE version_id = %s", (self.version_id,))
        row = cur.fetchone()
        return row[0] if row else None

    def _screen_ids(self):
        cur = self.conn.cursor()
        cur.execute("SELECT screen_id FROM screen WHERE version_id = %s ORDER BY screen_id",
                    (self.version_id,))
        return [r[0] for r in cur.fetchall()]

    # SELECT body of build_fact_screen_gene, filtered to a batch of screen_ids and
    # committed per batch (the monolithic function over 26M rows exceeded the wall
    # clock on version 7).
    FACT_BATCH_SQL = """
        INSERT INTO fact_screen_gene
            (version_id, run_id, screen_id, gene_id, hit_count, hit_percentage,
             avg_raw_score, total_publications, condition_count, is_current)
        SELECT %s, %s, sgr.screen_id, sgr.gene_id,
               COUNT(CASE WHEN sgr.hit_flag THEN 1 END)::INT,
               ROUND(100.0 * COUNT(CASE WHEN sgr.hit_flag THEN 1 END)
                     / NULLIF(COUNT(*), 0), 2)::NUMERIC,
               AVG(sgr.raw_score)::NUMERIC, 0, 1, TRUE
        FROM screen_gene_raw sgr
        WHERE sgr.version_id = %s AND sgr.screen_id = ANY(%s)
        GROUP BY sgr.screen_id, sgr.gene_id
        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
            hit_count = EXCLUDED.hit_count, hit_percentage = EXCLUDED.hit_percentage,
            avg_raw_score = EXCLUDED.avg_raw_score, is_current = TRUE
    """

    def _build_aggregates(self) -> bool:
        """Build fact (batched by screen) and dimension (whole) tables."""
        logger.info("Building fact and dimension tables...")

        try:
            cur = self.conn.cursor()

            # Fact: batched by screen, resumable (skip screens already in fact).
            all_screens = self._screen_ids()
            cur.execute("SELECT DISTINCT screen_id FROM fact_screen_gene WHERE version_id = %s",
                        (self.version_id,))
            done = {r[0] for r in cur.fetchall()}
            todo = [s for s in all_screens if s not in done]
            logger.info(f"  fact: {len(all_screens)} screens, {len(done)} done, {len(todo)} to build")
            n_batches = (len(todo) + SCREEN_BATCH_SIZE - 1) // SCREEN_BATCH_SIZE
            for i in range(0, len(todo), SCREEN_BATCH_SIZE):
                batch = todo[i:i + SCREEN_BATCH_SIZE]
                t0 = time.time()
                cur.execute(self.FACT_BATCH_SQL,
                            (self.version_id, self.run_id, self.version_id, batch))
                self.conn.commit()
                logger.info(f"  fact batch {i // SCREEN_BATCH_SIZE + 1}/{n_batches}: "
                            f"+{cur.rowcount:,} rows ({time.time() - t0:.1f}s)")

            # Dimensions are light (one row per screen / per gene) — call whole.
            for fn in ('build_dim_screen', 'build_dim_gene'):
                logger.info(f"  Running: {fn}...")
                t0 = time.time()
                cur.execute(f"SELECT {fn}(%s, %s)", (self.run_id, self.version_id))
                cur.fetchone()
                self.conn.commit()
                logger.info(f"  -> {fn} ({time.time() - t0:.1f}s)")

            self.stats['aggregates_built'] = True
            self._update_checkpoint('aggregates', 1)
            logger.info("✓ Aggregates built successfully")
            return True

        except Exception as e:
            self.conn.rollback()
            self._update_checkpoint('aggregates', 0, str(e))
            logger.error(f"Failed to build aggregates: {e}", exc_info=True)
            return False

    def _mark_run_failed(self, error_msg: str) -> None:
        """Mark ETL run as failed."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE etl_pipeline_run
                SET status = 'failed', completed_at = CURRENT_TIMESTAMP, error_message = %s
                WHERE run_id = %s
            """, (error_msg, self.run_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark run as failed: {e}")

    def _mark_run_completed(self, elapsed_seconds):
        """Mark ETL run as completed and update version counts."""
        try:
            cursor = self.conn.cursor()

            # Update etl_pipeline_run status
            cursor.execute("""
                UPDATE etl_pipeline_run
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP, total_duration_seconds = %s
                WHERE run_id = %s
            """, (elapsed_seconds, self.run_id))

            # Update data_load_version status and counts
            cursor.execute("""
                SELECT COUNT(*) FROM screen WHERE version_id = %s
            """, (self.version_id,))
            num_screens = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM gene WHERE version_id = %s
            """, (self.version_id,))
            num_genes = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = %s AND run_id = %s
            """, (self.version_id, self.run_id))
            num_gene_hits = cursor.fetchone()[0]

            cursor.execute("""
                UPDATE data_load_version
                SET status = 'valid', num_screens = %s, num_genes = %s, num_gene_hits = %s, is_current = TRUE
                WHERE version_id = %s
            """, (num_screens, num_genes, num_gene_hits, self.version_id))

            self.conn.commit()
            logger.info(f"✓ Marked run as completed (screens: {num_screens:,}, genes: {num_genes:,}, hits: {num_gene_hits:,})")

        except Exception as e:
            logger.error(f"Failed to mark run as completed: {e}")


def main():
    parser = argparse.ArgumentParser(description="CPU Transformation Phase")
    parser.add_argument('--version', type=int, required=True, help='Data load version ID')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    phase = CPUTransformPhase(version_id=args.version)
    success = phase.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
