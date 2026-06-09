#!/bin/bash
#SBATCH --job-name=reticle-etl
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/reticle-etl-%j.out
#SBATCH --error=logs/reticle-etl-%j.err
#SBATCH --partition=cpu
# Note: --partition can be overridden via sbatch --partition= or wrapper sets it

# RETICLE ETL Pipeline - SLURM Job Script
#
# Usage:
#   sbatch reticle-etl.sh
#   sbatch --cpus-per-task=16 reticle-etl.sh  (override cores)
#   sbatch --mem=64G reticle-etl.sh           (override memory)
#
# Environment Variables (optional):
#   VERSION_ID        Version to process (default: 2)
#   NUM_THREADS       Thread count (default: 8, must match --cpus-per-task)
#   CHUNK_SIZE        Data chunk size (default: 100000)
#   BATCH_SIZE        Insert batch size (default: 10000)

set -e

# Configuration from environment variables
VERSION_ID=${VERSION_ID:-2}
NUM_THREADS=${NUM_THREADS:-${SLURM_CPUS_PER_TASK:-8}}
CHUNK_SIZE=${CHUNK_SIZE:-100000}
BATCH_SIZE=${BATCH_SIZE:-10000}

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
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RETICLE ETL Pipeline - SLURM Job${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "SLURM Job ID:     $SLURM_JOB_ID"
echo "Job Name:         $SLURM_JOB_NAME"
echo "Nodes:            $SLURM_NNODES"
echo "CPUs per task:    $SLURM_CPUS_PER_TASK"
echo "Memory:           $SLURM_MEM_PER_NODE MB"
echo "Partition:        $SLURM_JOB_PARTITION"
echo ""
echo "ETL Configuration:"
echo "Version ID:       $VERSION_ID"
echo "Threads:          $NUM_THREADS"
echo "Chunk Size:       $CHUNK_SIZE"
echo "Batch Size:       $BATCH_SIZE"
echo ""

# Load environment
echo -e "${BLUE}[SETUP]${NC} Loading environment..."
if [ -f "$RETICLE_DIR/slurm/env-setup.sh" ]; then
    source "$RETICLE_DIR/slurm/env-setup.sh"
else
    echo "Warning: env-setup.sh not found, using system python"
fi

# Create log directory
mkdir -p "$RETICLE_DIR/logs"

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
    cursor.execute("SELECT COUNT(*) FROM data_load_version")
    count = cursor.fetchone()[0]
    print(f"✓ Database connected ({count} versions found)")
    conn.close()
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    sys.exit(1)
PYTHON

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Database validation failed"
    exit 1
fi

# Start timer
START_TIME=$(date +%s)

# Run ETL pipeline
echo -e "${BLUE}[RUN]${NC} Starting ETL pipeline..."
echo ""

python3 hpc_etl_pipeline.py \
    --version "$VERSION_ID" \
    --threads "$NUM_THREADS" \
    --chunk-size "$CHUNK_SIZE" \
    --batch-size "$BATCH_SIZE"

ETL_EXIT_CODE=$?

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $ETL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ ETL PIPELINE COMPLETED SUCCESSFULLY${NC}"
else
    echo -e "${RED}✗ ETL PIPELINE FAILED (exit code: $ETL_EXIT_CODE)${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo "Total Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo "Job ID:         $SLURM_JOB_ID"
echo ""

# Log results to database
python3 << PYTHON
import psycopg2
from config import Config
from datetime import datetime

try:
    conn = psycopg2.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        sslmode='require',
        gssencmode='disable'
    )
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO etl_job_log (slurm_job_id, version_id, duration_seconds, status, completed_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
    """, ($SLURM_JOB_ID, $VERSION_ID, $DURATION, 'completed' if $ETL_EXIT_CODE -eq 0 else 'failed'))
    conn.commit()
    conn.close()
except Exception as e:
    echo "Warning: Could not log to database: \$e"
PYTHON

exit $ETL_EXIT_CODE
