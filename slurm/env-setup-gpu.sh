#!/bin/bash
# Environment setup for RETICLE ETL - GPU variant
# Load CUDA, cuDNN, and RAPIDS (or cuDF via pip)
# Works with or without conda
#
# Partition & Account Configuration:
#   Partition: Set via RETICLE_PARTITION_GPU env var or sbatch --partition=
#   Account:   Set via RETICLE_ACCOUNT env var or sbatch --account=

set -e

echo "Setting up GPU environment..."

# Load Python module
# WashU C2: python3 (default)
module load python3

# Load CUDA module if available (adjust for your cluster)
# WashU C2: check with 'module avail cuda'
# Common options: cuda/11.8, cuda/12.0, cuda/12.2
# If your cluster doesn't have CUDA module, you may need:
# - export PATH=/usr/local/cuda/bin:$PATH
# - export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
echo "  Loading CUDA modules (if available)..."
module load cuda 2>/dev/null || echo "  ⚠ CUDA module not found (GPU may not work)"

# Verify CUDA
if ! command -v nvidia-smi &> /dev/null; then
    echo "  ⚠ nvidia-smi not found - GPU may not be available"
fi

# Path for virtual environment
VENV_HOME="$HOME/.rapids-gpu-venv"

# OPTION 1: Use conda if available (preferred for RAPIDS)
if command -v conda &> /dev/null; then
    echo "  Using conda for RAPIDS..."
    conda activate rapids-gpu 2>/dev/null || {
        echo "  Creating RAPIDS conda environment..."
        echo "  (This may take a few minutes...)"

        conda create -y -n rapids-gpu python=3.11 \
            -c nvidia -c conda-forge \
            rapids=24.02 \
            cudf \
            cupy \
            psycopg2-binary \
            pandas \
            numpy \
            python-dotenv \
            tqdm
        conda activate rapids-gpu
    }

# OPTION 2: Use Python venv with GPU packages via pip
else
    echo "  Conda not found, using Python venv..."

    if [ ! -d "$VENV_HOME" ]; then
        echo "  Creating virtual environment at $VENV_HOME..."
        python3 -m venv "$VENV_HOME"
    fi

    echo "  Activating virtual environment..."
    source "$VENV_HOME/bin/activate"

    echo "  Installing packages (this may take several minutes)..."
    pip install --upgrade pip --quiet

    # Try to install cuDF (GPU-accelerated pandas)
    echo "  Installing cuDF (GPU-accelerated DataFrame)..."
    pip install cudf-cu12 --quiet 2>/dev/null || {
        echo "  ⚠ cuDF installation failed - GPU acceleration unavailable"
        echo "     Falling back to CPU pandas"
        pip install pandas numpy psycopg2-binary python-dotenv tqdm --quiet
    }

    # Fallback packages if GPU unavailable
    pip install pandas numpy psycopg2-binary python-dotenv tqdm --quiet
fi

# Verify packages
echo "  Verifying packages..."
python3 << 'PYTHON'
import sys

packages = {
    'pandas': 'CPU fallback',
    'psycopg2': 'PostgreSQL',
    'dotenv': 'Configuration management',
    'tqdm': 'Progress reporting',
}

# Try GPU packages, but don't fail if missing
optional = {
    'cudf': 'GPU DataFrame',
    'cupy': 'GPU Array',
}

missing = []
for pkg, desc in packages.items():
    try:
        __import__(pkg)
        print(f"  ✓ {pkg}: {desc}")
    except ImportError:
        print(f"  ✗ {pkg}: {desc}")
        missing.append(pkg)

# Check GPU packages (optional)
gpu_available = False
for pkg, desc in optional.items():
    try:
        mod = __import__(pkg)
        print(f"  ✓ {pkg}: {desc}")
        gpu_available = True
    except ImportError:
        print(f"  ⚠ {pkg}: {desc} (GPU acceleration unavailable)")

if missing:
    print(f"\nError: Missing required packages: {', '.join(missing)}")
    sys.exit(1)

if not gpu_available:
    print("\n⚠ GPU packages not available - using CPU fallback")
    print("  For GPU acceleration, install RAPIDS:")
    print("  conda install -c nvidia -c conda-forge rapids=24.02")

print("")
PYTHON

# Verify .pgpass exists and has correct permissions
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
echo "✓ GPU environment ready"
