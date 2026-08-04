#!/bin/bash
#SBATCH --job-name=reticle-context
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=23:00:00
#SBATCH --partition=general-cpu
# Notes:
# - CPU job (D8). Contextual convergence re-runs the same sparse Hᵀ·H + vectorized
#   hypergeometric math as D6, once per facet-value bucket (assay_domain/
#   cell_line/cell_type/condition/phenotype) instead of once globally — same
#   memory profile as reticle-cohit.sh, no GPU.
# - Do NOT hardcode --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides.
#
# D8 contextual convergence (Channel 4). Prereqs: P3 (dim_screen_context) and an
# accepted relatedness_config (D3). Composes with D5/D6/D7: fills
# fact_gene_pair.context_* + dim_gene_pair_context without touching other channels.
#
# Usage:
#   sbatch reticle-context.sh 7 --config-id 2
#   sbatch reticle-context.sh 7 --config-id 2 --context-types assay_domain,cell_line --dry-run
#
# Requires ~/.pgpass. DATA_DIR is NOT needed (reads only the warehouse).

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--config-id N | --label L] [--context-types t1,t2] [--dry-run]"
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
exec 1>"$LOG_DIR/reticle-context-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-context-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Contextual convergence (D8)${NC}"
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
echo -e "${BLUE}[RUN]${NC} compute_contextual.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
run_with_heartbeat "compute_contextual.py" python3 compute_contextual.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ CONTEXTUAL CONVERGENCE COMPLETED${NC}"
else
    echo -e "${RED}✗ CONTEXTUAL CONVERGENCE FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
