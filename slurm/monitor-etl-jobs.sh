#!/bin/bash
#
# Monitor RETICLE ETL jobs
#
# Usage:
#   ./monitor-etl-jobs.sh              # Show all RETICLE jobs
#   ./monitor-etl-jobs.sh 12345        # Show specific job
#   ./monitor-etl-jobs.sh 12345 tail   # Tail job output
#

RETICLE_DIR="/Volumes/SD Media/projects/RETICLE"
LOGS_DIR="$RETICLE_DIR/logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

function log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

function log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Case 1: Monitor all RETICLE jobs
if [ -z "$1" ]; then
    log_step "RETICLE ETL Jobs"
    echo ""
    squeue -n "reticle-etl*" --format="%.18i %.20j %.2t %.10M %.5C %.5m %N"
    echo ""
    log_info "Show detailed info: squeue -j <job_id>"
    log_info "Tail output:        ./monitor-etl-jobs.sh <job_id> tail"
    exit 0
fi

JOB_ID=$1
COMMAND=${2:-status}

# Check if job exists
if ! squeue -j "$JOB_ID" &>/dev/null; then
    log_error "Job $JOB_ID not found in queue"

    # Check if logs exist
    if ls "$LOGS_DIR"/reticle-etl-$JOB_ID* 1>/dev/null 2>&1; then
        log_info "Job logs found (job may have completed)"
        ls -lh "$LOGS_DIR"/reticle-etl-$JOB_ID*
    else
        exit 1
    fi
else
    log_info "Job $JOB_ID is in queue"
fi

case $COMMAND in
    status)
        echo ""
        log_step "Job Details"
        squeue -j "$JOB_ID" --format="%.18i %.20j %.2t %.10M %.5C %.5m %N"
        echo ""
        ;;
    tail)
        echo ""
        log_step "Tailing Job Output"
        if [ -f "$LOGS_DIR/reticle-etl-$JOB_ID.out" ]; then
            echo "Press Ctrl+C to stop"
            echo ""
            tail -f "$LOGS_DIR/reticle-etl-$JOB_ID.out"
        else
            log_error "Output file not found: $LOGS_DIR/reticle-etl-$JOB_ID.out"
            exit 1
        fi
        ;;
    log)
        echo ""
        log_step "Complete Job Log"
        if [ -f "$LOGS_DIR/reticle-etl-$JOB_ID.out" ]; then
            cat "$LOGS_DIR/reticle-etl-$JOB_ID.out"
        else
            log_error "Log file not found"
            exit 1
        fi
        ;;
    error)
        echo ""
        log_step "Error Log"
        if [ -f "$LOGS_DIR/reticle-etl-$JOB_ID.err" ]; then
            cat "$LOGS_DIR/reticle-etl-$JOB_ID.err"
        else
            log_info "No errors logged"
        fi
        ;;
    cancel)
        log_step "Canceling job $JOB_ID..."
        scancel "$JOB_ID"
        log_info "Job cancellation requested"
        ;;
    *)
        echo "Usage: $0 <job_id> [status|tail|log|error|cancel]"
        exit 1
        ;;
esac
