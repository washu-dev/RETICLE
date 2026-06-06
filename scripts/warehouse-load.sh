#!/bin/bash
#
# RETICLE Data Warehouse Load Script
#
# Simple wrapper to load JSON/TSV data into staging tables
#
# Usage:
#   ./warehouse-load.sh homo_sapiens
#   ./warehouse-load.sh mus_musculus "Description of the load"
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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
    log_error "Usage: $0 <organism> [description]"
    echo ""
    echo "Arguments:"
    echo "  organism        homo_sapiens or mus_musculus (required)"
    echo "  description     Custom description for this load (optional)"
    echo ""
    echo "Examples:"
    echo "  $0 homo_sapiens"
    echo "  $0 mus_musculus 'Human data v2 - fixed gene names'"
    exit 1
fi

ORGANISM="$1"
DESCRIPTION="${2:-Auto-loaded $ORGANISM data}"

# Validate organism
case "$ORGANISM" in
    homo_sapiens|mus_musculus)
        log_info "Loading $ORGANISM data"
        ;;
    *)
        log_error "Unknown organism: $ORGANISM (must be homo_sapiens or mus_musculus)"
        exit 1
        ;;
esac

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "python3 not found"
    exit 1
fi

# Run the loader
log_info "Starting staging data loader..."
echo ""

python3 staging_loader.py \
    --organism "$ORGANISM" \
    --description "$DESCRIPTION"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    log_info "Staging load completed successfully"
    log_info "Next step: Run ./warehouse-run-etl.sh <version_id>"
else
    log_error "Staging load failed (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
