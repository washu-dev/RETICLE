#!/usr/bin/env python3
"""
Load JSON and TSV data into versioned staging tables using PostgreSQL COPY.

Fast bulk upload using CSV files and COPY command (100x faster than ORM).

Usage:
  python staging_loader.py --organism homo_sapiens --description "Human data v2"
  python staging_loader.py --organism mus_musculus
"""

import argparse
import csv
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg2
from config import Config

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, desc=None, total=None, unit=None, ncols=None):
        return iterable

logger = logging.getLogger(__name__)

PIPE_DELIMITER = '|'
TEMP_DIR = Path(tempfile.gettempdir()) / 'reticle_staging'


class BulkStagingLoader:
    """Load JSON and TSV files using PostgreSQL COPY for speed."""

    def __init__(self, organism: str, description: str = ""):
        self.organism = organism
        self.description = description or f"Auto-loaded {organism} data"
        self.version_id = None
        self.conn = None
        self.stats = {
            'screens_loaded': 0,
            'genes_loaded': 0,
            'validation_errors': 0,
            'files_processed': 0,
        }
        TEMP_DIR.mkdir(exist_ok=True)

    def run(self) -> bool:
        """Execute the complete staging load."""
        logger.info("="*80)
        logger.info(f"BULK STAGING LOADER: {self.organism}")
        logger.info("="*80)

        start_time = time.time()

        try:
            # Connect to database (require SSL, disable GSS)
            self.conn = psycopg2.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                database=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                sslmode='require',
                gssencmode='disable'
            )
            logger.info("✓ Connected to database")

            # Step 1: Create version record
            self.version_id = self._create_version_record()
            if not self.version_id:
                logger.error("Failed to create version record")
                return False

            # Step 2: Load JSON files
            if not self._load_json_files():
                logger.error("Failed to load JSON files")
                return False

            # Step 3: Load TSV files
            if not self._load_tsv_files():
                logger.error("Failed to load TSV files")
                return False

            # Step 4: Validate data
            if not self._validate_staging_data():
                logger.warning("Validation found errors (see details above)")

            # Step 5: Update version stats
            self._update_version_stats()

            elapsed_time = time.time() - start_time

            logger.info("\n" + "="*80)
            logger.info("STAGING LOAD SUMMARY")
            logger.info("="*80)
            for key, value in self.stats.items():
                logger.info(f"{key:.<40} {value:>10,}")
            logger.info(f"{'elapsed_time (seconds)':.<40} {elapsed_time:>10.1f}")
            logger.info("="*80 + "\n")

            return True

        except Exception as e:
            logger.error(f"Staging load failed: {e}", exc_info=True)
            return False
        finally:
            if self.conn:
                self.conn.close()
                logger.info("✓ Database connection closed")
            self._cleanup_temp_files()

    def _create_version_record(self) -> Optional[int]:
        """Create a new data_load_version record."""
        logger.info(f"\nCreating version record for {self.organism}...")

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO data_load_version (organism, source_type, load_date, status, is_current, load_description)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING version_id
            """, (self.organism, 'biogrid_orcs', datetime.now(), 'pending', False, self.description))

            version_id = cursor.fetchone()[0]
            self.conn.commit()
            logger.info(f"✓ Created version_id: {version_id}")
            return version_id

        except Exception as e:
            logger.error(f"Failed to create version record: {e}")
            return None

    def _load_json_files(self) -> bool:
        """Load JSON files using batched INSERT (executemany)."""
        logger.info(f"\nLoading JSON files for {self.organism}...")

        if self.organism not in Config.ORGANISMS:
            logger.error(f"Unknown organism: {self.organism}")
            return False

        organism_config = Config.ORGANISMS[self.organism]
        json_pattern = organism_config['json_pattern']
        json_files = list(Config.DATA_DIR.glob(json_pattern))

        if not json_files:
            logger.error(f"No JSON files found matching {json_pattern}")
            return False

        logger.info(f"Found {len(json_files)} JSON file(s)")

        try:
            screen_rows = []
            json_filenames = []

            for json_file in json_files:
                logger.info(f"Processing {json_file.name}...")
                json_filenames.append(json_file.name)

                with open(json_file, 'r') as jf:
                    data = json.load(jf)

                # Flatten JSON structure: { "381": [{...}], "902": [{...}], ... }
                screens = []
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, list):
                            screens.extend(value)
                        else:
                            screens.append(value)
                else:
                    screens = [data]

                logger.info(f"  Found {len(screens)} screens")

                for screen in tqdm(screens, desc="    Building rows", unit="screen", ncols=80, leave=False):
                    try:
                        screen_id = int(screen.get('SCREEN_ID', 0))
                        biogrid_screen_id = screen.get('SCREEN_ID')
                        organism = self.organism
                        annotation_source = screen.get('SOURCE')
                        moi = screen.get('MOI')
                        notes = screen.get('NOTES')

                        screen_rows.append((
                            self.version_id,
                            screen_id,
                            biogrid_screen_id,
                            organism,
                            annotation_source,
                            moi,
                            notes
                        ))
                    except Exception as e:
                        logger.warning(f"  Failed to process screen: {e}")
                        self.stats['validation_errors'] += 1

            logger.info(f"✓ Built {len(screen_rows)} screen rows")
            self.stats['screens_loaded'] = len(screen_rows)

            # Store JSON filenames in version record
            self._update_version_filenames(json_filenames=json_filenames)

            # Batch insert into database
            if screen_rows:
                logger.info(f"\nInserting {len(screen_rows)} screens into database...")
                self._batch_insert('staging_screen', [
                    'version_id', 'screen_id', 'biogrid_screen_id',
                    'organism', 'annotation_source', 'moi', 'notes'
                ], screen_rows)

            return True

        except Exception as e:
            logger.error(f"Failed to load JSON files: {e}", exc_info=True)
            return False

    def _load_tsv_files(self) -> bool:
        """Load TSV files and create CSV for bulk insert."""
        logger.info(f"\nLoading TSV files for {self.organism}...")

        if self.organism not in Config.ORGANISMS:
            logger.error(f"Unknown organism: {self.organism}")
            return False

        organism_config = Config.ORGANISMS[self.organism]
        tsv_pattern = organism_config['tsv_pattern']
        tsv_files = sorted(Config.DATA_DIR.glob(tsv_pattern))

        if not tsv_files:
            logger.error(f"No TSV files found matching {tsv_pattern}")
            return False

        logger.info(f"Found {len(tsv_files)} TSV file(s)")

        try:
            # Create CSV file for bulk upload
            csv_file = TEMP_DIR / f'staging_screen_gene_v{self.version_id}.csv'

            tsv_filenames = []
            with open(csv_file, "w", encoding="utf-8") as csv_f:
                gene_count = 0
                file_count = 0

                for tsv_file in tqdm(tsv_files, desc="Processing TSV files", unit="file", ncols=80):
                    tsv_filenames.append(tsv_file.name)
                    file_count += 1
                    file_gene_count = 0

                    try:
                        with open(tsv_file, "r", encoding="utf-8") as tsv_f:
                            reader = csv.DictReader(tsv_f, delimiter='\t')

                            for row_num, row in enumerate(reader, start=2):
                                try:
                                    # Read SCREEN_ID from the data (authoritative source)
                                    screen_id_str = row.get('#SCREEN_ID', '').strip()
                                    if not screen_id_str:
                                        self.stats['validation_errors'] += 1
                                        continue

                                    screen_id = int(screen_id_str)

                                    identifier_id = row.get('IDENTIFIER_ID', '').strip()
                                    gene_symbol = row.get('OFFICIAL_SYMBOL', '').strip()
                                    official_symbol = gene_symbol
                                    hit_flag = 't' if row.get('HIT', '').upper() == 'YES' else 'f'

                                    # Extract scores
                                    score_strs = []
                                    for i in range(1, 6):
                                        score_key = f'SCORE.{i}'
                                        if score_key in row and row[score_key]:
                                            try:
                                                score_strs.append(str(float(row[score_key])))
                                            except ValueError:
                                                score_strs.append('')
                                        else:
                                            score_strs.append('')

                                    # Write pipe-delimited row
                                    row_data = [
                                        str(self.version_id),
                                        str(screen_id),
                                        str(screen_id),  # biogrid_screen_id
                                        identifier_id,
                                        gene_symbol,
                                        official_symbol,
                                        hit_flag,
                                    ] + score_strs + [
                                        tsv_file.name,
                                        str(row_num)
                                    ]
                                    row_str = PIPE_DELIMITER.join(row_data) + '\n'
                                    csv_f.write(row_str)
                                    gene_count += 1
                                    file_gene_count += 1
                                except Exception as e:
                                    self.stats['validation_errors'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to read {tsv_file.name}: {e}")
                        self.stats['validation_errors'] += 1
                        continue

            # Check CSV file was created and has content
            csv_size = csv_file.stat().st_size if csv_file.exists() else 0
            logger.info(f"✓ Created CSV with {gene_count:,} gene-screen pairs ({csv_size:,} bytes)")

            if gene_count == 0:
                logger.warning("⚠ CSV file is empty! No genes were written.")

            self.stats['genes_loaded'] = gene_count
            self.stats['files_processed'] = file_count

            # Store TSV filenames in version record
            self._update_version_filenames(tsv_filenames=tsv_filenames)

            # Load CSV into database
            if gene_count > 0:
                logger.info(f"\n  Inserting {gene_count} gene-screen pairs into database...")
                success = self._copy_csv_to_db(csv_file, 'staging_screen_gene', [
                    'version_id', 'screen_id', 'biogrid_screen_id',
                    'identifier_id', 'gene_symbol', 'official_symbol', 'hit_flag',
                    'score_1', 'score_2', 'score_3', 'score_4', 'score_5',
                    'tsv_filename', 'tsv_row_number'
                ])

                if not success:
                    logger.error("  ✗ COPY command failed, see details above")
                    return False
            else:
                logger.warning("  ⚠ Skipping COPY (no genes to load)")

            return True

        except Exception as e:
            logger.error(f"Failed to load TSV files: {e}", exc_info=True)
            return False

    def _batch_insert(self, table: str, columns: list, rows: list) -> bool:
        """Batch insert rows using executemany (fast for direct data)."""
        logger.info(f"  Uploading to {table}...")
        insert_start = time.time()

        try:
            placeholders = ','.join(['%s'] * len(columns))
            columns_str = ','.join(columns)
            sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"

            cursor = self.conn.cursor()
            cursor.executemany(sql, rows)
            self.conn.commit()

            insert_time = time.time() - insert_start
            logger.info(f"  ✓ {table} batch insert completed ({insert_time:.1f}s, {len(rows)} rows)")
            return True

        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            self.conn.rollback()
            return False

    def _copy_csv_to_db(self, csv_file: Path, table: str, columns: list) -> bool:
        """Use PostgreSQL COPY to bulk load CSV file."""
        logger.info(f"Uploading to {table}...")
        copy_start = time.time()

        try:
            # Verify CSV file exists and has content
            if not csv_file.exists():
                logger.error(f"CSV file not found: {csv_file}")
                return False

            csv_size = csv_file.stat().st_size

            # Count rows in CSV
            row_count = 0
            with open(csv_file, 'r', encoding='utf-8') as f:
                row_count = sum(1 for _ in f)

            if row_count == 0:
                logger.warning("CSV file is empty, nothing to COPY")
                return True

            # Perform COPY
            cursor = self.conn.cursor()
            with open(csv_file, 'r', encoding='utf-8') as f:
                cursor.copy_from(
                    f,
                    table,
                    columns=columns,
                    sep=PIPE_DELIMITER,
                    null=''
                )

            self.conn.commit()
            copy_time = time.time() - copy_start

            # Verify rows were inserted
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE version_id = %s", (self.version_id,))
            inserted_count = cursor.fetchone()[0]
            logger.info(f"✓ {table} COPY completed ({copy_time:.1f}s, {inserted_count:,} rows)")

            return True

        except Exception as e:
            logger.error(f"COPY failed: {e}", exc_info=True)
            self.conn.rollback()
            return False

    def _update_version_filenames(self, json_filenames=None, tsv_filenames=None):
        """Store source filenames in version record."""
        try:
            cursor = self.conn.cursor()

            if json_filenames:
                # Convert list to PostgreSQL array syntax
                json_array = '{' + ','.join(json_filenames) + '}'
                cursor.execute(
                    "UPDATE data_load_version SET json_filenames = %s WHERE version_id = %s",
                    (json_array, self.version_id)
                )

            if tsv_filenames:
                # Convert list to PostgreSQL array syntax
                tsv_array = '{' + ','.join(tsv_filenames) + '}'
                cursor.execute(
                    "UPDATE data_load_version SET tsv_filenames = %s WHERE version_id = %s",
                    (tsv_array, self.version_id)
                )

            self.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update version filenames: {e}")

    def _validate_staging_data(self) -> bool:
        """Validate staging data and mark invalid rows."""
        logger.info(f"\nValidating staging data...")

        try:
            cursor = self.conn.cursor()

            # Mark missing biogrid_screen_id in staging_screen
            cursor.execute("""
                UPDATE staging_screen
                SET validation_errors = 'Missing biogrid_screen_id'
                WHERE version_id = %s
                AND (biogrid_screen_id IS NULL OR biogrid_screen_id = '')
            """, (self.version_id,))

            # Mark missing identifier_id in staging_screen_gene
            cursor.execute("""
                UPDATE staging_screen_gene
                SET validation_errors = 'Missing identifier_id'
                WHERE version_id = %s
                AND (identifier_id IS NULL OR identifier_id = '')
            """, (self.version_id,))

            # Count total errors
            cursor.execute("""
                SELECT COUNT(*) FROM staging_screen
                WHERE version_id = %s AND validation_errors IS NOT NULL
            """, (self.version_id,))
            screen_error_count = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM staging_screen_gene
                WHERE version_id = %s AND validation_errors IS NOT NULL
            """, (self.version_id,))
            gene_error_count = cursor.fetchone()[0] or 0

            total_errors = screen_error_count + gene_error_count

            self.conn.commit()

            logger.info(f"✓ Validation complete ({total_errors:,} errors)")

            return total_errors == 0

        except Exception as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            return False

    def _update_version_stats(self):
        """Update version record with final stats."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE data_load_version
                SET status = %s, is_current = %s,
                    num_screens = %s, num_genes = %s, file_count = %s
                WHERE version_id = %s
            """, (
                'valid', True,
                self.stats['screens_loaded'],
                self.stats['genes_loaded'],
                self.stats['files_processed'],
                self.version_id
            ))
            self.conn.commit()
            logger.info("✓ Version stats updated")
        except Exception as e:
            logger.error(f"Failed to update version stats: {e}")

    def _cleanup_temp_files(self):
        """Clean up temporary CSV files."""
        try:
            for f in TEMP_DIR.glob(f'staging_screen*_v{self.version_id}.csv'):
                f.unlink()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='RETICLE bulk staging loader (fast COPY-based upload)'
    )
    parser.add_argument(
        '--organism',
        required=True,
        choices=['homo_sapiens', 'mus_musculus'],
        help='Organism to load'
    )
    parser.add_argument(
        '--description',
        default='',
        help='Load description'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format=Config.LOG_FORMAT
    )

    # Validate configuration
    is_valid, errors = Config.validate()
    if not is_valid:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return 1

    # Run loader
    loader = BulkStagingLoader(args.organism, args.description)
    success = loader.run()

    return 0 if success else 1


if __name__ == '__main__':
    try:
        exit(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        exit(1)
