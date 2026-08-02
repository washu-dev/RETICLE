#!/bin/bash
#SBATCH --job-name=reticle-screen-context
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --partition=general-cpu
# CPU job. P3 populate dim_screen_context (one row per screen — far lighter than
# P2's per-screen-gene link table, hence the smaller footprint). Do NOT hardcode
# --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides --partition. Requires
# ~/.pgpass. Requires DATA_DIR to point at the dir holding screen_metadata_*.json.
# Requires P1 harmonize to have run first (reads screen_harmonization).
#
# Usage:  sbatch reticle-screen-context.sh <version_id> [args...]

set -e
if [ -z "$1" ]; then echo "Usage: sbatch $0 <version_id> [args]"; exit 1; fi
VERSION="$1"; shift
if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then echo "ERROR: version_id must be a number, got: $VERSION"; exit 1; fi
EXTRA_ARGS=("$@")

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
SCRIPTS_DIR="$RETICLE_DIR/scripts"
export LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
exec 1>"$LOG_DIR/reticle-screen-context-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-screen-context-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}RETICLE SCREEN CONTEXT (P3)${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo ""

if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi

if [ ! -f ~/.pgpass ]; then echo -e "${RED}[ERROR]${NC} ~/.pgpass not found"; exit 1; fi
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then echo -e "${RED}[ERROR]${NC} ~/.pgpass must be mode 600"; exit 1; fi

cd "$SCRIPTS_DIR"
START_TIME=$(date +%s)
echo -e "${BLUE}[RUN]${NC} populate_screen_context.py --version $VERSION ${EXTRA_ARGS[*]}"
python3 populate_screen_context.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
DURATION=$(($(date +%s) - START_TIME))
echo ""
if [ $EXIT_CODE -eq 0 ]; then echo -e "${GREEN}✓ SCREEN CONTEXT (P3) COMPLETED${NC}"; else echo -e "${RED}✗ SCREEN CONTEXT (P3) FAILED (exit $EXIT_CODE)${NC}"; fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
exit $EXIT_CODE
