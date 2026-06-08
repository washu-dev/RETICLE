#!/bin/bash
# Environment setup for RETICLE ETL - CPU variant
# Load required modules and activate conda environment

set -e

echo "Setting up environment..."

# Load common modules (adjust for your cluster)
# module load gcc/11.2.0
# module load openmpi/4.1.2

# Load Python environment - OPTION 1: Conda
if command -v conda &> /dev/null; then
    echo "  Loading conda environment..."
    conda activate reticle-etl 2>/dev/null || {
        echo "  Creating conda environment..."
        conda create -y -n reticle-etl python=3.11 \
            pandas numpy psycopg2-binary \
            -c conda-forge
        conda activate reticle-etl
    }
else
    echo "  Conda not found, using system Python"
fi

# Verify required packages
python3 << 'PYTHON'
import sys

packages = {
    'pandas': 'Data deduplication',
    'numpy': 'Numerical computing',
    'psycopg2': 'PostgreSQL driver'
}

missing = []
for pkg, desc in packages.items():
    try:
        __import__(pkg)
        print(f"  ✓ {pkg}: {desc}")
    except ImportError:
        print(f"  ✗ {pkg}: {desc}")
        missing.append(pkg)

if missing:
    print(f"\nError: Missing packages: {', '.join(missing)}")
    print(f"Install with: pip install {' '.join(missing)}")
    sys.exit(1)
PYTHON

# Verify .pgpass exists and has correct permissions
echo ""
echo "Checking PostgreSQL credentials (.pgpass)..."
if [ ! -f ~/.pgpass ]; then
    echo "  ✗ .pgpass not found in home directory"
    echo "    Create it with: cat > ~/.pgpass <<'EOF'"
    echo "    your.postgres.host:5432:reticle_biogrid:reticle_admin:PASSWORD"
    echo "    EOF"
    echo "    Then: chmod 600 ~/.pgpass"
    exit 1
fi

# Check permissions (must be exactly 600 / -rw-------)
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    echo "  ✗ .pgpass has incorrect permissions: $PGPASS_PERMS (must be 600)"
    echo "    Fix with: chmod 600 ~/.pgpass"
    exit 1
fi
echo "  ✓ .pgpass found with correct permissions (600)"

echo ""
echo "✓ Environment ready"
