# RETICLE ETL on SLURM

Complete SLURM integration for submitting, monitoring, and managing RETICLE ETL jobs on HPC clusters.

## Quick Start (2 Minutes)

### 1. Submit a Job
```bash
cd /Volumes/SD Media/projects/RETICLE/slurm

# CPU job (8 cores, default)
./submit-etl-job.sh 2

# GPU job (1 GPU)
./submit-etl-job.sh 2 --gpu

# Large job (32 cores, 128GB RAM)
./submit-etl-job.sh 2 --cores 32 --mem 128
```

### 2. Monitor
```bash
# List all RETICLE jobs
./monitor-etl-jobs.sh

# Watch specific job
./monitor-etl-jobs.sh 12345 tail

# View complete log
./monitor-etl-jobs.sh 12345 log
```

### 3. Expected Results
- Mouse dataset (1.9M genes): **15-20 seconds (CPU)** or **5-10 seconds (GPU)**
- Human dataset (26M genes): **~2 minutes (CPU)** or **~45 seconds (GPU)**

---

## Files

### Job Scripts
- **reticle-etl.sh** — CPU multi-threaded job
- **reticle-etl-gpu.sh** — GPU-accelerated job (RAPIDS)

### Helpers
- **submit-etl-job.sh** — Job submission wrapper (recommended)
- **monitor-etl-jobs.sh** — Job monitoring and log viewing
- **env-setup.sh** — CPU environment configuration
- **env-setup-gpu.sh** — GPU environment configuration

### Documentation
- **../docs/SLURM_GUIDE.md** — Complete SLURM guide
- **../QUICKSTART_HPC_ETL.md** — HPC pipeline quickstart

---

## Usage

### Submit CPU Job
```bash
./submit-etl-job.sh <version_id> [--cores N] [--mem MB] [--time HH:MM:SS] [--partition NAME]
```

**Examples:**
```bash
./submit-etl-job.sh 2                          # Default: 8 cores, 30 min
./submit-etl-job.sh 2 --cores 16               # 16 cores
./submit-etl-job.sh 2 --cores 32 --mem 128     # 32 cores, 128GB RAM
./submit-etl-job.sh 2 --partition compute      # Custom partition
```

### Submit GPU Job
```bash
./submit-etl-job.sh <version_id> --gpu [--gpus N] [--time HH:MM:SS]
```

**Examples:**
```bash
./submit-etl-job.sh 2 --gpu                    # Default: 1 GPU, 16 cores
./submit-etl-job.sh 2 --gpu --gpus 2           # 2 GPUs
./submit-etl-job.sh 2 --gpu --time 01:00:00    # 1 hour time limit
```

### Monitor Jobs
```bash
./monitor-etl-jobs.sh                   # List all jobs
./monitor-etl-jobs.sh <job_id>          # Job status
./monitor-etl-jobs.sh <job_id> tail     # Watch output
./monitor-etl-jobs.sh <job_id> log      # Full log
./monitor-etl-jobs.sh <job_id> error    # Error log
./monitor-etl-jobs.sh <job_id> cancel   # Cancel job
```

---

## Performance Estimates

### Mouse Dataset (1.9M genes)
| CPUs | GPU | Time | Speedup |
|------|-----|------|---------|
| 8 | - | 15 sec | 1x |
| 16 | - | 8 sec | 2x |
| 32 | - | 5 sec | 3x |
| 16 | 1 | 5 sec | 3x |
| 16 | 2 | 3 sec | 5x |

### Human Dataset (26M genes) - Estimates
| CPUs | GPU | Time | Speedup |
|------|-----|------|---------|
| 32 | - | 120 sec | 1x |
| 64 | - | 60 sec | 2x |
| 32 | 1 | 60 sec | 2x |
| 32 | 2 | 45 sec | 2.7x |
| 64 | 2 | 30 sec | 4x |

---

## Environment Setup

### CPU Jobs
The `env-setup.sh` script:
1. Loads SLURM modules (if needed)
2. Creates/activates conda environment `reticle-etl`
3. Verifies pandas, numpy, psycopg2

**Customize for your cluster:**
```bash
# Edit env-setup.sh line 11-13 to load your modules:
# module load gcc/11.2.0
# module load openmpi/4.1.2
```

### GPU Jobs
The `env-setup-gpu.sh` script:
1. Loads CUDA module
2. Creates/activates RAPIDS conda environment
3. Verifies GPU access and RAPIDS packages

**Customize for your cluster:**
```bash
# Edit env-setup-gpu.sh line 13-16 to load your CUDA version:
# module load cuda/12.0
# module load cudnn/8.6
```

---

## Database Logging

ETL pipeline logs to database table `etl_job_log`:

```sql
-- Create table (run once)
psql -h <host> -d <db> -f ../database/migrations/0010_etl_job_logging.sql

-- View recent jobs
SELECT slurm_job_id, version_id, duration_seconds, status, completed_at
FROM etl_job_log
ORDER BY completed_at DESC
LIMIT 10;

-- View performance stats
SELECT * FROM etl_job_stats;
```

---

## Common Tasks

### Check Job Queue
```bash
squeue -n "reticle-etl*"     # All RETICLE jobs
squeue -u $USER              # Your jobs
```

### Submit Multiple Versions
```bash
for VERSION in 2 3 4; do
    JOB_ID=$(./submit-etl-job.sh $VERSION | grep "Job ID" | awk '{print $NF}')
    echo "Version $VERSION: Job ID $JOB_ID"
done
```

### Watch Jobs in Real-Time
```bash
watch -n 5 'squeue -n "reticle-etl*"'
```

### Cancel All RETICLE Jobs
```bash
scancel -n reticle-etl
```

---

## Troubleshooting

### GPU Not Available
```bash
# Check CUDA module
module list | grep cuda

# Check GPU visibility
nvidia-smi

# Verify RAPIDS
python3 -c "import cudf; print(cudf.__version__)"
```

### Job Timeout
```bash
# Increase time limit
./submit-etl-job.sh 2 --time 01:00:00

# Or use GPU (faster)
./submit-etl-job.sh 2 --gpu
```

### Out of Memory
```bash
# Increase memory
./submit-etl-job.sh 2 --mem 128

# Or reduce cores
./submit-etl-job.sh 2 --cores 8 --mem 32
```

### Connection Errors
```bash
# Verify database credentials in ../scripts/config.py
# Test connection:
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -c "SELECT 1"
```

---

## Integration Example

### Process Multiple Datasets
```bash
#!/bin/bash
# run-all.sh - Submit all versions in sequence

RETICLE_SLURM="/Volumes/SD Media/projects/RETICLE/slurm"

for VERSION in 2 3 4; do
    echo "Submitting version $VERSION..."
    $RETICLE_SLURM/submit-etl-job.sh $VERSION --gpu --gpus 2
    sleep 5
done

echo "All jobs submitted. Monitor with:"
echo "  watch -n 5 'squeue -n \"reticle-etl*\"'"
```

Run:
```bash
chmod +x run-all.sh
./run-all.sh
```

---

## Next Steps

1. **Customize environment** — Edit `env-setup.sh` and `env-setup-gpu.sh` for your cluster
2. **Test CPU job** — `./submit-etl-job.sh 2`
3. **Test GPU job** — `./submit-etl-job.sh 2 --gpu` (if available)
4. **Monitor results** — `./monitor-etl-jobs.sh`
5. **Check database** — Query `etl_job_log` table for metrics

---

## More Info

See `../docs/SLURM_GUIDE.md` for complete documentation including:
- Detailed SLURM directives
- Configuration for different cluster sizes
- Performance tuning
- Advanced partition options
- SLURM command reference
