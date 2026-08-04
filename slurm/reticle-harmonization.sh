#!/bin/bash
#SBATCH --job-name=reticle-harmonize
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --partition=general-cpu
# --partition overridable via sbatch --partition=<name>
#
# RETICLE harmonization pipeline — INFREQUENT SLURM job.
#
# Chains (prototype/script, SQLite-based; writes $RETICLE_DATA/processed_data/reticle_master.db):
#   1. harmonize_scores.py        (raw BioGRID screens -> harmonized_scores, ~28M rows)
#   2. [WITH_LLM=1] llm_metadata_extractor.py + directionality_mapper.py  (needs WashU LLM gateway)
#   3. apply_directionality.py --anchor-resolve-conflicts
#   4. fix_directionality.py
#   5. validate_harmonization.py  -> HARD GATE: exits 1 if any method's sign is inverted
#   6. [MIGRATE=1] migrate_to_rds.py  -> promote to RDS schema `reticle`
#
# Env flags (sbatch passes them through automatically):
#   WITH_LLM=1     include the LLM directionality step (default: off; uses frozen
#                  $RETICLE_DATA/processed_data/directionality_overrides.json)
#   MIGRATE=1      also promote to RDS. Needs AWS_DB_HOST/PORT/USER/NAME/PASSWORD
#                  exported before submit (migrate_to_rds.py reads them from env).
#   META_ONLY=1    with MIGRATE=1, promote only the small tables (quick check)
#
# Usage:
#   sbatch slurm/reticle-harmonization.sh
#   WITH_LLM=1 sbatch slurm/reticle-harmonization.sh
#   MIGRATE=1 META_ONLY=1 sbatch slurm/reticle-harmonization.sh

set -e

RETICLE_DATA="${RETICLE_DATA:-/storage3/fs1/aorvedahl-RETICLE/Active/data}"
export RETICLE_DATA               # prototype/script/paths.py reads this
VENV="${RETICLE_VENV:-$HOME/.reticle-etl-venv}"
WITH_LLM="${WITH_LLM:-0}"
MIGRATE="${MIGRATE:-0}"
META_ONLY="${META_ONLY:-0}"

if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
if [ -n "$SLURM_JOB_ID" ]; then
    exec 1>"$LOG_DIR/reticle-harmonize-${SLURM_JOB_ID}.out"
    exec 2>"$LOG_DIR/reticle-harmonize-${SLURM_JOB_ID}.err"
fi

echo "========================================"
echo "RETICLE harmonization"
echo "  SLURM Job ID: ${SLURM_JOB_ID:-<interactive>}"
echo "  RETICLE_DATA: $RETICLE_DATA"
echo "  WITH_LLM=$WITH_LLM  MIGRATE=$MIGRATE  META_ONLY=$META_ONLY"
echo "========================================"

module load python3 2>/dev/null || true
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
source "$VENV/bin/activate"
pip install --upgrade pip --quiet
# prototype deps: numpy pandas scipy requests psycopg2-binary (+ dotenv for migrate)
pip install numpy pandas scipy requests psycopg2-binary python-dotenv --quiet

if [ "$MIGRATE" = "1" ] && [ -z "${AWS_DB_HOST:-}" ]; then
    echo "WARNING: MIGRATE=1 but AWS_DB_HOST unset — migrate_to_rds.py will fail."
    echo "         export AWS_DB_HOST/PORT/USER/NAME/PASSWORD before submitting."
fi

P="$RETICLE_DIR/prototype/script"
cd "$P"

echo "[harmonize] 1 harmonize_scores"
python3 harmonize_scores.py

if [ "$WITH_LLM" = "1" ]; then
    echo "[harmonize] 2 LLM metadata + directionality (WashU gateway)"
    python3 llm_metadata_extractor.py
    python3 directionality_mapper.py
else
    echo "[harmonize] 2 LLM step skipped (frozen directionality_overrides.json)"
fi

echo "[harmonize] 3 apply_directionality"
python3 apply_directionality.py --anchor-resolve-conflicts

echo "[harmonize] 4 fix_directionality"
python3 fix_directionality.py

echo "[harmonize] 5 validate (HARD GATE — job aborts on inverted sign)"
python3 validate_harmonization.py

if [ "$MIGRATE" = "1" ]; then
    MO=""
    [ "$META_ONLY" = "1" ] && MO="--meta-only"
    echo "[harmonize] 6 migrate_to_rds $MO"
    python3 migrate_to_rds.py $MO
fi

echo "[harmonize] done"
