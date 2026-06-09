#!/bin/bash
#
# Helper script to submit RETICLE split ETL jobs (Phase 1: GPU, Phase 2: CPU)
#
# Usage:
#   ./submit-etl-job-split.sh 2                        # Submit Phase 1 only (GPU dedup)
#   ./submit-etl-job-split.sh 2 --both                 # Submit both phases (GPU then CPU)
#   ./submit-etl-job-split.sh 2 --cpu                  # Submit Phase 2 only (CPU load)
#   ./submit-etl-job-split.sh 2 --gpu-time 00:10:00    # Phase 1 with custom time limit
#   ./submit-etl-job-split.sh 2 --cpu-time 00:30:00    # Phase 2 with custom time limit
#

set -e

# Get RETICLE_DIR from environment or auto-detect
if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi

SCRIPT_DIR="$RETICLE_DIR/slurm"

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
  --gpu                 Submit only Phase 1 (GPU dedup) [default]
  --cpu                 Submit only Phase 2 (CPU load)
  --both                Submit both phases sequentially
  --gpu-time HH:MM:SS   Time limit for Phase 1 (default: 5 min)
  --gpu-gpus N          Number of GPUs for Phase 1 (default: 1)
  --gpu-cores N         CPU cores for Phase 1 (default: 8)
  --cpu-time HH:MM:SS   Time limit for Phase 2 (default: 1 hour)
  --cpu-cores N         CPU cores for Phase 2 (default: 8)
  --partition NAME      SLURM partition (overrides defaults)
  --help                Show this help

Environment Variables:
  RETICLE_PARTITION_CPU   Default partition for CPU jobs (default: cpu)
  RETICLE_PARTITION_GPU   Default partition for GPU jobs (default: gpu)

Examples:
  $0 2                                    # Phase 1: GPU dedup only
  $0 2 --both                             # Phases 1 & 2 (chained)
  $0 2 --gpu --gpu-time 00:10:00          # Phase 1 with 10 min timeout
  $0 2 --cpu                              # Phase 2: Load only (manual phase 1)

Performance Expectations:
  Phase 1 (GPU dedup):  ~30 seconds on A100, ~5 min reserved
  Phase 2 (CPU load):   ~30 seconds on fast node, ~1 hour reserved

  Total GPU time: Only ~30 seconds (vs 30 min in unified pipeline)
  Significant cost savings on expensive GPU resources.
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
MODE="gpu"
GPU_TIME_LIMIT="00:05:00"
GPU_GPUS=1
GPU_CORES=8
GPU_PARTITION=${RETICLE_PARTITION_GPU:-gpu}

CPU_TIME_LIMIT="01:00:00"
CPU_CORES=8
CPU_PARTITION=${RETICLE_PARTITION_CPU:-cpu}

# HPC Accounting (set RETICLE_ACCOUNT for proper billing)
ACCOUNT="${RETICLE_ACCOUNT:-}"

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu)
            MODE="gpu"
            shift
            ;;
        --cpu)
            MODE="cpu"
            shift
            ;;
        --both)
            MODE="both"
            shift
            ;;
        --gpu-time)
            GPU_TIME_LIMIT=$2
            shift 2
            ;;
        --gpu-gpus)
            GPU_GPUS=$2
            shift 2
            ;;
        --gpu-cores)
            GPU_CORES=$2
            shift 2
            ;;
        --cpu-time)
            CPU_TIME_LIMIT=$2
            shift 2
            ;;
        --cpu-cores)
            CPU_CORES=$2
            shift 2
            ;;
        --partition)
            GPU_PARTITION=$2
            CPU_PARTITION=$2
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
    exit 1
fi

# Check permissions (must be 600)
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    log_error ".pgpass has incorrect permissions: $PGPASS_PERMS (must be 600)"
    echo "Fix with: chmod 600 ~/.pgpass"
    exit 1
fi

# Create logs directory
mkdir -p "$RETICLE_DIR/logs"

