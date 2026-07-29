#!/bin/bash
#SBATCH --job-name=reticle-coess
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --gres=gpu:1
#SBATCH --partition=general-gpu
# Notes:
# - GPU job (D5). Tail-restricted Spearman ρ over the selective-gene × FULL-screen
#   percentile matrix via masked GEMMs (cupy). Falls back to CPU/numpy with --cpu
#   (much slower). Memory is high because the dense percentile matrix + tiled
#   block outputs live in host RAM before/after the device.
# - Do NOT hardcode --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides the
#   --partition default. Request more GPUs with `sbatch --gres=gpu:2 ...` if needed.
#
# D5 co-essentiality. Prereq: an ACCEPTED relatedness_config (D3) for the version,
# which needs P1 harmonize (D-... fact_screen_gene.percentile_score) + a profile
# (D2) + configure_relatedness.py --accept.
#
# Usage:
#   sbatch reticle-coessentiality.sh 7 --histogram
#   sbatch reticle-coessentiality.sh 7 --build --rho-min 0.20 --top-k 200
#   sbatch reticle-coessentiality.sh 7 --build --rho-min 0.20 --top-k 200 --dry-run
#
# Requires ~/.pgpass. DATA_DIR is NOT needed (reads only the warehouse).

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> (--histogram | --build [--rho-min X --top-k K]) [--dry-run] [--cpu]"
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
exec 1>"$LOG_DIR/reticle-coess-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-coess-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Co-essentiality (D5)${NC}"
echo -e "${BLUE}========================================${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "GPUs:          ${SLURM_GPUS:-${SLURM_JOB_GPUS:-1}}"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo ""

echo -e "${BLUE}[SETUP]${NC} Loading GPU environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup-gpu.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup-gpu.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup-gpu.sh not found; using system python"
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
echo -e "${BLUE}[RUN]${NC} compute_coessentiality.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
python3 compute_coessentiality.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ CO-ESSENTIALITY COMPLETED${NC}"
else
    echo -e "${RED}✗ CO-ESSENTIALITY FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
