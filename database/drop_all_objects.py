#!/usr/bin/env python3
"""
Drop ALL RETICLE database objects for a clean start.

WARNING: This is destructive. All data will be permanently deleted.

Usage:
  python3 drop_all_objects.py --confirm

Run from: database/ folder
  cd database && python3 drop_all_objects.py --confirm
"""

import argparse
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
import sys
from pathlib import Path

# Add scripts folder to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from config import Config

def drop_all_objects():
    """Drop all RETICLE database objects."""

    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            sslmode='require',
            gssencmode='disable'
        )
        cursor = conn.cursor()
        print("✓ Connected to database")

        # Get list of all tables
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\nFound {len(tables)} tables to drop:")
        for table in tables:
            print(f"  - {table}")

        # Drop all tables (CASCADE removes dependent objects)
        if tables:
            print("\nDropping tables...")
            for table in tables:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                    print(f"  ✓ Dropped {table}")
                except Exception as e:
                    print(f"  ⚠ Error dropping {table}: {e}")
            conn.commit()

        # Get list of all functions
        cursor.execute("""
            SELECT routine_name, routine_type
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            ORDER BY routine_name
        """)
        functions = cursor.fetchall()
        print(f"\nFound {len(functions)} functions/procedures:")
        for func_name, func_type in functions:
            print(f"  - {func_name} ({func_type})")

        # Drop all functions
        if functions:
            print("\nDropping functions...")
            for func_name, func_type in functions:
                try:
                    if func_type == 'FUNCTION':
                        # Functions need signature, try to get it
                        cursor.execute(f"DROP FUNCTION IF EXISTS {func_name} CASCADE")
                    else:
                        cursor.execute(f"DROP PROCEDURE IF EXISTS {func_name} CASCADE")
                    print(f"  ✓ Dropped {func_name}")
                except Exception as e:
                    print(f"  ⚠ Error dropping {func_name}: {e}")
            conn.commit()

        # Get list of all views
        cursor.execute("""
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        views = [row[0] for row in cursor.fetchall()]
        print(f"\nFound {len(views)} views:")
        for view in views:
            print(f"  - {view}")

        # Drop all views
        if views:
            print("\nDropping views...")
            for view in views:
                try:
                    cursor.execute(f"DROP VIEW IF EXISTS {view} CASCADE")
                    print(f"  ✓ Dropped {view}")
                except Exception as e:
                    print(f"  ⚠ Error dropping {view}: {e}")
            conn.commit()

        # Get list of all sequences
        cursor.execute("""
            SELECT sequence_name
            FROM information_schema.sequences
            WHERE sequence_schema = 'public'
            ORDER BY sequence_name
        """)
        sequences = [row[0] for row in cursor.fetchall()]
        print(f"\nFound {len(sequences)} sequences:")
        for seq in sequences:
            print(f"  - {seq}")

        # Drop all sequences
        if sequences:
            print("\nDropping sequences...")
            for seq in sequences:
                try:
                    cursor.execute(f"DROP SEQUENCE IF EXISTS {seq} CASCADE")
                    print(f"  ✓ Dropped {seq}")
                except Exception as e:
                    print(f"  ⚠ Error dropping {seq}: {e}")
            conn.commit()

        # Get list of all indexes
        cursor.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY indexname
        """)
        indexes = [row[0] for row in cursor.fetchall()]
        print(f"\nFound {len(indexes)} indexes:")
        for idx in indexes:
            print(f"  - {idx}")

        # Drop all indexes
        if indexes:
            print("\nDropping indexes...")
            for idx in indexes:
                try:
                    cursor.execute(f"DROP INDEX IF EXISTS {idx} CASCADE")
                    print(f"  ✓ Dropped {idx}")
                except Exception as e:
                    print(f"  ⚠ Error dropping {idx}: {e}")
            conn.commit()

        print("\n" + "="*80)
        print("✓ ALL RETICLE DATABASE OBJECTS DROPPED")
        print("="*80)
        print("\nNext steps:")
        print("  1. Apply migrations: for f in migrations/000[1-3]_*.sql; do psql ... < $f; done")
        print("  2. python3 scripts/staging_loader.py --organism homo_sapiens")
        print("  3. ./slurm/submit-etl-job.sh <version_id>")

        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Drop all RETICLE database objects (DESTRUCTIVE)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
WARNING: This will permanently delete ALL data in the RETICLE schema.

Usage:
  cd database && python3 drop_all_objects.py --confirm

The --confirm flag is required to prevent accidental data loss.
        """
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        required=True,
        help='Confirm that you want to drop all objects (required safety flag)'
    )

    args = parser.parse_args()

    if not drop_all_objects():
        sys.exit(1)


if __name__ == '__main__':
    main()