# Show configuration
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Split ETL Job Configuration${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Version ID:       $VERSION_ID"
echo "Mode:             $(echo $MODE | tr 'a-z' 'A-Z')"
echo ""

# Function to submit Phase 1 (GPU Dedup)
submit_phase1() {
    echo -e "${BLUE}PHASE 1 (GPU Deduplication)${NC}" >&2
    echo "  GPU Cores:        $GPU_CORES" >&2
    echo "  GPUs:             $GPU_GPUS" >&2
    echo "  Time Limit:       $GPU_TIME_LIMIT" >&2
    echo "  Partition:        $GPU_PARTITION" >&2
    echo "" >&2

    log_step "Submitting Phase 1 (GPU Dedup)..." >&2
    echo "" >&2

    GPU_JOB_ID=$(sbatch \
        --cpus-per-task=$GPU_CORES \
        --mem=$((GPU_CORES * 4))G \
        --time=$GPU_TIME_LIMIT \
        --partition=$GPU_PARTITION \
        $([ -n "$ACCOUNT" ] && echo "--account=$ACCOUNT") \
        --gres=gpu:$GPU_GPUS \
        --export=VERSION_ID="$VERSION_ID",RETICLE_DIR="$RETICLE_DIR" \
        "$SCRIPT_DIR/reticle-etl-dedup-gpu.sh" | awk '{print $NF}')

    echo "" >&2
    log_info "Phase 1 submitted successfully!" >&2
    echo "" >&2
    echo "Job ID:           $GPU_JOB_ID" >&2
    echo "Status:           Check with: squeue -j $GPU_JOB_ID" >&2
    echo "Output:           $RETICLE_DIR/logs/reticle-etl-dedup-gpu-$GPU_JOB_ID.out" >&2
    echo "" >&2
    echo -e "${GREEN}Watch output:     tail -f $RETICLE_DIR/logs/reticle-etl-dedup-gpu-$GPU_JOB_ID.out${NC}" >&2
    echo "" >&2

    # Return ONLY the job ID on stdout
    echo "$GPU_JOB_ID"
}

# Function to submit Phase 2 (CPU Load)
submit_phase2() {
    local DEPENDENCY=$1

    if [ -z "$DEPENDENCY" ]; then
        # No dependency: submit immediately
        echo -e "${BLUE}PHASE 2 (CPU Loading)${NC}" >&2
        echo "  CPU Cores:        $CPU_CORES" >&2
        echo "  Time Limit:       $CPU_TIME_LIMIT" >&2
        echo "  Partition:        $CPU_PARTITION" >&2
        echo "  Depends on:       (none - manual submission)" >&2
        echo "" >&2

        log_step "Submitting Phase 2 (CPU Load)..." >&2
        echo "" >&2

        CPU_JOB_ID=$(sbatch \
            --cpus-per-task=$CPU_CORES \
            --mem=$((CPU_CORES * 4))G \
            --time=$CPU_TIME_LIMIT \
            --partition=$CPU_PARTITION \
            $([ -n "$ACCOUNT" ] && echo "--account=$ACCOUNT") \
            --export=VERSION_ID="$VERSION_ID",RETICLE_DIR="$RETICLE_DIR" \
            "$SCRIPT_DIR/reticle-etl-load-cpu.sh" | awk '{print $NF}')
    else
        # With dependency: wait for Phase 1 to complete
        echo -e "${BLUE}PHASE 2 (CPU Loading)${NC}" >&2
        echo "  CPU Cores:        $CPU_CORES" >&2
        echo "  Time Limit:       $CPU_TIME_LIMIT" >&2
        echo "  Partition:        $CPU_PARTITION" >&2
        echo "  Depends on:       Phase 1 (job $DEPENDENCY)" >&2
        echo "" >&2

        log_step "Submitting Phase 2 (CPU Load) with dependency on Phase 1..." >&2
        echo "" >&2

        CPU_JOB_ID=$(sbatch \
            --cpus-per-task=$CPU_CORES \
            --mem=$((CPU_CORES * 4))G \
            --time=$CPU_TIME_LIMIT \
            --partition=$CPU_PARTITION \
            $([ -n "$ACCOUNT" ] && echo "--account=$ACCOUNT") \
            --dependency=afterok:$DEPENDENCY \
            --export=VERSION_ID="$VERSION_ID",RETICLE_DIR="$RETICLE_DIR" \
            "$SCRIPT_DIR/reticle-etl-load-cpu.sh" | awk '{print $NF}')
    fi

    echo "" >&2
    log_info "Phase 2 submitted successfully!" >&2
    echo "" >&2
    echo "Job ID:           $CPU_JOB_ID" >&2
    echo "Status:           Check with: squeue -j $CPU_JOB_ID" >&2
    echo "Output:           $RETICLE_DIR/logs/reticle-etl-load-cpu-$CPU_JOB_ID.out" >&2
    echo "" >&2
    echo -e "${GREEN}Watch output:     tail -f $RETICLE_DIR/logs/reticle-etl-load-cpu-$CPU_JOB_ID.out${NC}" >&2
    echo "" >&2

    # Return ONLY the job ID on stdout
    echo "$CPU_JOB_ID"
}

# Execute based on mode
case $MODE in
    gpu)
        GPU_JOB_ID=$(submit_phase1)
        echo "To run Phase 2 after completion:"
        echo "  $SCRIPT_DIR/submit-etl-job-split.sh $VERSION_ID --cpu"
        echo ""
        ;;
    cpu)
        log_step "Submitting Phase 2 (CPU Load)..."
        echo ""
        echo "Note: Phase 1 (gpu_etl_dedup_only.py) must have completed first."
        echo "If not, the CSV files will not be found and this job will fail."
        echo ""
        CPU_JOB_ID=$(submit_phase2)
        ;;
    both)
        GPU_JOB_ID=$(submit_phase1)
        CPU_JOB_ID=$(submit_phase2 "$GPU_JOB_ID")
        echo ""
        echo -e "${BLUE}========================================${NC}"
        echo -e "${GREEN}BOTH PHASES SUBMITTED${NC}"
        echo -e "${BLUE}========================================${NC}"
        echo ""
        echo "Phase 1 (GPU):    Job $GPU_JOB_ID"
        echo "Phase 2 (CPU):    Job $CPU_JOB_ID"
        echo ""
        echo "Phase 2 will start automatically after Phase 1 completes."
        echo ""
        ;;
esac

exit 0
