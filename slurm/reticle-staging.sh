#!/bin/bash
#SBATCH --job-name=reticle-staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=logs/reticle-staging-%j.out
#SBATCH --error=logs/reticle-staging-%j.err

# RETICLE Staging Loader - SLURM Job Script
#
# Loads JSON and TSV data into versioned staging tables using parallel I/O.
#
# Usage:
#   sbatch reticle-staging.sh homo_sapiens
#   sbatch reticle-staging.sh mus_musculus 16
#   sbatch reticle-staging.sh --organism homo_sapiens --threads 16
#   sbatch --cpus-per-task=16 reticle-staging.sh homo_sapiens 16
#
# Arguments (positional or flags):
#   homo_sapiens|mus_musculus  Organism [required, positional or --organism]
#   16                         Threads (default: 8, positional or --threads)
#   --organism ORGANISM        Organism flag format
#   --threads N                Threads flag format
#   --description TEXT         Custom description (default: auto-generated)
#
# Environment Variables (optional):
#   STAGING_DESCRIPTION  Custom description for this load (default: auto-generated)
#   RETICLE_DIR          Path to RETICLE repo (auto-detected if not set)

set -e

# Defaults
ORGANISM=""
NUM_THREADS=""

# Parse arguments (supports both positional and flag formats)
while [[ $# -gt 0 ]]; do
    case $1 in
        --organism)
            ORGANISM="$2"
            shift 2
            ;;
        --threads)
            NUM_THREADS="$2"
            shift 2
            ;;
        --description)
            STAGING_DESCRIPTION="$2"
            shift 2
            ;;
        homo_sapiens|mus_musculus)
            # Positional organism
            if [ -z "$ORGANISM" ]; then
                ORGANISM="$1"
                shift
            else
                echo "Error: Organism specified twice"
                exit 1
            fi
            ;;
        [0-9]*)
            # Positional threads
            if [ -z "$NUM_THREADS" ]; then
                NUM_THREADS="$1"
                shift
            else
                echo "Error: Threads specified twice"
                exit 1
            fi
            ;;
        *)
            echo "Error: Unknown argument: $1"
            echo "Usage: $0 [--organism ORGANISM] [--threads N] [--description TEXT]"
            echo "   or: $0 ORGANISM [THREADS]"
            exit 1
            ;;
    esac
done

# Validate organism
if [ -z "$ORGANISM" ]; then
    echo "Error: Organism not specified"
    echo "Usage: $0 [--organism ORGANISM] [--threads N] [--description TEXT]"
    echo "   or: $0 ORGANISM [THREADS]"
    echo ""
    echo "Examples:"
    echo "  $0 homo_sapiens"
    echo "  $0 mus_musculus 16"
    echo "  $0 --organism homo_sapiens --threads 16"
    exit 1
fi

case "$ORGANISM" in
    homo_sapiens|mus_musculus)
        ;;
    *)
        echo "Error: Unknown organism: $ORGANISM"
        echo "Must be: homo_sapiens or mus_musculus"
        exit 1
        ;;
esac

# Set threads default if not specified
NUM_THREADS="${NUM_THREADS:-${SLURM_CPUS_PER_TASK:-8}}"

# Set description default if not specified
STAGING_DESCRIPTION="${STAGING_DESCRIPTION:-Auto-loaded $ORGANISM data (SLURM Job $SLURM_JOB_ID)}"

# Directory configuration
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
echo -e "${BLUE}RETICLE Staging Loader - SLURM Job${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "SLURM Job ID:     $SLURM_JOB_ID"
echo "Job Name:         $SLURM_JOB_NAME"
echo "Nodes:            $SLURM_NNODES"
echo "CPUs per task:    $SLURM_CPUS_PER_TASK"
echo "Memory:           $SLURM_MEM_PER_NODE MB"
echo "Partition:        $SLURM_JOB_PARTITION"
echo ""
echo "Staging Configuration:"
echo "Organism:         $ORGANISM"
echo "Threads:          $NUM_THREADS"
echo "Description:      $STAGING_DESCRIPTION"
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

# Validate data directory
echo -e "${BLUE}[SETUP]${NC} Validating data directory..."
if [ -z "$DATA_DIR" ]; then
    echo -e "${RED}[ERROR]${NC} DATA_DIR not set"
    exit 1
fi

if [ ! -d "$DATA_DIR" ]; then
    echo -e "${RED}[ERROR]${NC} DATA_DIR not found: $DATA_DIR"
    exit 1
fi

DATA_FILES=$(find "$DATA_DIR" -name "screen_metadata_*.json" -o -name "BIOGRID-ORCS-SCREEN_*.screen.tab.txt" | wc -l)
echo "✓ Data directory found ($DATA_FILES files)"
echo ""

# Record start time
START_TIME=$(date +%s)

# Run staging loader
echo -e "${BLUE}[RUN]${NC} Starting HPC staging loader..."
echo ""

python3 hpc_staging_loader.py \
    --organism "$ORGANISM" \
    --threads "$NUM_THREADS" \
    --description "$STAGING_DESCRIPTION"

STAGING_EXIT_CODE=$?

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $STAGING_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ STAGING COMPLETED SUCCESSFULLY${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Check staging results: python3 maintenance.py --show-storage"
    echo "2. Run ETL pipeline:"
    echo "   sbatch ${RETICLE_DIR}/slurm/reticle-etl.sh <version_id>          # CPU"
    echo "   sbatch ${RETICLE_DIR}/slurm/reticle-etl-dedup-gpu.sh <version_id> # GPU"
else
    echo -e "${RED}✗ STAGING FAILED (exit code: $STAGING_EXIT_CODE)${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo "Total Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo "Job ID:         $SLURM_JOB_ID"
echo ""

# Log results to database (optional - table may not exist)
# Only attempt if running in actual SLURM job (SLURM_JOB_ID is set)
if [ -n "$SLURM_JOB_ID" ]; then
    python3 << PYTHON
import psycopg2
from config import Config

try:
    conn = psycopg2.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
        user=Config.DB_USER,
        sslmode='require',
        gssencmode='disable'
    )
    cursor = conn.cursor()
    status = 'completed' if $STAGING_EXIT_CODE == 0 else 'failed'
    cursor.execute("""
        INSERT INTO staging_job_log (slurm_job_id, organism, num_threads, duration_seconds, status, completed_at)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    """, ($SLURM_JOB_ID, "$ORGANISM", $NUM_THREADS, $DURATION, status))
    conn.commit()
    conn.close()
except Exception as e:
    # Table may not exist or other DB error - this is not critical
    pass
PYTHON
fi

exit $STAGING_EXIT_CODE
