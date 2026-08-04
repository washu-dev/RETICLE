#!/bin/bash
#SBATCH --job-name=reticle-cohit
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=23:00:00
#SBATCH --partition=general-cpu
# Notes:
# - CPU job (D6). Co-hit enrichment is exact sparse Hᵀ·H over selective-gene hit
#   sets + vectorized hypergeometric p — cheap, no GPU. Memory covers the sparse
#   co-occurrence matrix (tens of millions of nonzeros possible).
# - Do NOT hardcode --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides.
#
# D6 co-hit (Channel 2). Prereq: an accepted relatedness_config (D3) for the
# version (pass --config-id/--label to target a specific one). Composes with D5:
# fills fact_gene_pair.cohit_* without touching coess_*.
#
# Usage:
#   sbatch reticle-cohit.sh 7 --config-id 2
#   sbatch reticle-cohit.sh 7 --config-id 2 --dry-run
#
# Requires ~/.pgpass. DATA_DIR is NOT needed (reads only the warehouse).

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--config-id N | --label L] [--min-cohit K] [--dry-run]"
    exit 1
fi
VERSION="$1"; shift
if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: version_id must be a number, got: $VERSION"; exit 1
fi
EXTRA_ARGS=("$@")

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
SCRIPTS_DIR="$RETICLE_DIR/scripts"
export LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
exec 1>"$LOG_DIR/reticle-cohit-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-cohit-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Co-hit enrichment (D6)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo ""

echo -e "${BLUE}[SETUP]${NC} Loading environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi
source "$RETICLE_DIR/slurm/heartbeat.sh"

if [ ! -f ~/.pgpass ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass not found (see slurm/PGPASS_SETUP.md)"; exit 1
fi
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass permissions $PGPASS_PERMS (must be 600): chmod 600 ~/.pgpass"; exit 1
fi

cd "$SCRIPTS_DIR"
START_TIME=$(date +%s)
echo -e "${BLUE}[RUN]${NC} compute_cohit.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
run_with_heartbeat "compute_cohit.py" python3 compute_cohit.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ CO-HIT COMPLETED${NC}"
else
    echo -e "${RED}✗ CO-HIT FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
