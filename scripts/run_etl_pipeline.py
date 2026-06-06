#!/usr/bin/env python3
"""
Run the RETICLE ETL pipeline on a specific data version.

This is Step 2 of the data warehouse workflow:
  1. Load JSON/TSV into staging (staging_loader.py)
  2. Run ETL pipeline (this script)

Usage:
  python run_etl_pipeline.py --version 1
  python run_etl_pipeline.py --version 2 --pipeline-version 1.0.0
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Optional

from config import Config
from database import DatabaseManager, get_db_manager
from sqlalchemy import text

logger = logging.getLogger(__name__)

class ETLPipeline:
    """Execute the ETL pipeline on a data version."""

    def __init__(self, version_id: int, pipeline_version: Optional[str] = None):
        self.version_id = version_id
        self.pipeline_version = pipeline_version or Config.PIPELINE_VERSION
        self.db = get_db_manager()
        self.run_id: Optional[int] = None

    def run(self) -> bool:
        """Execute the complete ETL pipeline."""
        logger.info("="*80)
        logger.info(f"ETL PIPELINE EXECUTION")
        logger.info("="*80)
        logger.info(f"Version ID: {self.version_id}")
        logger.info(f"Pipeline Version: {self.pipeline_version}\n")

        try:
            # Call the PostgreSQL function
            with self.db.get_session() as session:
                logger.info("Executing run_etl_pipeline() function...\n")

                result = session.execute(text("""
                    SELECT * FROM run_etl_pipeline(
                        p_version_id := :version_id,
                        p_pipeline_version := :pipeline_version
                    )
                """), {
                    'version_id': self.version_id,
                    'pipeline_version': self.pipeline_version
                })

                rows = result.fetchall()

                logger.info("="*80)
                logger.info("ETL PIPELINE RESULT")
                logger.info("="*80)

                for row in rows:
                    run_id, status, duration, message = row
                    self.run_id = run_id

                    logger.info(f"Run ID:       {run_id}")
                    logger.info(f"Status:       {status}")
                    logger.info(f"Duration:     {duration:.1f}s" if duration else "Duration:     N/A")
                    logger.info(f"Message:      {message}")

                logger.info("="*80 + "\n")

                # Show detailed audit log
                if status == 'completed':
                    self._show_audit_log(session)
                    return True
                else:
                    logger.error("Pipeline failed. Check logs above.")
                    return False

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
            return False

    def _show_audit_log(self, session):
        """Display detailed audit log from the ETL run."""
        logger.info("ETL AUDIT LOG")
        logger.info("="*80)

        result = session.execute(text("""
            SELECT
                step_name,
                status,
                rows_processed,
                rows_inserted,
                rows_skipped,
                duration_seconds,
                error_message
            FROM etl_audit_log
            WHERE run_id = :run_id
            ORDER BY step_order
        """), {'run_id': self.run_id})

        rows = result.fetchall()

        for row in rows:
            step_name, status, rows_proc, rows_ins, rows_skip, duration, error = row

            logger.info(f"\n  {step_name}:")
            logger.info(f"    Status:           {status}")
            if rows_proc:
                logger.info(f"    Rows processed:   {rows_proc:,}")
            if rows_ins:
                logger.info(f"    Rows inserted:    {rows_ins:,}")
            if rows_skip:
                logger.info(f"    Rows skipped:     {rows_skip:,}")
            if duration:
                logger.info(f"    Duration:         {duration:.2f}s")
            if error:
                logger.info(f"    Error:            {error}")

        logger.info("\n" + "="*80 + "\n")

    def show_version_info(self):
        """Show information about the version being processed."""
        logger.info("VERSION INFORMATION")
        logger.info("="*80)

        try:
            with self.db.get_session() as session:
                result = session.execute(text("""
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
                    WHERE version_id = :version_id
                """), {'version_id': self.version_id})

                row = result.fetchone()

                if not row:
                    logger.error(f"Version {self.version_id} not found")
                    return False

                version_id, organism, load_date, status, is_current, num_screens, num_genes, num_hits, file_count = row

                logger.info(f"Version ID:        {version_id}")
                logger.info(f"Organism:          {organism}")
                logger.info(f"Load Date:         {load_date}")
                logger.info(f"Status:            {status}")
                logger.info(f"Is Current:        {is_current}")
                logger.info(f"Screens:           {num_screens:,}" if num_screens else "Screens:           N/A")
                logger.info(f"Genes:             {num_genes:,}" if num_genes else "Genes:             N/A")
                logger.info(f"Gene-Screen Hits:  {num_hits:,}" if num_hits else "Gene-Screen Hits:  N/A")
                logger.info(f"Files Processed:   {file_count}" if file_count else "Files Processed:   N/A")

                logger.info("="*80 + "\n")
                return True

        except Exception as e:
            logger.error(f"Failed to show version info: {e}")
            return False


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

    # Validate configuration
    is_valid, errors = Config.validate()
    if not is_valid:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return 1

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
