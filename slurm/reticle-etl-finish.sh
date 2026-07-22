#!/bin/bash
#SBATCH --job-name=reticle-etl-finish
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --partition=general-cpu
# Notes:
# - This job is a thin client; the heavy work (aggregate GROUP BYs) runs server-side
#   in PostgreSQL, so cpu/mem are modest but --time is generous for large versions.
# - Do NOT hardcode --account here. Set it once via the SBATCH_ACCOUNT env var
#   (e.g. export SBATCH_ACCOUNT="$RETICLE_ACCOUNT"); sbatch honors it automatically.
#   Likewise SBATCH_PARTITION overrides the --partition default above.
#
# RETICLE ETL Finisher - repair a split-pipeline load whose aggregate stage
# did not complete (fact_screen_gene / dim_* empty for a version).
#
# Usage:
#   sbatch reticle-etl-finish.sh 7            # version 7, latest run
#   sbatch reticle-etl-finish.sh 7 4          # version 7, run_id 4
#   sbatch reticle-etl-finish.sh 7 --dry-run  # log SQL + counts, change nothing
#   sbatch reticle-etl-finish.sh 7 4 --dry-run

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [run_id] [--dry-run]"
    exit 1
fi

VERSION="$1"; shift
if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: version_id must be a number, got: $VERSION"
    exit 1
fi

# Optional args: a bare number = run_id; --dry-run passes through.
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) EXTRA_ARGS+=(--dry-run); shift ;;
        --run-id)  EXTRA_ARGS+=(--run-id "$2"); shift 2 ;;
        [0-9]*)    EXTRA_ARGS+=(--run-id "$1"); shift ;;
        *) echo "ERROR: unknown argument: $1"; exit 1 ;;
    esac
done

# Directory configuration (auto-detect if RETICLE_DIR unset)
if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
SCRIPTS_DIR="$RETICLE_DIR/scripts"
export LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"

# Redirect SLURM job output into LOG_DIR (the Python script also writes its own
# etl-finish-v<version>-run<run>.log there with every SQL statement + row count).
exec 1>"$LOG_DIR/reticle-etl-finish-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-etl-finish-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE ETL Finisher${NC}"
echo -e "${BLUE}========================================${NC}"
echo "SLURM Job ID:  $SLURM_JOB_ID"
echo "Node:          $SLURM_NODENAME"
echo "Version ID:    $VERSION"
echo "Extra args:    ${EXTRA_ARGS[*]:-<none>}"
echo "LOG_DIR:       $LOG_DIR"
echo ""

# Load environment (venv + psycopg2); same as the other ETL jobs
echo -e "${BLUE}[SETUP]${NC} Loading environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi

# Validate credentials
if [ ! -f ~/.pgpass ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass not found (see slurm/PGPASS_SETUP.md)"
    exit 1
fi
PGPASS_PERMS=$(stat -c %a ~/.pgpass 2>/dev/null || stat -f %A ~/.pgpass 2>/dev/null)
if [ "$PGPASS_PERMS" != "600" ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass permissions are $PGPASS_PERMS (must be 600): chmod 600 ~/.pgpass"
    exit 1
fi

cd "$SCRIPTS_DIR"

START_TIME=$(date +%s)
echo -e "${BLUE}[RUN]${NC} finish_etl_load.py --version $VERSION ${EXTRA_ARGS[*]}"
echo ""

python3 finish_etl_load.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ ETL FINISH COMPLETED${NC}"
else
    echo -e "${RED}✗ ETL FINISH FAILED (exit $EXIT_CODE)${NC}"
fi
echo "Duration:      $((DURATION / 60))m $((DURATION % 60))s"
echo "Detail log:    $LOG_DIR/etl-finish-v${VERSION}-run*.log"
echo -e "${BLUE}========================================${NC}"

exit $EXIT_CODE
