#!/bin/bash
#
# HPC ETL Pipeline Runner
# Switches between different ETL implementations based on available resources
#
# Usage:
#   ./run-hpc-etl.sh 2 --threads 16                    # Multi-threaded (CPU)
#   ./run-hpc-etl.sh 2 --gpu                           # GPU-accelerated
#   ./run-hpc-etl.sh 2 --mode sql                      # Original SQL approach
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# Parse arguments
if [ $# -lt 1 ]; then
    log_error "Usage: $0 <version_id> [--threads N|--gpu|--mode sql]"
    echo ""
    echo "Options:"
    echo "  --threads N    Multi-threaded CPU mode (default: 8 threads)"
    echo "  --gpu          GPU-accelerated mode (requires RAPIDS/cuDF)"
    echo "  --mode sql     Original SQL-only mode (slow on large datasets)"
    exit 1
fi

VERSION_ID="$1"
shift

# Defaults
MODE="hpc"
THREADS=8
GPU=false

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --threads)
            THREADS="$2"
            shift 2
            ;;
        --gpu)
            GPU=true
            MODE="gpu"
            shift
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate version ID
if ! [[ "$VERSION_ID" =~ ^[0-9]+$ ]]; then
    log_error "Version ID must be a number"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "python3 not found"
    exit 1
fi

log_step "Starting ETL pipeline for version $VERSION_ID (mode: $MODE, threads: $THREADS)"
echo ""

case $MODE in
    sql)
        log_info "Using original SQL-based pipeline"
        python3 run_etl_pipeline.py --version "$VERSION_ID"
        ;;
    hpc)
        log_info "Using multi-threaded HPC pipeline ($THREADS threads)"
        python3 hpc_etl_pipeline.py --version "$VERSION_ID" --threads "$THREADS"
        ;;
    gpu)
        log_info "Using GPU-accelerated pipeline"
        python3 hpc_etl_gpu.py --version "$VERSION_ID" --threads "$THREADS"
        ;;
    *)
        log_error "Unknown mode: $MODE"
        exit 1
        ;;
esac

EXIT_CODE=$?

echo ""

if [ $EXIT_CODE -eq 0 ]; then
    log_info "✓ ETL pipeline completed successfully"
else
    log_error "✗ ETL pipeline failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
