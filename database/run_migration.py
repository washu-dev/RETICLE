#!/usr/bin/env python3
"""
Apply database migrations to RETICLE database.

Usage:
    python run_migration.py migrations/010_add_etl_progress_tracking.sql
    python run_migration.py migrations/0009_versioned_data_warehouse.sql
"""

import sys
import os
from pathlib import Path

# Add scripts directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from config import Config
import psycopg2
import psycopg2.extensions


def apply_migration(migration_path):
    """Apply a single migration file."""
    migration_file = Path(migration_path)

    if not migration_file.exists():
        print(f"✗ Migration file not found: {migration_file}")
        return False

    if not migration_file.suffix == '.sql':
        print(f"✗ Migration file must be .sql: {migration_file}")
        return False

    print(f"Applying migration: {migration_file.name}")
    print(f"  Path: {migration_file.absolute()}")

    try:
        # Read migration SQL
        with open(migration_file, 'r') as f:
            sql = f.read()

        # Connect to database
        print("  Connecting to database...")
        conn = psycopg2.connect(**Config.get_psycopg2_params())
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

        cursor = conn.cursor()

        # Execute migration
        print("  Executing migration...")
        cursor.execute(sql)

        cursor.close()
        conn.close()

        print(f"✓ Migration applied successfully: {migration_file.name}")
        return True

    except psycopg2.Error as e:
        print(f"✗ Database error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    migration_path = sys.argv[1]

    if not apply_migration(migration_path):
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
