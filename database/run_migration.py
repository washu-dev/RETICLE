#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply database migrations to RETICLE database.

Usage:
    python run_migration.py migrations/010_add_etl_progress_tracking.sql
    python run_migration.py migrations/0009_versioned_data_warehouse.sql
"""

import sys
import os

# Add scripts directory to path for config import
script_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.join(os.path.dirname(script_dir), 'scripts')
sys.path.insert(0, scripts_dir)

from config import Config
import psycopg2
import psycopg2.extensions


def apply_migration(migration_path):
    """Apply a single migration file."""
    migration_file = os.path.abspath(migration_path)

    if not os.path.exists(migration_file):
        print("✗ Migration file not found: {}".format(migration_file))
        return False

    if not migration_file.endswith('.sql'):
        print("✗ Migration file must be .sql: {}".format(migration_file))
        return False

    print("Applying migration: {}".format(os.path.basename(migration_file)))
    print("  Path: {}".format(migration_file))

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

        print("✓ Migration applied successfully: {}".format(os.path.basename(migration_file)))
        return True

    except psycopg2.Error as e:
        print("✗ Database error: {}".format(e))
        return False
    except Exception as e:
        print("✗ Error: {}".format(e))
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
