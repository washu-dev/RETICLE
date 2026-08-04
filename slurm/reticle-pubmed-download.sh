#!/bin/bash
#SBATCH --job-name=reticle-pubmed
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --partition=general-cpu
# --partition overridable: sbatch --partition=<name> reticle-pubmed-download.sh
# --account settable via: sbatch --account=<acct> or RETICLE_ACCOUNT
#
# RETICLE PubMed / NCBI literature refresh — RECURRING SLURM job.
#
# Chains (all on RIS storage, NO database needed — lowest-risk job):
#   1. scripts/download_ncbi_bulk.py        -> $RETICLE_DATA/ncbi/*.gz
#   2. prototype/script/build_kb_gene.py    -> $RETICLE_DATA/kb/kb.db (identity backbone)
#   3. prototype/script/build_kb_pubmed_links.py -> kb_gene_pubmed (gene<->PMID)
#
# build_kb_pubmed_links REQUIRES kb_gene first, so build_kb_gene runs in between
# (cheap full rebuild, ~65k genes). Idempotent: the downloader skips unchanged files.
#
# Usage (on a c2-login host):
#   sbatch slurm/reticle-pubmed-download.sh
#   TAXIDS=9606 sbatch slurm/reticle-pubmed-download.sh    # human only
# Recurrence: cron on a WashU-network host that ssh's in and runs the sbatch
# (see slurm/RETICLE_RIS_JOBS.md).

set -e

# ---- config (env-overridable) ----
RETICLE_DATA="${RETICLE_DATA:-/storage3/fs1/aorvedahl-RETICLE/Active/data}"
TAXIDS="${TAXIDS:-9606,10090}"
VENV="${RETICLE_VENV:-$HOME/.reticle-etl-venv}"

# ---- locate the repo (this script lives in <repo>/slurm) ----
if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi
LOG_DIR="${LOG_DIR:-$RETICLE_DIR/logs}"
mkdir -p "$LOG_DIR"
# Redirect only inside a real SLURM job (so interactive `bash` runs print to screen).
if [ -n "$SLURM_JOB_ID" ]; then
    exec 1>"$LOG_DIR/reticle-pubmed-${SLURM_JOB_ID}.out"
    exec 2>"$LOG_DIR/reticle-pubmed-${SLURM_JOB_ID}.err"
fi

echo "========================================"
echo "RETICLE PubMed refresh"
echo "  SLURM Job ID: ${SLURM_JOB_ID:-<interactive>}"
echo "  RETICLE_DATA: $RETICLE_DATA"
echo "  taxids:       $TAXIDS"
echo "========================================"

# ---- python env (no .pgpass needed: this job never touches the DB) ----
module load python3 2>/dev/null || true
if [ ! -d "$VENV" ]; then
    echo "[setup] creating venv at $VENV"
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
pip install --upgrade pip --quiet
pip install requests --quiet   # download_ncbi_bulk.py; build_kb_* use only stdlib

NCBI_DIR="$RETICLE_DATA/ncbi"
KB_DB="$RETICLE_DATA/kb/kb.db"
mkdir -p "$(dirname "$KB_DB")"

echo "[pubmed] 1/3 download NCBI bulk files"
python3 "$RETICLE_DIR/scripts/download_ncbi_bulk.py" --out-dir "$NCBI_DIR"

echo "[pubmed] 2/3 rebuild kb_gene identity backbone"
python3 "$RETICLE_DIR/prototype/script/build_kb_gene.py" \
    --ncbi-dir "$NCBI_DIR" --out "$KB_DB" --taxids "$TAXIDS"

echo "[pubmed] 3/3 rebuild kb_gene_pubmed links"
python3 "$RETICLE_DIR/prototype/script/build_kb_pubmed_links.py" \
    --ncbi-dir "$NCBI_DIR" --db "$KB_DB" --taxids "$TAXIDS"

echo "[pubmed] done"
