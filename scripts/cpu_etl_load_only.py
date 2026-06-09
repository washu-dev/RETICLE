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
  - CSV files must exist in ${RETICLE_STAGING_DIR} or /tmp/reticle_staging/
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
        """Load screens from CSV to production screen table."""
        logger.info("Loading screens to production table...")

        csv_file = TEMP_DIR / f'staging_screen_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Screen CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

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
                for row in reader:
                    if len(row) >= 4:  # Need at least version_id, screen_id, biogrid_screen_id, organism
                        version_id = int(row[0])
                        biogrid_screen_id = row[2]
                        organism = row[3]
                        annotation_source = row[4] if len(row) > 4 and row[4] else None

                        screens.append((version_id, biogrid_screen_id, organism, annotation_source, True))

                        if TQDM_AVAILABLE:
                            pbar.update(1)

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

            logger.info(f"✓ Loaded {len(screens):,} screens to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to load screens: {e}")
            return False

    def _load_genes_csv(self) -> bool:
        """Load genes from CSV to production gene table (deduplicated)."""
        logger.info("Loading genes to production table...")

        csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Pair CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Read genes from CSV (extract unique genes from pairs)
            # CSV format: version_id|screen_id|biogrid_screen_id|identifier_id|gene_symbol|official_symbol|hit_flag|...
            genes_dict = {}  # identifier_id -> (gene_symbol, organism)

            logger.info("  Extracting unique genes from pairs...")
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)
                for row in reader:
                    if len(row) >= 5:
                        identifier_id = row[3]
                        gene_symbol = row[4]

                        # Store if not seen before
                        if identifier_id not in genes_dict:
                            genes_dict[identifier_id] = gene_symbol

            logger.info(f"  Total unique genes: {len(genes_dict):,}")

            # Prepare gene data (assume organism is mus_musculus for now)
            genes = [
                (self.version_id, identifier_id, gene_symbol, 'mus_musculus', True)
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

            logger.info(f"✓ Loaded {len(genes):,} genes to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to load genes: {e}")
            return False

    def _load_pairs_csv(self) -> bool:
        """Load screen-gene pairs from CSV to production screen_gene_raw table."""
        logger.info("Loading screen-gene pairs to production table...")

        csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Pair CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Count rows
            with open(csv_file, 'r', encoding='utf-8') as f:
                total_rows = sum(1 for _ in f)

            logger.info(f"  Total pairs: {total_rows:,}")

            # Read pairs from CSV and insert
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)

                if TQDM_AVAILABLE:
                    pbar = tqdm(total=total_rows, desc='  Loading pairs', unit=' rows', ncols=80, unit_scale=True)

                pairs_batch = []
                for row in reader:
                    if len(row) >= 13:  # Full row needed
                        version_id = int(row[0])
                        biogrid_screen_id = row[2]
                        identifier_id = row[3]
                        hit_flag = row[6].lower() == 'true' if row[6] else False
                        score_1 = float(row[7]) if row[7] else None

                        # Look up screen_id and gene_id
                        cursor.execute("""
                            SELECT s.screen_id, g.gene_id
                            FROM screen s, gene g
                            WHERE s.version_id = %s AND s.biogrid_screen_id = %s
                            AND g.version_id = %s AND g.identifier_id = %s
                        """, (version_id, biogrid_screen_id, version_id, identifier_id))

                        result = cursor.fetchone()
                        if result:
                            screen_id, gene_id = result
                            pairs_batch.append((
                                version_id, self.run_id, screen_id, gene_id,
                                biogrid_screen_id, identifier_id,
                                hit_flag, score_1, score_1, True
                            ))

                            # Batch insert every 5000 rows
                            if len(pairs_batch) >= 5000:
                                psycopg2.extras.execute_batch(cursor, """
                                    INSERT INTO screen_gene_raw
                                    (version_id, run_id, screen_id, gene_id, biogrid_screen_id, identifier_id,
                                     hit_flag, score_1, raw_score, is_current)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
                                        hit_flag = EXCLUDED.hit_flag, is_current = TRUE
                                """, pairs_batch)
                                self.conn.commit()
                                pairs_batch = []

                        if TQDM_AVAILABLE:
                            pbar.update(1)

                # Insert remaining
                if pairs_batch:
                    psycopg2.extras.execute_batch(cursor, """
                        INSERT INTO screen_gene_raw
                        (version_id, run_id, screen_id, gene_id, biogrid_screen_id, identifier_id,
                         hit_flag, score_1, raw_score, is_current)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
                            hit_flag = EXCLUDED.hit_flag, is_current = TRUE
                    """, pairs_batch)

                if TQDM_AVAILABLE:
                    pbar.close()

            self.conn.commit()

            # Count inserted rows
            cursor.execute("SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = %s AND run_id = %s",
                          (self.version_id, self.run_id))
            pair_count = cursor.fetchone()[0]
            self.stats['pairs_loaded'] = pair_count

            logger.info(f"✓ Loaded {pair_count:,} pairs to production table")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to load pairs: {e}")
            return False

    def _build_aggregates(self) -> bool:
        """Build fact and dimension tables via stored procedures."""
        logger.info("Building fact and dimension tables...")

        try:
            cursor = self.conn.cursor()

            # Call stored procedures to build aggregates
            steps = [
                'build_fact_screen_gene',
                'build_dim_screen',
                'build_dim_gene',
            ]

            for step_name in steps:
                logger.info(f"  Running: {step_name}...")
                cursor.execute(f"SELECT {step_name}(%s, %s)", (self.run_id, self.version_id))
                cursor.fetchone()

            self.conn.commit()
            self.stats['aggregates_built'] = True

            logger.info("✓ Aggregates built successfully")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to build aggregates: {e}")
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


def main():
    parser = argparse.ArgumentParser(description="CPU Transformation Phase")
    parser.add_argument('--version', type=int, required=True, help='Data load version ID')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    phase = CPUTransformPhase(version_id=args.version)
    success = phase.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
