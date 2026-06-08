#!/bin/bash
#
# RETICLE Database Purge
#
# Drops ALL database objects for a clean slate.
# WARNING: This is destructive and cannot be undone.
#
# Usage:
#   ./warehouse-purge.sh --confirm
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

# Check for confirm flag
if [[ "$1" != "--confirm" ]]; then
    log_error "DESTRUCTIVE OPERATION: This will permanently delete ALL database objects"
    echo ""
    echo -e "${RED}WARNING:${NC} All RETICLE data will be permanently deleted."
    echo ""
    echo "Usage: $0 --confirm"
    echo ""
    echo "If you are sure, run:"
    echo "  $0 --confirm"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "python3 not found"
    exit 1
fi

log_step "PURGING ALL RETICLE DATABASE OBJECTS"
log_warn "THIS IS DESTRUCTIVE AND CANNOT BE UNDONE"
echo ""

# Execute purge
python3 drop_all_objects.py --confirm

EXIT_CODE=$?

echo ""

if [ $EXIT_CODE -eq 0 ]; then
    log_info "Database purge completed successfully"
    log_info "Ready to rebuild schema with: psql < ../database/migrations/0009_versioned_data_warehouse.sql"
else
    log_error "Database purge failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
