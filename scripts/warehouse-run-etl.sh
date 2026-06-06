#!/bin/bash
#
# RETICLE ETL Pipeline Runner
#
# Executes the complete ETL pipeline on a versioned data load
#
# Usage:
#   ./warehouse-run-etl.sh 1
#   ./warehouse-run-etl.sh 2 --pipeline-version 1.0.0
#   ./warehouse-run-etl.sh 3 --show-info
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

function log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

function log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check arguments
if [ $# -lt 1 ]; then
    log_error "Usage: $0 <version_id> [options]"
    echo ""
    echo "Arguments:"
    echo "  version_id      Version ID to process (required)"
    echo ""
    echo "Options:"
    echo "  --show-info           Show version info before running"
    echo "  --pipeline-version    Pipeline version string (default: from config)"
    echo ""
    echo "Examples:"
    echo "  $0 1"
    echo "  $0 2 --show-info"
    echo "  $0 3 --pipeline-version 1.0.0"
    exit 1
fi

VERSION_ID="$1"
shift

# Validate version ID is numeric
if ! [[ "$VERSION_ID" =~ ^[0-9]+$ ]]; then
    log_error "Version ID must be a number, got: $VERSION_ID"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "python3 not found"
    exit 1
fi

# Check if virtual environment is active
if [ -z "$VIRTUAL_ENV" ]; then
    log_warn "No virtual environment detected"
    log_info "Attempting to activate reticle environment..."

    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif conda info --envlist | grep -q "reticle"; then
        conda activate reticle
    else
        log_warn "Could not auto-activate environment, proceeding anyway..."
    fi
fi

# Build command
CMD="python3 run_etl_pipeline.py --version $VERSION_ID $@"

log_step "Starting ETL pipeline for version $VERSION_ID"
log_info "Command: $CMD"
echo ""

# Execute
eval "$CMD"

EXIT_CODE=$?

echo ""

if [ $EXIT_CODE -eq 0 ]; then
    log_info "ETL pipeline completed successfully"
    log_info "Next step: Run './warehouse-maintenance.sh --show-storage' to verify"
else
    log_error "ETL pipeline failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
