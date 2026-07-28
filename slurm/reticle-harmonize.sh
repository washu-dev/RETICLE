#!/bin/bash
#SBATCH --job-name=reticle-harmonize
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --partition=general-cpu
# Notes:
# - CPU job by design. Harmonization is I/O-bound (RDS read/write) with trivial
#   per-screen math; a GPU gives no benefit. (The GPU payoff is later, at the
#   co-essentiality matrix stage.)
# - Do NOT hardcode --account; set SBATCH_ACCOUNT (e.g. export SBATCH_ACCOUNT="$RETICLE_ACCOUNT").
#   SBATCH_PARTITION overrides the --partition default above.
#
# P1 harmonization: reads screen_gene_raw + BioGRID metadata JSON, writes
# fact_screen_gene.{harmonized,percentile,robust_z}_score + screen_harmonization.
#
# Usage:
#   sbatch reticle-harmonize.sh 7
#   sbatch reticle-harmonize.sh 7 --dry-run
#   sbatch reticle-harmonize.sh 7 --overrides /path/directionality_overrides.json
#
# Requires DATA_DIR to point at the shared dir holding screen_metadata_*.json
# (the same files the staging loader reads). Resumable: re-running skips screens
# already present in screen_harmonization.

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--dry-run] [--overrides PATH]"
    exit 1
fi
VERSION="$1"; shift
if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: version_id must be a number, got: $VERSION"; exit 1
fi
EXTRA_ARGS=("$@")   # passthrough: --dry-run / --apply-directionality

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
SCRIPTS_DIR="$RETICLE_DIR/scripts"
export LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
exec 1>"$LOG_DIR/reticle-harmonize-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-harmonize-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Harmonization (P1)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo "DATA_DIR:      ${DATA_DIR:-<unset - metadata JSON must be reachable>}"
echo ""

echo -e "${BLUE}[SETUP]${NC} Loading environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi

if [ ! -f ~/.pgpass ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass not found (see slurm/PGPASS_SETUP.md)"; exit 1
fi
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass permissions $PGPASS_PERMS (must be 600): chmod 600 ~/.pgpass"; exit 1
fi

cd "$SCRIPTS_DIR"
START_TIME=$(date +%s)
echo -e "${BLUE}[RUN]${NC} harmonize_warehouse.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
python3 harmonize_warehouse.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ HARMONIZATION COMPLETED${NC}"
else
    echo -e "${RED}✗ HARMONIZATION FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
