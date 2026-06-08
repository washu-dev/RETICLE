#!/bin/bash
# Environment setup for RETICLE ETL - CPU variant
# Creates Python virtual environment and loads required packages
# Works with or without conda (uses venv if conda unavailable)

set -e

echo "Setting up environment..."

# Load Python module (adjust for your cluster if needed)
# WashU C2: python3 (default), python39
module load python3

# Path for virtual environment (in home directory to avoid quota issues)
VENV_HOME="$HOME/.reticle-etl-venv"

# OPTION 1: Use conda if available
if command -v conda &> /dev/null; then
    echo "  Using conda..."
    conda activate reticle-etl 2>/dev/null || {
        echo "  Creating conda environment..."
        conda create -y -n reticle-etl python=3.11 \
            pandas numpy psycopg2-binary python-dotenv \
            -c conda-forge
        conda activate reticle-etl
    }
# OPTION 2: Use Python venv (for clusters without conda)
else
    echo "  Conda not found, using Python venv..."

    if [ ! -d "$VENV_HOME" ]; then
        echo "  Creating virtual environment at $VENV_HOME..."
        python3 -m venv "$VENV_HOME"
    fi

    echo "  Activating virtual environment..."
    source "$VENV_HOME/bin/activate"

    echo "  Installing packages (this may take a minute)..."
    pip install --upgrade pip --quiet
    pip install pandas numpy psycopg2-binary python-dotenv --quiet
fi

# Verify required packages
echo "  Verifying packages..."
python3 << 'PYTHON'
import sys

packages = {
    'pandas': 'Data deduplication',
    'numpy': 'Numerical computing',
    'psycopg2': 'PostgreSQL driver',
    'dotenv': 'Configuration management'
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
