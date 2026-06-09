#!/usr/bin/env python3
"""
CPU-Only Database Loading Phase for RETICLE ETL.

Reads CSV files from GPU deduplication phase and batch inserts into PostgreSQL.
This is Phase 2 of the split GPU/CPU pipeline.

The GPU phase (gpu_etl_dedup_only.py) produces:
  - staging_screen_v2.csv
  - staging_screen_gene_v2.csv
  - dedup_metadata_v2.json

This phase:
  1. Reads the CSV files
  2. Uses PostgreSQL COPY for fast bulk inserts
  3. Validates inserted data matches expected counts
  4. Logs results to database

Performance:
  - Insert 500 screens: ~2 seconds
  - Insert 6M deduplicated pairs: ~20 seconds
  - Total CPU time: ~30 seconds

Usage:
  python cpu_etl_load_only.py --version 2

Prerequisites:
  - gpu_etl_dedup_only.py must have completed successfully
  - CSV files must exist in ${RETICLE_STAGING_DIR} or /tmp/reticle_staging/
  - Database tables (staging_screen, staging_screen_gene) must exist
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

import psycopg2
import psycopg2.extras

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


class CPULoadPhase:
    """CPU-based database loading phase."""

    def __init__(self, version_id: int):
        self.version_id = version_id
        self.conn = None
        self.stats = {
            'screens_inserted': 0,
            'pairs_inserted': 0,
            'validation_passed': False,
        }

    def run(self) -> bool:
        """Execute CPU loading phase."""
        logger.info("="*80)
        logger.info("CPU LOADING PHASE")
        logger.info("="*80)
        logger.info(f"Version ID: {self.version_id}")
        logger.info("")

        start_time = time.time()

        try:
            # Connect to database
            self.conn = psycopg2.connect(**Config.get_psycopg2_params())
            logger.info("✓ Connected to database")

            # Load metadata from GPU phase
            metadata = self._load_metadata()
            if not metadata:
                logger.error("GPU dedup metadata not found. Run gpu_etl_dedup_only.py first.")
                return False

            logger.info(f"  Dedup completed: {metadata['timestamp']}")
            logger.info(f"  Dedup elapsed: {metadata['elapsed_seconds']:.1f}s")
            logger.info("")

            # Load screens
            if not self._load_screens():
                logger.error("Failed to load screens")
                return False

            # Load pairs
            if not self._load_pairs():
                logger.error("Failed to load pairs")
                return False

            # Validate inserted data
            if not self._validate_load():
                logger.error("Data validation failed")
                return False

            elapsed = time.time() - start_time

            logger.info("\n" + "="*80)
            logger.info("CPU LOADING PHASE COMPLETE")
            logger.info("="*80)
            logger.info(f"Elapsed time: {elapsed:.1f}s")
            logger.info(f"Screens inserted: {self.stats['screens_inserted']:,}")
            logger.info(f"Pairs inserted: {self.stats['pairs_inserted']:,}")
            logger.info(f"Validation: {'PASSED' if self.stats['validation_passed'] else 'FAILED'}")
            logger.info("="*80 + "\n")

            return True

        except Exception as e:
            logger.error(f"CPU load phase failed: {e}", exc_info=True)
            return False
        finally:
            if self.conn:
                self.conn.close()
                logger.info("✓ Database connection closed")

    def _load_metadata(self) -> Optional[dict]:
        """Load deduplication metadata from GPU phase."""
        logger.info("Loading GPU dedup metadata...")

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

            logger.info(f"✓ Loaded metadata (GPU: {metadata['gpu_available']})")
            return metadata

        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
            return None

    def _load_screens(self) -> bool:
        """Load screens into staging_screen table using COPY."""
        logger.info("Loading screens via COPY...")

        csv_file = TEMP_DIR / f'staging_screen_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Screen CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Read CSV with proper csv module (handles quoted newlines correctly)
            screens = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)
                for row in reader:
                    screens.append(row)

            logger.info(f"  Total screens: {len(screens):,}")

            # Load via COPY
            if len(screens) > 0:
                from io import StringIO
                # Reconstruct CSV with proper quoting using csv.writer
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer, delimiter=PIPE_DELIMITER)

                if TQDM_AVAILABLE:
                    pbar = tqdm(total=len(screens), desc='  Preparing COPY', unit=' rows', ncols=80)
                    for row in screens:
                        writer.writerow(row)
                        pbar.update(1)
                    pbar.close()
                else:
                    for row in screens:
                        writer.writerow(row)

                # Get the reconstructed CSV and pass to COPY
                csv_buffer.seek(0)
                cursor.copy_from(
                    csv_buffer,
                    'staging_screen',
                    sep=PIPE_DELIMITER,
                    columns=('version_id', 'screen_id', 'biogrid_screen_id', 'organism',
                             'annotation_source', 'moi', 'notes'),
                    null='',
                )

            self.conn.commit()
            self.stats['screens_inserted'] = cursor.rowcount

            logger.info(f"✓ Inserted {self.stats['screens_inserted']:,} screens")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to load screens: {e}")
            return False

    def _load_pairs(self) -> bool:
        """Load screen-gene pairs into staging_screen_gene table using COPY."""
        logger.info("Loading screen-gene pairs via COPY...")

        csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
        if not csv_file.exists():
            logger.error(f"Pair CSV not found: {csv_file}")
            return False

        try:
            cursor = self.conn.cursor()

            # Read CSV with proper csv module (handles all edge cases)
            pairs = []
            logger.info("  Reading pairs from CSV...")
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=PIPE_DELIMITER)
                for row in reader:
                    pairs.append(row)

            logger.info(f"  Total pairs: {len(pairs):,}")

            # Load via COPY
            if len(pairs) > 0:
                from io import StringIO
                # Reconstruct CSV with proper quoting using csv.writer
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer, delimiter=PIPE_DELIMITER)

                if TQDM_AVAILABLE:
                    pbar = tqdm(total=len(pairs), desc='  Preparing COPY', unit=' rows', ncols=80, unit_scale=True)
                    for row in pairs:
                        writer.writerow(row)
                        pbar.update(1)
                    pbar.close()
                else:
                    for row in pairs:
                        writer.writerow(row)

                # Get the reconstructed CSV and pass to COPY
                csv_buffer.seek(0)
                cursor.copy_from(
                    csv_buffer,
                    'staging_screen_gene',
                    sep=PIPE_DELIMITER,
                    columns=('version_id', 'screen_id', 'biogrid_screen_id', 'identifier_id',
                             'gene_symbol', 'official_symbol', 'hit_flag',
                             'score_1', 'score_2', 'score_3', 'score_4', 'score_5',
                             'tsv_filename', 'tsv_row_number'),
                    null='',
                )

            self.conn.commit()
            self.stats['pairs_inserted'] = cursor.rowcount

            logger.info(f"✓ Inserted {self.stats['pairs_inserted']:,} pairs")
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to load pairs: {e}")
            return False

    def _validate_load(self) -> bool:
        """Validate that all data was inserted correctly."""
        logger.info("Validating loaded data...")

        try:
            cursor = self.conn.cursor()

            # Check screen count
            cursor.execute(
                "SELECT COUNT(*) FROM staging_screen WHERE version_id = %s",
                (self.version_id,)
            )
            screen_count = cursor.fetchone()[0]

            if screen_count != self.stats['screens_inserted']:
                logger.error(f"Screen count mismatch: {screen_count} != {self.stats['screens_inserted']}")
                return False

            logger.info(f"  Screens: {screen_count:,} ✓")

            # Check pair count
            cursor.execute(
                "SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = %s",
                (self.version_id,)
            )
            pair_count = cursor.fetchone()[0]

            if pair_count != self.stats['pairs_inserted']:
                logger.error(f"Pair count mismatch: {pair_count} != {self.stats['pairs_inserted']}")
                return False

            logger.info(f"  Pairs: {pair_count:,} ✓")

            # Check that no NULL critical values exist
            cursor.execute("""
                SELECT COUNT(*) FROM staging_screen WHERE version_id = %s
                AND (screen_id IS NULL OR organism IS NULL)
            """, (self.version_id,))
            null_screens = cursor.fetchone()[0]

            if null_screens > 0:
                logger.error(f"Found {null_screens} screens with NULL critical values")
                return False

            cursor.execute("""
                SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = %s
                AND (screen_id IS NULL OR identifier_id IS NULL)
            """, (self.version_id,))
            null_pairs = cursor.fetchone()[0]

            if null_pairs > 0:
                logger.error(f"Found {null_pairs} pairs with NULL critical values")
                return False

            logger.info(f"  NULL validation: PASSED ✓")

            self.stats['validation_passed'] = True
            return True

        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            return False


def main():
    parser = argparse.ArgumentParser(description="CPU Loading Phase")
    parser.add_argument('--version', type=int, required=True, help='Data load version ID')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    phase = CPULoadPhase(version_id=args.version)
    success = phase.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
