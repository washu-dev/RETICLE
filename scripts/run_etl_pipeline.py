#!/usr/bin/env python3
"""
Run the RETICLE ETL pipeline on a specific data version.

Direct psycopg2 implementation (no SQLAlchemy ORM).
- Calls run_etl_pipeline() stored procedure
- Displays audit trail
- Simple, transparent, efficient

Usage:
  python run_etl_pipeline.py --version 1
  python run_etl_pipeline.py --version 2 --pipeline-version 1.0.0
"""

import argparse
import logging
import sys
import time
import traceback
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from config import Config

logger = logging.getLogger(__name__)


class ETLPipeline:
    """Execute the ETL pipeline on a data version using direct psycopg2."""

    def __init__(self, version_id: int, pipeline_version: str = None):
        self.version_id = version_id
        self.pipeline_version = pipeline_version or Config.PIPELINE_VERSION
        self.conn = None
        self.run_id = None

    def connect(self) -> bool:
        """Connect to database."""
        try:
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
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False

    def run(self) -> bool:
        """Execute the complete ETL pipeline."""
        logger.info("="*80)
        logger.info("ETL PIPELINE EXECUTION")
        logger.info("="*80)
        logger.info(f"Version ID: {self.version_id}")
        logger.info(f"Pipeline Version: {self.pipeline_version}\n")

        if not self.connect():
            return False

        start_time = time.time()

        try:
            logger.info("⏳ Executing run_etl_pipeline() stored procedure...")
            logger.info("   Processing: validate → load → build → aggregate\n")

            cursor = self.conn.cursor(cursor_factory=RealDictCursor)

            # Call the stored procedure
            cursor.execute(
                "SELECT * FROM run_etl_pipeline(%s, %s)",
                (self.version_id, self.pipeline_version)
            )

            result = cursor.fetchone()

            if not result:
                logger.error("❌ No result from stored procedure")
                return False

            run_id = result['run_id']
            status = result['status']
            duration = result['duration_seconds']
            message = result['message']
            self.run_id = run_id

            elapsed = time.time() - start_time
            status_icon = "✓" if status == "completed" else "✗"

            logger.info("="*80)
            logger.info("ETL PIPELINE RESULT")
            logger.info("="*80)
            logger.info(f"{status_icon} Run ID:       {run_id}")
            logger.info(f"  Status:       {status}")
            logger.info(f"  Duration:     {duration:.1f}s" if duration else "  Duration:     N/A")
            logger.info(f"  Total time:   {elapsed:.1f}s")
            if message:
                logger.info(f"  Message:      {message}")
            logger.info("="*80 + "\n")

            # Show detailed audit log
            if status == "completed":
                self._show_audit_log(cursor)
                return True
            else:
                logger.error("❌ Pipeline failed!")
                logger.error(f"   Error: {message}")
                self._show_failed_steps(cursor)
                return False

        except Exception as e:
            logger.error("\n" + "="*80)
            logger.error("ETL PIPELINE EXECUTION ERROR")
            logger.error("="*80)
            logger.error(f"❌ Database error: {e}")
            logger.error("\nDETAILED ERROR:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.error(f"   {line}")
            logger.error("="*80 + "\n")
            return False

        finally:
            if self.conn:
                self.conn.close()

    def _show_audit_log(self, cursor):
        """Display detailed audit log from the ETL run."""
        logger.info("ETL AUDIT LOG")
        logger.info("="*80)

        cursor.execute(
            """
            SELECT
                step_name,
                status,
                rows_processed,
                rows_inserted,
                rows_skipped,
                duration_seconds,
                error_message
            FROM etl_audit_log
            WHERE run_id = %s
            ORDER BY step_order
            """,
            (self.run_id,)
        )

        rows = cursor.fetchall()

        for row in rows:
            status_icon = "✓" if row['status'] == "completed" else "⚠"

            logger.info(f"\n  {status_icon} {row['step_name']}:")
            logger.info(f"      Status:           {row['status']}")
            if row['rows_processed']:
                logger.info(f"      Rows processed:   {row['rows_processed']:,}")
            if row['rows_inserted']:
                logger.info(f"      Rows inserted:    {row['rows_inserted']:,}")
            if row['rows_skipped']:
                logger.info(f"      Rows skipped:     {row['rows_skipped']:,}")
            if row['duration_seconds']:
                logger.info(f"      Duration:         {row['duration_seconds']:.2f}s")
            if row['error_message']:
                logger.error(f"      Error:            {row['error_message']}")

        logger.info("\n" + "="*80 + "\n")

    def _show_failed_steps(self, cursor):
        """Show which steps failed and their error messages."""
        logger.error("\nFAILED STEPS DETAIL:")
        logger.error("="*80)

        cursor.execute(
            """
            SELECT
                step_name,
                status,
                error_message
            FROM etl_audit_log
            WHERE run_id = %s
            AND status != 'completed'
            ORDER BY step_order
            """,
            (self.run_id,)
        )

        rows = cursor.fetchall()

        if not rows:
            logger.error("No audit log entries found. Error may have occurred during function initialization.")
        else:
            for row in rows:
                logger.error(f"\n❌ {row['step_name']}")
                logger.error(f"   Status: {row['status']}")
                if row['error_message']:
                    logger.error(f"   Error:  {row['error_message']}")

        logger.error("="*80 + "\n")

    def show_version_info(self):
        """Show information about the version being processed."""
        if not self.connect():
            return False

        logger.info("VERSION INFORMATION")
        logger.info("="*80)

        try:
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT
                    version_id,
                    organism,
                    load_date,
                    status,
                    is_current,
                    num_screens,
                    num_genes,
                    num_gene_hits,
                    file_count
                FROM data_load_version
                WHERE version_id = %s
                """,
                (self.version_id,)
            )

            row = cursor.fetchone()

            if not row:
                logger.error(f"Version {self.version_id} not found")
                return False

            logger.info(f"Version ID:        {row['version_id']}")
            logger.info(f"Organism:          {row['organism']}")
            logger.info(f"Load Date:         {row['load_date']}")
            logger.info(f"Status:            {row['status']}")
            logger.info(f"Is Current:        {row['is_current']}")
            logger.info(f"Screens:           {row['num_screens']:,}" if row['num_screens'] else "Screens:           N/A")
            logger.info(f"Genes:             {row['num_genes']:,}" if row['num_genes'] else "Genes:             N/A")
            logger.info(f"Gene-Screen Hits:  {row['num_gene_hits']:,}" if row['num_gene_hits'] else "Gene-Screen Hits:  N/A")
            logger.info(f"Files Processed:   {row['file_count']}" if row['file_count'] else "Files Processed:   N/A")

            logger.info("="*80 + "\n")
            return True

        except Exception as e:
            logger.error(f"Failed to show version info: {e}")
            return False

        finally:
            if self.conn:
                self.conn.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Execute RETICLE ETL pipeline on a versioned data load'
    )
    parser.add_argument(
        '--version',
        type=int,
        required=True,
        help='Version ID to process'
    )
    parser.add_argument(
        '--pipeline-version',
        default=None,
        help='Pipeline version string (default: from config)'
    )
    parser.add_argument(
        '--show-info',
        action='store_true',
        help='Show version info before running pipeline'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format=Config.LOG_FORMAT
    )

    # Create pipeline
    pipeline = ETLPipeline(args.version, args.pipeline_version)

    # Show version info if requested
    if args.show_info:
        if not pipeline.show_version_info():
            return 1

    # Run pipeline
    success = pipeline.run()

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
