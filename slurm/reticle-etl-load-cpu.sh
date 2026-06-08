#!/bin/bash
#SBATCH --job-name=reticle-etl-load-cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/reticle-etl-load-cpu-%j.out
#SBATCH --error=logs/reticle-etl-load-cpu-%j.err
# Note: --partition is set by submit-etl-job-split.sh wrapper (do not set here)

# RETICLE ETL Pipeline - Phase 2: CPU Database Loading Only
#
# Usage:
#   sbatch reticle-etl-load-cpu.sh
#
# Prerequisites:
#   - Phase 1 (gpu_etl_dedup_only.py) must have completed successfully
#   - CSV files must exist in /tmp/reticle_staging/
#   - Staging tables must exist in database
#
# Input:
#   - CSV files from Phase 1: staging_screen_v{VERSION_ID}.csv, staging_screen_gene_v{VERSION_ID}.csv
#
# This script:
#   - Reads CSV files (already deduplicated by GPU phase)
#   - Uses PostgreSQL COPY for fast bulk loading
#   - Validates all data was inserted correctly
#   - No GPU required

set -e

VERSION_ID=${VERSION_ID:-2}

# Directory configuration
# RETICLE_DIR can be set via: export RETICLE_DIR=/path/to/reticle
# or passed via SLURM: sbatch --export=RETICLE_DIR=/path/to/reticle
# Default: auto-detect from script location (fallback)
if [ -z "$RETICLE_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi

SCRIPTS_DIR="$RETICLE_DIR/scripts"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE ETL Pipeline - Phase 2${NC}"
echo -e "${BLUE}CPU Database Loading Only${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "SLURM Job ID:     $SLURM_JOB_ID"
echo "Node:             $SLURM_NODENAME"
echo "CPUs per task:    $SLURM_CPUS_PER_TASK"
echo "Memory:           $SLURM_MEM_PER_NODE MB"
echo "Version ID:       $VERSION_ID"
echo ""

# Load CPU environment
echo -e "${BLUE}[SETUP]${NC} Loading CPU environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo -e "${YELLOW}[WARN]${NC} env-setup.sh not found"
fi

# Change to scripts directory
cd "$SCRIPTS_DIR"

# Validate database connection
echo -e "${BLUE}[SETUP]${NC} Validating database connection..."
python3 << 'PYTHON'
import sys
from config import Config
import psycopg2

try:
    params = Config.get_psycopg2_params()
    params['sslmode'] = 'require'
    params['connect_timeout'] = 5
    conn = psycopg2.connect(**params)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM staging_screen")
    count = cursor.fetchone()[0]
    print(f"✓ Database connected (staging tables accessible)")
    conn.close()
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    sys.exit(1)
PYTHON

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Database validation failed"
    exit 1
fi

# Check that CSV files exist
echo -e "${BLUE}[CHECK]${NC} Verifying CSV files from Phase 1..."

CSV_SCREENS="/tmp/reticle_staging/staging_screen_v${VERSION_ID}.csv"
CSV_PAIRS="/tmp/reticle_staging/staging_screen_gene_v${VERSION_ID}.csv"

if [ ! -f "$CSV_SCREENS" ]; then
    echo -e "${RED}[ERROR]${NC} CSV file not found: $CSV_SCREENS"
    echo ""
    echo "Phase 1 (gpu_etl_dedup_only.py) must complete first!"
    exit 1
fi

if [ ! -f "$CSV_PAIRS" ]; then
    echo -e "${RED}[ERROR]${NC} CSV file not found: $CSV_PAIRS"
    echo ""
    echo "Phase 1 (gpu_etl_dedup_only.py) must complete first!"
    exit 1
fi

SCREENS_SIZE=$(stat -f %z "$CSV_SCREENS" 2>/dev/null || stat -c %s "$CSV_SCREENS")
PAIRS_SIZE=$(stat -f %z "$CSV_PAIRS" 2>/dev/null || stat -c %s "$CSV_PAIRS")

echo "  Screens CSV: $(printf "%.1f" $(echo "$SCREENS_SIZE / 1024 / 1024" | bc -l)) MB"
echo "  Pairs CSV:   $(printf "%.1f" $(echo "$PAIRS_SIZE / 1024 / 1024" | bc -l)) MB"
echo ""

# Start timer
START_TIME=$(date +%s)

# Run CPU load phase
echo -e "${BLUE}[RUN]${NC} Starting CPU loading phase..."
echo ""

python3 cpu_etl_load_only.py \
    --version "$VERSION_ID"

ETL_EXIT_CODE=$?

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $ETL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ CPU LOAD PHASE COMPLETED${NC}"
    echo ""
    echo "SPLIT PIPELINE COMPLETE!"
    echo "  Phase 1 (GPU Dedup): ~30 seconds"
    echo "  Phase 2 (CPU Load):  ~$DURATION_SEC seconds"
else
    echo -e "${RED}✗ CPU LOAD PHASE FAILED${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo "Total Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo "Job ID:         $SLURM_JOB_ID"
echo ""

exit $ETL_EXIT_CODE
