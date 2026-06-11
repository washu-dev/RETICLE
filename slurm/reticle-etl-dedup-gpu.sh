#!/bin/bash
#SBATCH --job-name=reticle-etl-dedup-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --gres=gpu:1
#SBATCH --output=%x-%j.out
#SBATCH --partition=gpu
#SBATCH --account=${RETICLE_ACCOUNT}
# Note: --partition can be overridden via sbatch --partition= or wrapper sets it
# Note: --account can be set via sbatch --account= or RETICLE_ACCOUNT env var
# Note: Log files will be created in LOG_DIR (set below via environment variable)

# RETICLE ETL Pipeline - Phase 1: GPU Deduplication Only
#
# Usage:
#   sbatch reticle-etl-dedup-gpu.sh
#   sbatch --gres=gpu:2 reticle-etl-dedup-gpu.sh  (use 2 GPUs)
#
# Requirements:
#   - NVIDIA GPU with CUDA support
#   - RAPIDS/cuDF installed (falls back to CPU pandas if unavailable)
#   - See env-setup-gpu.sh for environment configuration
#
# Output:
#   - CSV files in /tmp/reticle_staging/
#   - Metadata in dedup_metadata_v{VERSION_ID}.json
#   - These files are consumed by Phase 2 (cpu_etl_load_only.py)

set -e

VERSION_ID=${VERSION_ID:-2}

# Directory configuration
# RETICLE_DIR can be set via: export RETICLE_DIR=/path/to/reticle
# or passed via SLURM: sbatch --export=RETICLE_DIR=/path/to/reticle
# Default: auto-detect from script location (fallback)
if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi

SCRIPTS_DIR="$RETICLE_DIR/scripts"
LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Redirect SLURM output to LOG_DIR
exec 1>"$LOG_DIR/reticle-etl-dedup-gpu-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-etl-dedup-gpu-${SLURM_JOB_ID}.err"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE ETL Pipeline - Phase 1${NC}"
echo -e "${BLUE}GPU Deduplication Only${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "SLURM Job ID:     $SLURM_JOB_ID"
echo "Node:             $SLURM_NODENAME"
echo "GPUs Allocated:   $SLURM_GPUS"
echo "CPUs per task:    $SLURM_CPUS_PER_TASK"
echo "Memory:           $SLURM_MEM_PER_NODE MB"
echo "Version ID:       $VERSION_ID"
echo ""

# Load GPU environment
echo -e "${BLUE}[SETUP]${NC} Loading GPU environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup-gpu.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup-gpu.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup-gpu.sh not found"
fi

# Verify GPU access
echo -e "${BLUE}[CHECK]${NC} Verifying GPU availability..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || {
    echo -e "${YELLOW}[WARN]${NC} GPU not accessible (will fall back to CPU)"
}
echo ""

# Verify RAPIDS (optional, falls back to pandas)
echo -e "${BLUE}[CHECK]${NC} Checking RAPIDS availability..."
python3 << 'PYTHON'
try:
    import cudf
    import cupy as cp
    print(f"✓ cuDF version: {cudf.__version__}")
    print(f"✓ CuPy version: {cp.__version__}")
except ImportError:
    print("⚠ RAPIDS not available (will use CPU pandas for dedup)")
PYTHON

# Change to scripts directory
cd "$SCRIPTS_DIR"

# Validate database connection
echo -e "${BLUE}[SETUP]${NC} Validating database connection..."
python3 << 'PYTHON'
import sys
from config import Config
import psycopg2

try:
    params = Config.get_psycopg2_params()
    params['sslmode'] = 'require'
    params['connect_timeout'] = 5
    conn = psycopg2.connect(**params)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM staging_screen")
    count = cursor.fetchone()[0]
    print(f"✓ Database connected ({count} screens in staging)")
    conn.close()
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    sys.exit(1)
PYTHON

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Database validation failed"
    exit 1
fi

echo ""

# Create output directory for CSV files
mkdir -p /tmp/reticle_staging

# Start timer
START_TIME=$(date +%s)

# Run GPU dedup phase
echo -e "${BLUE}[RUN]${NC} Starting GPU deduplication phase..."
echo ""

python3 gpu_etl_dedup_only.py \
    --version "$VERSION_ID"

ETL_EXIT_CODE=$?

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $ETL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ GPU DEDUP PHASE COMPLETED${NC}"
    echo ""
    echo "Next Step: Run Phase 2 (CPU Load)"
    echo "  ./submit-etl-job-split.sh $VERSION_ID --cpu"
    echo ""
    echo "Or directly:"
    echo "  cd $SCRIPTS_DIR"
    echo "  python3 cpu_etl_load_only.py --version $VERSION_ID"
else
    echo -e "${RED}✗ GPU DEDUP PHASE FAILED${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo "Total Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo "Job ID:         $SLURM_JOB_ID"
echo ""

exit $ETL_EXIT_CODE
