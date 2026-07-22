#!/usr/bin/env python3

"""
RETICLE Versioned Data Warehouse Configuration Management

Handles database connection settings, paths, and runtime configuration.
Supports environment variables and .env files.
"""

import os
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    """Database and application configuration."""

    # Database connection
    # Note: DB_PASSWORD should NOT be set. Use ~/.pgpass instead for secure HPC credential storage.
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME', 'reticle_biogrid')
    DB_USER = os.getenv('DB_USER', 'reticle_admin')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')  # Empty: psycopg2 will use ~/.pgpass
    DB_SSL = os.getenv('DB_SSL', 'false').lower() == 'true'

    # Connection pool settings
    POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 5))
    MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 10))
    POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', 30))

    # Data directories
    DATA_DIR = Path(os.getenv('DATA_DIR', '../Domain/Data'))
    STAGING_DIR = DATA_DIR / 'staging'
    BACKUP_DIR = DATA_DIR / 'backups'
    LOG_DIR = Path(os.getenv('LOG_DIR', '../logs'))

    # Staging output directory (for GPU/CPU split pipeline)
    # Must be on shared filesystem if running across multiple HPC nodes
    # Default: /tmp/reticle_staging (works for single-node, fails for multi-node)
    # Set STAGING_DIR to a shared filesystem path for multi-node HPC
    STAGING_OUTPUT_DIR = Path(os.getenv('STAGING_DIR', '/tmp/reticle_staging'))

    # Organisms to process
    ORGANISMS = {
        'homo_sapiens': {
            'json_pattern': 'screen_metadata_homo_sapiens.json',
            'tsv_pattern': 'homo_sapiens/BIOGRID-ORCS-SCREEN_*.screen.tab.txt',
            'description': 'Homo sapiens (human)'
        },
        'mus_musculus': {
            'json_pattern': 'screen_metadata_musculus.json',
            'tsv_pattern': 'mus_musculus/BIOGRID-ORCS-SCREEN_*.screen.tab.txt',
            'description': 'Mus musculus (mouse)'
        }
    }

    # ETL settings
    BATCH_SIZE = int(os.getenv('ETL_BATCH_SIZE', 10000))
    COMMIT_INTERVAL = int(os.getenv('ETL_COMMIT_INTERVAL', 50000))
    PIPELINE_VERSION = os.getenv('PIPELINE_VERSION', '1.0.0')

    # Logging
    # Normalize to upper-case: logging.basicConfig(level=...) only accepts the
    # canonical upper-case level names (e.g. 'DEBUG'), so a lower-case LOG_LEVEL
    # like 'debug' would raise "ValueError: Unknown level: 'debug'".
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Validation
    VALIDATE_ON_LOAD = os.getenv('VALIDATE_ON_LOAD', 'true').lower() == 'true'
    SKIP_INVALID_ROWS = os.getenv('SKIP_INVALID_ROWS', 'true').lower() == 'true'
    MAX_VALIDATION_ERRORS = int(os.getenv('MAX_VALIDATION_ERRORS', 1000))

    @classmethod
    def get_connection_string(cls) -> str:
        """Build SQLAlchemy connection string."""
        if cls.DB_PASSWORD:
            return f"postgresql://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}?gssencmode=disable"
        else:
            return f"postgresql://{cls.DB_USER}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"

    @classmethod
    def get_psycopg2_params(cls) -> dict:
        """Get psycopg2 connection parameters."""
        params = {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'database': cls.DB_NAME,
            'user': cls.DB_USER,
            'connect_timeout': 30,
            'gssencmode': 'disable',  # Disable Kerberos authentication
        }
        if cls.DB_PASSWORD:
            params['password'] = cls.DB_PASSWORD

        # Handle SSL
        if cls.DB_HOST and ('rds.amazonaws.com' in cls.DB_HOST or cls.DB_SSL):
            params['sslmode'] = 'prefer'

        return params

    @classmethod
    def validate(cls) -> Tuple[bool, list]:
        """Validate configuration and return (is_valid, errors)."""
        errors = []

        # Check database connectivity
        if not cls.DB_HOST:
            errors.append('DB_HOST not configured')
        if not cls.DB_USER:
            errors.append('DB_USER not configured')
        if not cls.DB_NAME:
            errors.append('DB_NAME not configured')

        # Check directories
        if not cls.DATA_DIR.exists():
            errors.append(f'DATA_DIR does not exist: {cls.DATA_DIR}')
        if not cls.LOG_DIR.exists():
            cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

        return len(errors) == 0, errors

    @classmethod
    def to_dict(cls) -> dict:
        """Return configuration as dictionary (safe - no passwords)."""
        return {
            'database': {
                'host': cls.DB_HOST,
                'port': cls.DB_PORT,
                'database': cls.DB_NAME,
                'user': cls.DB_USER,
                'ssl': cls.DB_SSL
            },
            'directories': {
                'data': str(cls.DATA_DIR),
                'staging': str(cls.STAGING_DIR),
                'logs': str(cls.LOG_DIR)
            },
            'etl': {
                'batch_size': cls.BATCH_SIZE,
                'commit_interval': cls.COMMIT_INTERVAL,
                'pipeline_version': cls.PIPELINE_VERSION
            }
        }

    @classmethod
    def print_config(cls):
        """Print configuration to console."""
        import json
        print("\n" + "="*80)
        print("RETICLE DATA WAREHOUSE CONFIGURATION")
        print("="*80)
        print(json.dumps(cls.to_dict(), indent=2))
        print("="*80 + "\n")


if __name__ == '__main__':
    # Validate configuration
    is_valid, errors = Config.validate()
    Config.print_config()

    if not is_valid:
        print("⚠️  Configuration validation errors:")
        for error in errors:
            print(f"  - {error}")
        exit(1)
    else:
        print("✓ Configuration valid")
