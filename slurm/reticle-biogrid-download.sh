#!/bin/bash
#SBATCH --job-name=reticle-biogrid-dl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --partition=general-cpu
# --partition overridable via sbatch --partition=<name>
#
# RETICLE BioGRID ORCS download — INFREQUENT SLURM job (download step only).
#
# Fetches BioGRID ORCS screen dumps into the on-disk layout the loaders expect.
# This job does NOT load the database — after it finishes, run the team's
# EXISTING SLURM scripts to stage + ETL:
#     sbatch slurm/reticle-staging.sh <organism>
#     sbatch slurm/reticle-etl.sh                 # (with VERSION_ID from staging)
#
# ⚠ screen_metadata_<organism>.json (ORCS webservice + access key) is NOT
#   downloaded here — place it in the loader's DATA_DIR before staging.
#
# Usage:
#   sbatch slurm/reticle-biogrid-download.sh                          # latest, human+mouse
#   ORGANISMS="homo_sapiens" RELEASE=2.0.18 sbatch slurm/reticle-biogrid-download.sh
#   RELEASE=2.0.18 sbatch slurm/reticle-biogrid-download.sh

set -e

RETICLE_DATA="${RETICLE_DATA:-/storage3/fs1/aorvedahl-RETICLE/Active/data}"
ORGANISMS="${ORGANISMS:-homo_sapiens mus_musculus}"
RELEASE="${RELEASE:-}"
VENV="${RETICLE_VENV:-$HOME/.reticle-etl-venv}"

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
if [ -n "$SLURM_JOB_ID" ]; then
    exec 1>"$LOG_DIR/reticle-biogrid-dl-${SLURM_JOB_ID}.out"
    exec 2>"$LOG_DIR/reticle-biogrid-dl-${SLURM_JOB_ID}.err"
fi

echo "========================================"
echo "RETICLE BioGRID ORCS download"
echo "  SLURM Job ID: ${SLURM_JOB_ID:-<interactive>}"
echo "  RETICLE_DATA: $RETICLE_DATA"
echo "  organisms:    $ORGANISMS"
echo "  release:      ${RELEASE:-<latest discovered>}"
echo "========================================"

module load python3 2>/dev/null || true
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
source "$VENV/bin/activate"
pip install --upgrade pip --quiet
pip install requests beautifulsoup4 lxml --quiet

REL_FLAG=""
[ -n "$RELEASE" ] && REL_FLAG="--release $RELEASE"
ORG_FLAGS=""
for org in $ORGANISMS; do ORG_FLAGS="$ORG_FLAGS --organism $org"; done

echo "[biogrid-dl] downloading..."
# shellcheck disable=SC2086
python3 "$RETICLE_DIR/scripts/download_biogrid_orcs.py" $REL_FLAG $ORG_FLAGS --out-dir "$RETICLE_DATA"

echo ""
echo "[biogrid-dl] done. Next steps (existing SLURM scripts):"
for org in $ORGANISMS; do
    echo "  DATA_DIR=$RETICLE_DATA/BIOGRID-ORCS-${RELEASE:-<release>} sbatch slurm/reticle-staging.sh $org"
done
echo "  # then, with the version_id printed by staging:"
echo "  VERSION_ID=<id> sbatch slurm/reticle-etl.sh"
