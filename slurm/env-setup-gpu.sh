#!/bin/bash
# Environment setup for RETICLE ETL - GPU variant
# Load CUDA, cuDNN, and RAPIDS

set -e

echo "Setting up GPU environment..."

# Load CUDA module (adjust version for your cluster)
# module load cuda/12.0
# module load cudnn/8.6
# module load nccl/2.16

echo "  Loading CUDA modules..."
# Example for common clusters:
# module load nvidia/cuda/12.0  or
# module load cuda/12.2  or
# . /opt/nvidia/hpc_sdk/linux_x86_64/24.1/compilers/bin/nvc -V

# Verify CUDA
if ! command -v nvidia-smi &> /dev/null; then
    echo "  ⚠ nvidia-smi not found - GPU may not be available"
fi

echo "  Loading RAPIDS conda environment..."
if command -v conda &> /dev/null; then
    conda activate rapids-gpu 2>/dev/null || {
        echo "  Creating RAPIDS environment..."
        echo "  (This may take a few minutes...)"

        # Create environment with RAPIDS
        # Option 1: Using conda-forge (recommended for HPC)
        conda create -y -n rapids-gpu python=3.11 \
            -c nvidia -c conda-forge \
            rapids=24.02 \
            cudf \
            cupy \
            psycopg2-binary \
            pandas \
            numpy

        conda activate rapids-gpu
    }
else
    echo "  ✗ Conda not found - cannot set up RAPIDS"
    exit 1
fi

# Verify RAPIDS and GPU
echo "  Verifying RAPIDS installation..."
python3 << 'PYTHON'
import sys

print("Checking RAPIDS packages...")
packages = {
    'cudf': 'GPU DataFrame',
    'cupy': 'GPU Array',
    'psycopg2': 'PostgreSQL',
    'pandas': 'CPU fallback'
}

for pkg, desc in packages.items():
    try:
        mod = __import__(pkg)
        print(f"  ✓ {pkg}: {desc}")
    except ImportError:
        print(f"  ✗ {pkg}: {desc}")
        sys.exit(1)

# Check GPU access
try:
    import cupy as cp
    gpu_name = cp.cuda.runtime.getDeviceProperties(0)['name']
    print(f"  ✓ GPU accessible: {gpu_name}")
except Exception as e:
    print(f"  ✗ GPU access failed: {e}")
    sys.exit(1)

print("\n✓ GPU environment ready")
PYTHON

if [ $? -ne 0 ]; then
    echo "✗ GPU environment setup failed"
    exit 1
fi

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
echo "✓ GPU environment ready"
