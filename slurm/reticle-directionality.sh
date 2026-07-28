#!/bin/bash
#SBATCH --job-name=reticle-directionality
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --partition=general-cpu
# Notes:
# - CPU job. Low volume (only the ambiguous screens for a version); rate-limited LLM calls.
# - Do NOT hardcode --account; set SBATCH_ACCOUNT. SBATCH_PARTITION overrides --partition.
# - Needs: ~/.pgpass (RDS), $DATA_DIR (screen_metadata_*.json), the WashU VPN (LLM gateway),
#   and RETICLE/secure_api secrets. If the compute node lacks AWS credentials to read
#   Secrets Manager, export the creds via env instead, e.g.:
#     export RETICLE_SECRET__RETICLE_SECURE_API_CLIENT_ID=... (etc. — see llm_gateway._fetch_secret)
#   Many will simply run this step locally (Mac / api host) where AWS creds already exist.
#
# LLM directionality resolution -> screen_directionality (DB). Run AFTER
# harmonize_warehouse.py has tagged ambiguous screens; then re-run harmonize with
# --apply-directionality to apply the status='auto' decisions.
#
# Usage:
#   sbatch reticle-directionality.sh 8
#   sbatch reticle-directionality.sh 8 --dry-run
#   sbatch reticle-directionality.sh 8 --model claude-opus-5 --limit 20

set -e

if [ -z "$1" ]; then
    echo "Usage: sbatch $0 <version_id> [--model M] [--limit N] [--dry-run] [--resume]"
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
exec 1>"$LOG_DIR/reticle-directionality-${SLURM_JOB_ID}.out"
exec 2>"$LOG_DIR/reticle-directionality-${SLURM_JOB_ID}.err"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${BLUE}RETICLE Directionality Mapper — version $VERSION${NC}"
echo "SLURM Job ID: $SLURM_JOB_ID | Extra args: ${EXTRA_ARGS[*]:-<none>} | DATA_DIR: ${DATA_DIR:-<unset>}"

if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found; using system python"
fi
if [ ! -f ~/.pgpass ]; then
    echo -e "${RED}[ERROR]${NC} ~/.pgpass not found"; exit 1
fi

cd "$SCRIPTS_DIR"
python3 directionality_mapper.py --version "$VERSION" "${EXTRA_ARGS[@]}"
EXIT_CODE=$?
echo -e "${BLUE}========================================${NC}"
[ $EXIT_CODE -eq 0 ] && echo -e "${GREEN}✓ DIRECTIONALITY COMPLETED${NC}" || echo -e "${RED}✗ FAILED (exit $EXIT_CODE)${NC}"
exit $EXIT_CODE
