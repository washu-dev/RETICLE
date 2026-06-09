#!/usr/bin/env python3
"""
GPU-Only Deduplication Phase for RETICLE ETL.

Fast GPU-accelerated deduplication of genes and screen-gene pairs.
Output: CSV files for CPU phase (cpu_etl_load_only.py)

Performance:
  - Dedup 1.9M genes: ~10 seconds on GPU A100
  - Dedup 1.9M pairs: ~8 seconds on GPU A100
  - Total GPU time: ~30 seconds (vs 5+ minutes on CPU)

Usage:
  python gpu_etl_dedup_only.py --version 2

Output files (in ${STAGING_DIR} or /tmp/reticle_staging/):
  - staging_screen_v2.csv         (screens for loading)
  - staging_screen_gene_v2.csv    (deduplicated pairs for loading)
  - dedup_metadata_v2.json        (statistics)
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
import pandas as pd
from config import Config

try:
    import cudf
    import cupy as cp
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False
    pd.DataFrame = pd.DataFrame  # Fallback to CPU pandas

logger = logging.getLogger(__name__)

PIPE_DELIMITER = '|'
TEMP_DIR = Config.STAGING_OUTPUT_DIR


class GPUDedupPhase:
    """GPU-accelerated deduplication phase."""

    def __init__(self, version_id: int):
        self.version_id = version_id
        self.conn = None
        self.stats = {
            'screens_loaded': 0,
            'raw_genes': 0,
            'dedup_genes': 0,
            'raw_pairs': 0,
            'dedup_pairs': 0,
            'genes_removed': 0,
            'pairs_removed': 0,
        }
        TEMP_DIR.mkdir(exist_ok=True)

    def run(self) -> bool:
        """Execute GPU deduplication phase."""
        logger.info("="*80)
        logger.info("GPU DEDUPLICATION PHASE")
        logger.info("="*80)
        logger.info(f"Version ID: {self.version_id}")
        logger.info(f"GPU Available: {GPU_AVAILABLE}")
        logger.info("")

        start_time = time.time()

        try:
            # Connect to database
            self.conn = psycopg2.connect(**Config.get_psycopg2_params())
            logger.info("✓ Connected to database")

            # Load screens from database
            if not self._load_screens():
                logger.error("Failed to load screens")
                return False

            # Load genes with GPU dedup
            if not self._load_genes_gpu():
                logger.error("Failed to load genes")
                return False

            # Load pairs with GPU dedup
            if not self._load_pairs_gpu():
                logger.error("Failed to load pairs")
                return False

            elapsed = time.time() - start_time

            # Save metadata
            self._save_metadata(elapsed)

            logger.info("\n" + "="*80)
            logger.info("GPU DEDUP PHASE COMPLETE")
            logger.info("="*80)
            logger.info(f"Elapsed time: {elapsed:.1f}s")
            logger.info(f"Screens: {self.stats['screens_loaded']:,}")
            logger.info(f"Genes: {self.stats['raw_genes']:,} → {self.stats['dedup_genes']:,} "
                       f"({self.stats['genes_removed']:,} removed)")
            logger.info(f"Pairs: {self.stats['raw_pairs']:,} → {self.stats['dedup_pairs']:,} "
                       f"({self.stats['pairs_removed']:,} removed)")
            logger.info("="*80)
            logger.info(f"Next step: Run cpu_etl_load_only.py --version {self.version_id}")
            logger.info("="*80 + "\n")

            return True

        except Exception as e:
            logger.error(f"GPU dedup phase failed: {e}", exc_info=True)
            return False
        finally:
            if self.conn:
                self.conn.close()
                logger.info("✓ Database connection closed")

    def _load_screens(self) -> bool:
        """Load screen metadata from staging_screen table."""
        logger.info("Loading screens...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT version_id, screen_id, biogrid_screen_id, organism,
                       annotation_source, moi, notes
                FROM staging_screen
                WHERE version_id = %s
                ORDER BY screen_id
            """, (self.version_id,))

            screens = cursor.fetchall()
            self.stats['screens_loaded'] = len(screens)

            # Write screens to CSV (quote only non-numeric fields for safety)
            csv_file = TEMP_DIR / f'staging_screen_v{self.version_id}.csv'
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=PIPE_DELIMITER, quoting=csv.QUOTE_NONNUMERIC)
                for screen in screens:
                    writer.writerow(screen)

            logger.info(f"✓ Loaded {len(screens):,} screens")
            return True

        except Exception as e:
            logger.error(f"Failed to load screens: {e}")
            return False

    def _load_genes_gpu(self) -> bool:
        """Load and deduplicate genes using GPU."""
        logger.info("Loading genes (GPU-accelerated dedup)...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT identifier_id
                FROM staging_screen_gene
                WHERE version_id = %s
                ORDER BY identifier_id
            """, (self.version_id,))

            genes = cursor.fetchall()
            self.stats['raw_genes'] = len(genes)

            if len(genes) == 0:
                logger.warning("No genes to deduplicate")
                return True

            # Convert to DataFrame for GPU processing
            if GPU_AVAILABLE:
                logger.info(f"  GPU: Deduplicating {len(genes):,} genes...")
                df = cudf.DataFrame({'identifier_id': [g[0] for g in genes]})
                dedup_df = df.drop_duplicates()
                dedup_genes = dedup_df['identifier_id'].to_pandas().tolist()
            else:
                logger.info(f"  CPU: Deduplicating {len(genes):,} genes...")
                df = pd.DataFrame({'identifier_id': [g[0] for g in genes]})
                dedup_df = df.drop_duplicates()
                dedup_genes = dedup_df['identifier_id'].tolist()

            self.stats['dedup_genes'] = len(dedup_genes)
            self.stats['genes_removed'] = len(genes) - len(dedup_genes)

            logger.info(f"  Removed {self.stats['genes_removed']:,} duplicates")

            return True

        except Exception as e:
            logger.error(f"Failed to load genes: {e}", exc_info=True)
            return False

    def _load_pairs_gpu(self) -> bool:
        """Load and deduplicate screen-gene pairs using GPU."""
        logger.info("Loading screen-gene pairs (GPU-accelerated dedup)...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT version_id, screen_id, biogrid_screen_id, identifier_id,
                       gene_symbol, official_symbol, hit_flag,
                       score_1, score_2, score_3, score_4, score_5,
                       tsv_filename, tsv_row_number
                FROM staging_screen_gene
                WHERE version_id = %s
                ORDER BY screen_id, identifier_id
            """, (self.version_id,))

            pairs = cursor.fetchall()
            self.stats['raw_pairs'] = len(pairs)

            logger.info(f"  Total pairs: {len(pairs):,}")

            if len(pairs) == 0:
                logger.warning("No pairs to deduplicate")
                return True

            # Convert to DataFrame for deduplication
            if GPU_AVAILABLE:
                logger.info("  GPU: Deduplicating pairs...")
                df = cudf.DataFrame({
                    'screen_id': [p[1] for p in pairs],
                    'identifier_id': [p[3] for p in pairs],
                })
                # Deduplicate on (screen_id, identifier_id)
                dedup_df = df.drop_duplicates(subset=['screen_id', 'identifier_id'])
                dedup_indices = dedup_df.index.to_pandas().tolist()
            else:
                logger.info("  CPU: Deduplicating pairs...")
                df = pd.DataFrame({
                    'screen_id': [p[1] for p in pairs],
                    'identifier_id': [p[3] for p in pairs],
                })
                dedup_df = df.drop_duplicates(subset=['screen_id', 'identifier_id'])
                dedup_indices = dedup_df.index.tolist()

            dedup_pairs = [pairs[i] for i in dedup_indices]
            self.stats['dedup_pairs'] = len(dedup_pairs)
            self.stats['pairs_removed'] = len(pairs) - len(dedup_pairs)

            logger.info(f"  After dedup: {len(dedup_pairs):,} unique pairs")

            # Write to CSV for CPU phase (quote only non-numeric fields for safety)
            csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=PIPE_DELIMITER, quoting=csv.QUOTE_NONNUMERIC)
                for pair in dedup_pairs:
                    writer.writerow(pair)

            return True

        except Exception as e:
            logger.error(f"Failed to load pairs: {e}", exc_info=True)
            return False

    def _save_metadata(self, elapsed: float):
        """Save deduplication statistics."""
        metadata = {
            'version_id': self.version_id,
            'timestamp': datetime.now().isoformat(),
            'elapsed_seconds': elapsed,
            'gpu_available': GPU_AVAILABLE,
            'stats': self.stats,
            'output_files': {
                'screens': str(TEMP_DIR / f'staging_screen_v{self.version_id}.csv'),
                'pairs': str(TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'),
            }
        }

        metadata_file = TEMP_DIR / f'dedup_metadata_v{self.version_id}.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved metadata to {metadata_file}")


def main():
    parser = argparse.ArgumentParser(description="GPU Deduplication Phase")
    parser.add_argument('--version', type=int, required=True, help='Data load version ID')
    parser.add_argument('--log-level', default='INFO', help='Logging level')

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    phase = GPUDedupPhase(version_id=args.version)
    success = phase.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
