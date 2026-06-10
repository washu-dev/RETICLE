#!/usr/bin/env python3
"""
Data warehouse maintenance utilities: purge, rollback, and storage analysis.

Usage:
  python maintenance.py --list-versions
  python maintenance.py --show-storage
  python maintenance.py --purge-version 1
  python maintenance.py --purge-old
  python maintenance.py --promote-version 2

Run from: database/ folder
  cd database && python3 maintenance.py --list-versions
"""

import argparse
import logging
import sys
from typing import Optional
from pathlib import Path
from tabulate import tabulate

import psycopg2

# Add scripts folder to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from config import Config

logger = logging.getLogger(__name__)

class MaintenanceManager:
    """Manage data warehouse maintenance operations."""

    def __init__(self):
        self.db_params = Config.get_psycopg2_params()
        self.db_params['sslmode'] = 'require'

    def list_versions(self) -> bool:
        """List all data versions."""
        logger.info("\n" + "="*100)
        logger.info("DATA LOAD VERSIONS")
        logger.info("="*100 + "\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    version_id,
                    organism,
                    load_date,
                    status,
                    CASE WHEN is_current THEN '✓ CURRENT' ELSE '' END as current,
                    num_screens,
                    num_genes,
                    file_count,
                    load_description
                FROM data_load_version
                ORDER BY load_date DESC
            """)

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                logger.info("No versions found")
                return True

            table_data = [
                [
                    row[0],  # version_id
                    row[1],  # organism
                    str(row[2])[:19],  # load_date
                    row[3],  # status
                    row[4],  # current
                    f"{row[5]:,}" if row[5] else "-",  # num_screens
                    f"{row[6]:,}" if row[6] else "-",  # num_genes
                    row[7] if row[7] else "-",  # file_count
                    row[8][:40] if row[8] else ""  # description (truncated)
                ]
                for row in rows
            ]

            headers = [
                "Version", "Organism", "Load Date", "Status",
                "Status", "Screens", "Genes", "Files", "Description"
            ]

            print(tabulate(table_data, headers=headers, tablefmt='grid'))
            logger.info("")
            return True

        except Exception as e:
            logger.error(f"Failed to list versions: {e}", exc_info=True)
            return False

    def show_storage(self) -> bool:
        """Show storage usage per version."""
        logger.info("\n" + "="*120)
        logger.info("STORAGE USAGE BY VERSION")
        logger.info("="*120 + "\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM get_version_storage_details()
                ORDER BY load_date DESC
            """)

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                logger.info("No versions found")
                return True

            table_data = [
                [
                    row[0],  # version_id
                    row[1],  # organism
                    str(row[2])[:10],  # load_date
                    "✓" if row[3] else "",  # is_current
                    row[8],  # screen_rows
                    row[9],  # gene_rows
                    row[10],  # screen_gene_raw_rows
                    row[11],  # fact_screen_gene_rows
                    f"{row[12]:.1f} MB" if row[12] else "N/A"  # total_size_mb
                ]
                for row in rows
            ]

            headers = [
                "Version", "Organism", "Date", "Current",
                "Screens", "Genes", "Raw Pairs", "Facts", "Total Size"
            ]

            print(tabulate(table_data, headers=headers, tablefmt='grid'))
            logger.info("")
            return True

        except Exception as e:
            logger.error(f"Failed to show storage: {e}", exc_info=True)
            return False

    def estimate_purge(self, version_id: int) -> bool:
        """Estimate space that would be freed by purging a version."""
        logger.info(f"\nEstimating space to be freed by purging version {version_id}...\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM estimate_purge_space(%s)
            """, (version_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if not row:
                logger.error(f"Version {version_id} not found")
                return False

            version_id, organism, space_mb, rows_deleted = row

            logger.info(f"Version:          {version_id}")
            logger.info(f"Organism:         {organism}")
            logger.info(f"Estimated space:  {space_mb:.1f} MB")
            logger.info(f"Rows to delete:   {rows_deleted:,}\n")

            return True

        except Exception as e:
            logger.error(f"Failed to estimate purge: {e}", exc_info=True)
            return False

    def purge_version(self, version_id: int, confirm: bool = True) -> bool:
        """Purge a specific version."""
        if confirm:
            self.estimate_purge(version_id)
            response = input(f"Permanently delete version {version_id}? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                logger.info("Purge cancelled")
                return False

        logger.info(f"\nPurging version {version_id}...\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM purge_version(%s)
            """, (version_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            status, versions_deleted, staging_rows, processed_rows, space_freed, message = row

            logger.info("="*80)
            logger.info("PURGE RESULT")
            logger.info("="*80)
            logger.info(f"Status:              {status}")
            logger.info(f"Versions deleted:    {versions_deleted}")
            logger.info(f"Staging rows:        {staging_rows:,}")
            logger.info(f"Processed rows:      {processed_rows:,}")
            logger.info(f"Space freed:         {space_freed:.1f} MB")
            logger.info(f"Message:             {message}")
            logger.info("="*80 + "\n")

            return status == 'success'

        except Exception as e:
            logger.error(f"Failed to purge version: {e}", exc_info=True)
            return False

    def purge_old_versions(self, confirm: bool = True) -> bool:
        """Purge all old versions except current."""
        logger.info("\nFinding old versions...\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) FROM data_load_version WHERE is_current = FALSE
            """)

            old_count = cursor.fetchone()[0] or 0

            if old_count == 0:
                logger.info("No old versions to purge")
                cursor.close()
                conn.close()
                return True

            logger.info(f"Found {old_count} old version(s)")

            if confirm:
                response = input(f"Permanently delete {old_count} old version(s)? Type 'yes' to confirm: ")
                if response.lower() != 'yes':
                    logger.info("Purge cancelled")
                    cursor.close()
                    conn.close()
                    return False

            logger.info("\nPurging old versions...\n")

            cursor.execute("""
                SELECT * FROM purge_old_versions()
            """)

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            status, versions_deleted, total_rows, space_freed, message = row

            logger.info("="*80)
            logger.info("PURGE RESULT")
            logger.info("="*80)
            logger.info(f"Status:              {status}")
            logger.info(f"Versions deleted:    {versions_deleted}")
            logger.info(f"Total rows deleted:  {total_rows:,}")
            logger.info(f"Space freed:         {space_freed:.1f} MB")
            logger.info(f"Message:             {message}")
            logger.info("="*80 + "\n")

            return status == 'success'

        except Exception as e:
            logger.error(f"Failed to purge old versions: {e}", exc_info=True)
            return False

    def promote_version(self, version_id: int) -> bool:
        """Promote a version back to current."""
        logger.info(f"\nPromoting version {version_id} to current...\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM promote_version_to_current(%s)
            """, (version_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            status, message = row

            logger.info("="*80)
            logger.info("PROMOTION RESULT")
            logger.info("="*80)
            logger.info(f"Status:  {status}")
            logger.info(f"Message: {message}")
            logger.info("="*80 + "\n")

            return status == 'success'

        except Exception as e:
            logger.error(f"Failed to promote version: {e}", exc_info=True)
            return False

    def show_etl_history(self) -> bool:
        """Show ETL pipeline run history."""
        logger.info("\n" + "="*120)
        logger.info("ETL PIPELINE RUN HISTORY")
        logger.info("="*120 + "\n")

        try:
            conn = psycopg2.connect(**self.db_params)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM v_etl_run_summary LIMIT 20
            """)

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                logger.info("No ETL runs found")
                return True

            table_data = [
                [
                    row[0],  # run_id
                    row[1],  # version_id
                    row[2],  # organism
                    str(row[3])[:19],  # run_date
                    row[4],  # status
                    "✓" if row[5] else "",  # is_current
                    f"{row[6]:.1f}s" if row[6] else "N/A",  # duration
                ]
                for row in rows
            ]

            headers = [
                "Run ID", "Version", "Organism", "Run Date",
                "Status", "Current", "Duration"
            ]

            print(tabulate(table_data, headers=headers, tablefmt='grid'))
            logger.info("")
            return True

        except Exception as e:
            logger.error(f"Failed to show ETL history: {e}", exc_info=True)
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='RETICLE data warehouse maintenance utilities'
    )

    # Mutually exclusive operation group
    ops = parser.add_mutually_exclusive_group(required=True)
    ops.add_argument(
        '--list-versions',
        action='store_true',
        help='List all data versions'
    )
    ops.add_argument(
        '--show-storage',
        action='store_true',
        help='Show storage usage per version'
    )
    ops.add_argument(
        '--show-etl-history',
        action='store_true',
        help='Show ETL pipeline run history'
    )
    ops.add_argument(
        '--estimate-purge',
        type=int,
        metavar='VERSION_ID',
        help='Estimate space to be freed by purging a version'
    )
    ops.add_argument(
        '--purge-version',
        type=int,
        metavar='VERSION_ID',
        help='Purge a specific version'
    )
    ops.add_argument(
        '--purge-old',
        action='store_true',
        help='Purge all old versions (keep current)'
    )
    ops.add_argument(
        '--promote-version',
        type=int,
        metavar='VERSION_ID',
        help='Promote a version back to current'
    )

    parser.add_argument(
        '--no-confirm',
        action='store_true',
        help='Skip confirmation prompts (for destructive operations)'
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

    # Create manager and execute operation
    manager = MaintenanceManager()

    if args.list_versions:
        success = manager.list_versions()
    elif args.show_storage:
        success = manager.show_storage()
    elif args.show_etl_history:
        success = manager.show_etl_history()
    elif args.estimate_purge is not None:
        success = manager.estimate_purge(args.estimate_purge)
    elif args.purge_version is not None:
        success = manager.purge_version(args.purge_version, not args.no_confirm)
    elif args.purge_old:
        success = manager.purge_old_versions(not args.no_confirm)
    elif args.promote_version is not None:
        success = manager.promote_version(args.promote_version)
    else:
        parser.print_help()
        return 1

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
