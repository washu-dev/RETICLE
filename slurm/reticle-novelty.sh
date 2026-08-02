#!/bin/bash
#SBATCH --job-name=reticle-novelty
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --partition=general-gpu
#SBATCH --gres=gpu:1
# Notes:
# - GPU-capable job (D5b), same masked-GEMM tail-restricted-Spearman machinery
#   as D5, run over the residualized matrix instead of the raw one. Pass --cpu
#   to force CPU/numpy (e.g. off-cluster) — see slurm/env-setup-gpu.sh.
# - Do NOT hardcode --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides.
#
# D5b novelty / mechanistic-divergence (Channel 5). Prereqs: D5 (co-essentiality,
# for the same matrix + optional novelty_score contrast), P3 (dim_screen_context,
# for the additive model's context-group term and the buffering-candidate
# context-anti-correlation check), and dim_gene_paralog (slurm/reticle-paralogs.sh,
# for the buffering-candidate paralog criterion). Composes with D5/D6/D7/D8:
# fills fact_gene_pair.resid_*/novelty_score/is_antagonistic/is_buffering_candidate
# + dim_gene_expectation_model, without touching other channels' columns.
#
# Usage:
#   sbatch reticle-novelty.sh 7 --config-id 2
#   sbatch reticle-novelty.sh 7 --config-id 2 --cpu --dry-run
#
# Requires ~/.pgpass. DATA_DIR/STRING_DIR are NOT needed (reads only the warehouse).

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--config-id N | --label L] [--cpu] [--dry-run]"
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
exec 1>"$LOG_DIR/reticle-novelty-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-novelty-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Novelty / mechanistic-divergence (D5b)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo ""

echo -e "${BLUE}[SETUP]${NC} Loading environment..."
if [[ " ${EXTRA_ARGS[*]} " == *" --cpu "* ]]; then
    if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
        source "$RETICLE_DIR/slurm/env-setup.sh"
    fi
elif [ -f "$RETICLE_DIR/slurm/env-setup-gpu.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup-gpu.sh"
elif [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    echo -e "${YELLOW}[WARN]${NC} env-setup-gpu.sh not found; falling back to env-setup.sh"
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} no env-setup script found; using system python"
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
echo -e "${BLUE}[RUN]${NC} compute_novelty.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
python3 compute_novelty.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ NOVELTY CHANNEL COMPLETED${NC}"
else
    echo -e "${RED}✗ NOVELTY CHANNEL FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
