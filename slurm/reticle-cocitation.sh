#!/bin/bash
#SBATCH --job-name=reticle-cocitation
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=23:00:00
#SBATCH --partition=general-cpu
# CPU job. D7 co-citation. Do NOT hardcode --account; set SBATCH_ACCOUNT.
# SBATCH_PARTITION overrides --partition. Requires ~/.pgpass.
#
# Usage:  sbatch reticle-cocitation.sh <version_id> [args...]

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
exec 1>"$LOG_DIR/reticle-cocitation-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-cocitation-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}RETICLE CO-CITATION (D7)${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo ""

if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi
source "$RETICLE_DIR/slurm/heartbeat.sh"

if [ ! -f ~/.pgpass ]; then echo -e "${RED}[ERROR]${NC} ~/.pgpass not found"; exit 1; fi
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then echo -e "${RED}[ERROR]${NC} ~/.pgpass must be mode 600"; exit 1; fi

cd "$SCRIPTS_DIR"
START_TIME=$(date +%s)
echo -e "${BLUE}[RUN]${NC} compute_cocitation.py --version $VERSION ${EXTRA_ARGS[*]}"
run_with_heartbeat "compute_cocitation.py" python3 compute_cocitation.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
DURATION=$(($(date +%s) - START_TIME))
echo ""
if [ $EXIT_CODE -eq 0 ]; then echo -e "${GREEN}✓ CO-CITATION (D7) COMPLETED${NC}"; else echo -e "${RED}✗ CO-CITATION (D7) FAILED (exit $EXIT_CODE)${NC}"; fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
exit $EXIT_CODE
