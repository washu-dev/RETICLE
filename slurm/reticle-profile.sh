#!/bin/bash
#SBATCH --job-name=reticle-profile
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=23:00:00
#SBATCH --partition=general-cpu
# Notes:
# - CPU job by design. The profiler (D2) is exact-where-cheap (sparse Hᵀ·H for
#   co-hit/co-citation) + a SAMPLED co-essentiality estimate — no n×n product, no
#   GPU. Memory is bumped vs harmonize because the sparse co-hit matrix over
#   selective genes can carry tens of millions of nonzeros.
# - Do NOT hardcode --account; set SBATCH_ACCOUNT (e.g. export SBATCH_ACCOUNT="$RETICLE_ACCOUNT").
#   SBATCH_PARTITION overrides the --partition default above.
#
# D2 profiler: reads the harmonized warehouse (P1) for one version and writes ONE
# relatedness_profile snapshot (data shape + threshold->projected-pairs/cost
# curves). Prerequisite: run slurm/reticle-harmonize.sh <version> first.
#
# Usage:
#   sbatch reticle-profile.sh 7
#   sbatch reticle-profile.sh 7 --dry-run
#   sbatch reticle-profile.sh 7 --sample-size 600 --seed 1337
#
# Requires ~/.pgpass (DB creds). DATA_DIR is NOT needed (unlike harmonize) — the
# profiler reads only the warehouse.

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--dry-run] [--sample-size N] [--seed N]"
    exit 1
fi
VERSION="$1"; shift
if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: version_id must be a number, got: $VERSION"; exit 1
fi
EXTRA_ARGS=("$@")   # passthrough: --dry-run / --sample-size / --seed / --*-grid

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
SCRIPTS_DIR="$RETICLE_DIR/scripts"
export LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
exec 1>"$LOG_DIR/reticle-profile-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-profile-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE Relatedness Profiler (D2)${NC}"
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
echo -e "${BLUE}[RUN]${NC} profile_relatedness.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""
run_with_heartbeat "profile_relatedness.py" python3 profile_relatedness.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s); DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ PROFILE COMPLETED${NC}"
else
    echo -e "${RED}✗ PROFILE FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo -e "${BLUE}========================================${NC}"
exit $EXIT_CODE
