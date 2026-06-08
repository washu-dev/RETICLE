#!/usr/bin/env python3
"""
Validate ETL pipeline readiness before execution.

Checks:
1. Database connectivity
2. Schema completeness (tables, columns, functions)
3. Staging data (row counts, no critical nulls)
4. Version record integrity
5. ETL function availability
"""

import sys
import logging
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ETLReadinessValidator:
    def __init__(self):
        self.conn = None
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = []

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
            logger.info("✓ Database connection successful")
            self.checks_passed += 1
            return True
        except Exception as e:
            logger.error(f"✗ Database connection failed: {e}")
            self.checks_failed += 1
            return False

    def check_schema_tables(self) -> bool:
        """Check all required tables exist."""
        required_tables = {
            'data_load_version': ['version_id', 'organism', 'num_screens', 'num_genes'],
            'staging_screen': ['staging_id', 'version_id', 'screen_id', 'biogrid_screen_id'],
            'staging_screen_gene': ['staging_id', 'version_id', 'identifier_id'],
            'screen': ['screen_id', 'version_id', 'biogrid_screen_id'],
            'gene': ['gene_id', 'version_id', 'identifier_id'],
            'screen_gene_raw': ['screen_gene_raw_id', 'version_id', 'screen_id', 'gene_id'],
            'fact_screen_gene': ['fact_id', 'version_id', 'screen_id', 'gene_id'],
            'dim_screen': ['dim_screen_id', 'version_id', 'screen_id'],
            'dim_gene': ['dim_gene_id', 'version_id', 'gene_id'],
            'etl_pipeline_run': ['run_id', 'data_load_version_id'],
            'etl_audit_log': ['audit_id', 'run_id'],
        }

        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        all_ok = True

        for table, required_cols in required_tables.items():
            try:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    (table,)
                )
                existing_cols = {row['column_name'] for row in cursor.fetchall()}

                missing = set(required_cols) - existing_cols
                if missing:
                    logger.error(f"✗ Table '{table}' missing columns: {missing}")
                    self.checks_failed += 1
                    all_ok = False
                else:
                    logger.info(f"✓ Table '{table}' has all required columns")
                    self.checks_passed += 1
            except Exception as e:
                logger.error(f"✗ Table '{table}' does not exist: {e}")
                self.checks_failed += 1
                all_ok = False

        return all_ok

    def check_etl_functions(self) -> bool:
        """Check ETL functions are available."""
        cursor = self.conn.cursor()
        all_ok = True

        # Check for ETL views
        views = ['v_validation_issues', 'v_etl_run_summary']
        for view in views:
            try:
                cursor.execute(f"SELECT 1 FROM {view} LIMIT 1")
                logger.info(f"✓ View '{view}' exists and is queryable")
                self.checks_passed += 1
            except Exception as e:
                logger.warning(f"⚠ View '{view}' not found or not queryable: {e}")
                self.warnings.append(f"View {view} may not be available")
                self.checks_failed += 1
                all_ok = False

        return all_ok

    def check_staging_data(self) -> bool:
        """Check staging tables have data."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        all_ok = True

        # Get current version
        try:
            cursor.execute("SELECT version_id, organism FROM data_load_version ORDER BY version_id DESC LIMIT 1")
            version = cursor.fetchone()
            if not version:
                logger.error("✗ No data_load_version records found. Run staging_loader.py first.")
                self.checks_failed += 1
                return False

            version_id = version['version_id']
            organism = version['organism']
            logger.info(f"✓ Found current version: version_id={version_id}, organism={organism}")
            self.checks_passed += 1

            # Check staging_screen
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM staging_screen WHERE version_id = %s",
                (version_id,)
            )
            screen_count = cursor.fetchone()['cnt']
            if screen_count == 0:
                logger.error(f"✗ No screens in staging_screen for version {version_id}")
                self.checks_failed += 1
                all_ok = False
            else:
                logger.info(f"✓ Found {screen_count:,} screens in staging_screen")
                self.checks_passed += 1

            # Check staging_screen_gene
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM staging_screen_gene WHERE version_id = %s",
                (version_id,)
            )
            gene_count = cursor.fetchone()['cnt']
            if gene_count == 0:
                logger.error(f"✗ No genes in staging_screen_gene for version {version_id}")
                self.checks_failed += 1
                all_ok = False
            else:
                logger.info(f"✓ Found {gene_count:,} gene-screen pairs in staging_screen_gene")
                self.checks_passed += 1

            # Check for validation errors
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM staging_screen WHERE version_id = %s AND validation_errors IS NOT NULL",
                (version_id,)
            )
            error_count = cursor.fetchone()['cnt']
            if error_count > 0:
                logger.warning(f"⚠ {error_count} screens have validation errors")
                self.warnings.append(f"Staging screens with errors: {error_count}")

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM staging_screen_gene WHERE version_id = %s AND validation_errors IS NOT NULL",
                (version_id,)
            )
            gene_error_count = cursor.fetchone()['cnt']
            if gene_error_count > 0:
                logger.warning(f"⚠ {gene_error_count} gene records have validation errors")
                self.warnings.append(f"Staging genes with errors: {gene_error_count}")

            # Check version record has counts
            cursor.execute(
                "SELECT num_screens, num_genes, status FROM data_load_version WHERE version_id = %s",
                (version_id,)
            )
            version_info = cursor.fetchone()
            if version_info['status'] != 'valid':
                logger.warning(f"⚠ Version status is '{version_info['status']}', not 'valid'")
                self.warnings.append(f"Version status: {version_info['status']}")
            else:
                logger.info(f"✓ Version status is 'valid'")
                self.checks_passed += 1

            return all_ok

        except Exception as e:
            logger.error(f"✗ Error checking staging data: {e}")
            self.checks_failed += 1
            return False

    def check_no_existing_etl_data(self) -> bool:
        """Check if ETL has already been run (to avoid duplicates)."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM screen WHERE is_current = TRUE")
            count = cursor.fetchone()['cnt']
            if count > 0:
                logger.warning(f"⚠ Found {count:,} existing 'current' screen records. ETL may have already run.")
                self.warnings.append("ETL appears to have already executed")
                return False

            logger.info("✓ No existing ETL data found (clean slate)")
            self.checks_passed += 1
            return True
        except Exception as e:
            logger.error(f"✗ Error checking for existing ETL data: {e}")
            self.checks_failed += 1
            return False

    def validate(self) -> bool:
        """Run all validation checks."""
        logger.info("=" * 80)
        logger.info("ETL PIPELINE READINESS VALIDATION")
        logger.info("=" * 80)

        if not self.connect():
            return False

        logger.info("\nChecking schema...")
        self.check_schema_tables()
        self.check_etl_functions()

        logger.info("\nChecking staging data...")
        self.check_staging_data()

        logger.info("\nChecking for existing ETL data...")
        self.check_no_existing_etl_data()

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Checks passed: {self.checks_passed}")
        logger.info(f"Checks failed: {self.checks_failed}")

        if self.warnings:
            logger.info("\nWarnings:")
            for warning in self.warnings:
                logger.warning(f"  - {warning}")

        is_ready = self.checks_failed == 0

        if is_ready:
            logger.info("\n✓ ETL PIPELINE IS READY TO RUN")
        else:
            logger.error("\n✗ ETL PIPELINE IS NOT READY")
            logger.error("  Fix the errors above before running the ETL pipeline")

        logger.info("=" * 80)
        return is_ready

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


def main():
    validator = ETLReadinessValidator()
    try:
        is_ready = validator.validate()
        return 0 if is_ready else 1
    finally:
        validator.close()


if __name__ == '__main__':
    sys.exit(main())
