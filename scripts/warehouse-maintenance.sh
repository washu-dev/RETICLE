#!/bin/bash
#
# RETICLE Data Warehouse Maintenance Script
#
# Manage data warehouse versioning, purging, and rollback
#
# Usage:
#   ./warehouse-maintenance.sh --list-versions
#   ./warehouse-maintenance.sh --show-storage
#   ./warehouse-maintenance.sh --show-etl-history
#   ./warehouse-maintenance.sh --purge-version 1
#   ./warehouse-maintenance.sh --purge-old
#   ./warehouse-maintenance.sh --promote-version 2
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

# Check arguments
if [ $# -lt 1 ]; then
    log_error "Usage: $0 <operation> [options]"
    echo ""
    echo "Operations:"
    echo "  --list-versions              List all data versions"
    echo "  --show-storage               Show storage usage per version"
    echo "  --show-etl-history           Show ETL pipeline run history"
    echo "  --estimate-purge VERSION_ID  Estimate space freed by purge"
    echo "  --purge-version VERSION_ID   Purge a specific version"
    echo "  --purge-old                  Purge all old versions"
    echo "  --promote-version VERSION_ID Promote version back to current"
    echo ""
    echo "Options:"
    echo "  --no-confirm                 Skip confirmation prompts"
    echo ""
    echo "Examples:"
    echo "  $0 --list-versions"
    echo "  $0 --show-storage"
    echo "  $0 --purge-old"
    echo "  $0 --promote-version 2"
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

# Build and execute command
CMD="python3 maintenance.py $@"

log_info "Executing: $CMD"
echo ""

eval "$CMD"

exit $?
