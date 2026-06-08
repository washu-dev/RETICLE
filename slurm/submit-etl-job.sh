#!/bin/bash
#
# Helper script to submit RETICLE ETL jobs to SLURM
#
# Usage:
#   ./submit-etl-job.sh 2                        # CPU mode, default (8 cores)
#   ./submit-etl-job.sh 2 --cores 16             # CPU mode, 16 cores
#   ./submit-etl-job.sh 2 --gpu                  # GPU mode
#   ./submit-etl-job.sh 2 --gpu --gpus 2         # GPU mode, 2 GPUs
#   ./submit-etl-job.sh 2 --time 1:00:00         # Custom time limit
#   ./submit-etl-job.sh 2 --partition fast       # Custom partition
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RETICLE_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

function log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

function log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

function usage() {
    cat << EOF
Usage: $0 <version_id> [options]

Options:
  --cores N          Number of CPU cores (default: 8)
  --mem MB           Memory in GB (default: auto = 4GB per core)
  --gpu              Use GPU mode (requires RAPIDS)
  --gpus N           Number of GPUs (default: 1, only with --gpu)
  --time HH:MM:SS    Time limit (default: 30 min for CPU, 15 min for GPU)
  --partition NAME   SLURM partition (default: cpu or gpu)
  --help             Show this help

Examples:
  $0 2                               # CPU, 8 cores, 30 minutes
  $0 2 --cores 32 --mem 128          # CPU, 32 cores, 128GB RAM
  $0 2 --gpu                         # GPU, 1 GPU, 15 minutes
  $0 2 --gpu --gpus 2 --time 00:30:00  # GPU, 2 GPUs, 30 minutes
EOF
    exit 1
}

# Parse arguments
if [ $# -lt 1 ]; then
    usage
fi

VERSION_ID=$1
shift

# Defaults
MODE="cpu"
CORES=8
GPUS=0
TIME_LIMIT="00:30:00"
PARTITION="cpu"
MEM_AUTO=true
MEM=""

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --cores)
            CORES=$2
            shift 2
            ;;
        --mem)
            MEM=$2
            MEM_AUTO=false
            shift 2
            ;;
        --gpu)
            MODE="gpu"
            PARTITION="gpu"
            TIME_LIMIT="00:15:00"
            CORES=16
            GPUS=1
            shift
            ;;
        --gpus)
            GPUS=$2
            shift 2
            ;;
        --time)
            TIME_LIMIT=$2
            shift 2
            ;;
        --partition)
            PARTITION=$2
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate version ID
if ! [[ "$VERSION_ID" =~ ^[0-9]+$ ]]; then
    log_error "Version ID must be a number"
    exit 1
fi

# Validate .pgpass exists and has correct permissions
if [ ! -f ~/.pgpass ]; then
    log_error ".pgpass not found in home directory"
    echo ""
    echo "Create it with:"
    echo "  cat > ~/.pgpass <<'EOF'"
    echo "  your.postgres.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD"
    echo "  EOF"
    echo ""
    echo "Then set permissions:"
    echo "  chmod 600 ~/.pgpass"
    echo ""
    echo "For detailed setup instructions, see: slurm/PGPASS_SETUP.md"
    exit 1
fi

# Check permissions (must be 600)
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    log_error ".pgpass has incorrect permissions: $PGPASS_PERMS (must be 600)"
    echo "Fix with: chmod 600 ~/.pgpass"
    exit 1
fi

# Calculate memory if not specified
if [ "$MEM_AUTO" = true ]; then
    MEM=$((CORES * 4))  # 4GB per core
fi

# Build SBATCH arguments
SBATCH_ARGS=()
SBATCH_ARGS+=("--cpus-per-task=$CORES")
SBATCH_ARGS+=("--mem=${MEM}G")
SBATCH_ARGS+=("--time=$TIME_LIMIT")
SBATCH_ARGS+=("--partition=$PARTITION")

if [ "$MODE" = "gpu" ]; then
    SBATCH_ARGS+=("--gres=gpu:$GPUS")
    JOB_SCRIPT="reticle-etl-gpu.sh"
else
    JOB_SCRIPT="reticle-etl.sh"
fi

# Create logs directory
mkdir -p "$RETICLE_DIR/logs"

# Show configuration
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE ETL Job Configuration${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Version ID:       $VERSION_ID"
echo "Mode:             $(echo $MODE | tr 'a-z' 'A-Z')"
echo "Cores:            $CORES"
echo "Memory:           ${MEM}G"
if [ "$MODE" = "gpu" ]; then
    echo "GPUs:             $GPUS"
fi
echo "Time Limit:       $TIME_LIMIT"
echo "Partition:        $PARTITION"
echo "Job Script:       $JOB_SCRIPT"
echo ""

# Submit job
log_step "Submitting SLURM job..."
echo ""

JOB_ID=$(sbatch "${SBATCH_ARGS[@]}" \
    --export=VERSION_ID="$VERSION_ID",NUM_THREADS="$CORES" \
    "$SCRIPT_DIR/$JOB_SCRIPT" | awk '{print $NF}')

echo ""
log_info "Job submitted successfully!"
echo ""
echo "Job ID:           $JOB_ID"
echo "Status:           Check with: squeue -j $JOB_ID"
echo "Output:           $RETICLE_DIR/logs/reticle-etl-$JOB_ID.out"
echo "Error:            $RETICLE_DIR/logs/reticle-etl-$JOB_ID.err"
echo ""
echo -e "${GREEN}Watch output:     tail -f $RETICLE_DIR/logs/reticle-etl-$JOB_ID.out${NC}"
echo -e "${GREEN}Cancel job:       scancel $JOB_ID${NC}"
echo ""

exit 0
