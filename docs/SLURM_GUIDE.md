# RETICLE ETL on SLURM - Complete Guide

## Overview

RETICLE ETL pipeline is fully integrated with SLURM job scheduler. Submit jobs, monitor progress, and scale to large datasets on HPC clusters.

Database credentials are stored securely in `~/.pgpass` (PostgreSQL standard, no plaintext passwords in scripts).

## Setup (One-Time)

### PostgreSQL Credentials (.pgpass)

Create `~/.pgpass` on your HPC login node:

```bash
cat > ~/.pgpass <<'EOF'
your.postgres.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD
EOF

chmod 600 ~/.pgpass
```

See [../slurm/PGPASS_SETUP.md](../slurm/PGPASS_SETUP.md) for complete setup guide.

## Quick Start

### 1. Basic CPU Job (8 cores, 30 minutes)
```bash
cd /Volumes/SD Media/projects/RETICLE/slurm
./submit-etl-job.sh 2
```

### 2. Large CPU Job (32 cores, 64GB RAM)
```bash
./submit-etl-job.sh 2 --cores 32 --mem 64
```

### 3. GPU Job (1 GPU, 16 cores)
```bash
./submit-etl-job.sh 2 --gpu
```

### 4. Multi-GPU Job (2 GPUs)
```bash
./submit-etl-job.sh 2 --gpu --gpus 2 --time 00:30:00
```

## Job Submission Script

### submit-etl-job.sh

Wrapper that builds the correct SBATCH directives and submits the job.

**Features:**
- Auto-calculates memory (4GB per core default)
- Switches between CPU/GPU modes
- Custom time limits and partitions
- Validates inputs before submission

**Usage:**
```bash
./submit-etl-job.sh <version_id> [--cores N] [--mem MB] [--gpu] [--gpus N] [--time HH:MM:SS] [--partition NAME]
```

**Examples:**
```bash
# Mouse dataset (1.9M genes), CPU
./submit-etl-job.sh 2 --cores 16 --mem 64

# Mouse dataset, GPU
./submit-etl-job.sh 2 --gpu --gpus 1

# Human dataset (26M genes), multi-GPU
./submit-etl-job.sh 3 --gpu --gpus 2 --time 01:00:00 --mem 128

# Submit to specific partition
./submit-etl-job.sh 2 --partition compute --cores 24
```

## Job Monitoring

### monitor-etl-jobs.sh

Real-time monitoring of SLURM jobs.

**Commands:**
```bash
./monitor-etl-jobs.sh                   # List all RETICLE jobs
./monitor-etl-jobs.sh 12345             # Show job status
./monitor-etl-jobs.sh 12345 tail        # Watch output live
./monitor-etl-jobs.sh 12345 log         # View complete log
./monitor-etl-jobs.sh 12345 error       # View error log
./monitor-etl-jobs.sh 12345 cancel      # Cancel job
```

**Output Example:**
```
[STEP] RETICLE ETL Jobs

               JOBID                 NAME  ST       TIME  CPUS MIN_CPUS MIN_TMP_DISK END_TIME  FEATURES OVER_SUBSCRIBE JOBID EXEC_HOST CPUS NODES PARTITION PRIORITY NODELIST(REASON) START_TIME STATE UID SUBMIT_TIME NICE MIN_CPUS MIN_TMP_DISK END_TIME FEATURES OVER_SUBSCRIBE JOBID EXEC_HOST CPUS NODES PARTITION PRIORITY NODELIST(REASON) START_TIME STATE UID SUBMIT_TIME NICE MIN_CPUS MIN_TMP_DISK END_TIME FEATURES OVER_SUBSCRIBE
              12345      reticle-etl  R   12:34  8  8        0          2026-06-08T14:23:45Z          OK                    no   [gpu-node-01] Running
```

## SLURM Job Scripts

### reticle-etl.sh (CPU)

Default SLURM job script for multi-threaded CPU processing.

**SBATCH Directives:**
```bash
#SBATCH --job-name=reticle-etl          # Job name
#SBATCH --nodes=1                       # Single node
#SBATCH --ntasks=1                      # Single task
#SBATCH --cpus-per-task=8               # 8 cores (override with --cpus-per-task)
#SBATCH --mem=32G                       # 32GB RAM
#SBATCH --time=00:30:00                 # 30 minutes
#SBATCH --output=logs/reticle-etl-%j.out
#SBATCH --error=logs/reticle-etl-%j.err
#SBATCH --partition=cpu
```

**What It Does:**
1. Validates database connectivity
2. Sets up environment (conda)
3. Runs `hpc_etl_pipeline.py` with specified threads
4. Logs job metadata to database
5. Returns exit code (0 = success)

**Submit Directly:**
```bash
sbatch reticle-etl.sh                   # Default (8 cores)
sbatch --cpus-per-task=16 reticle-etl.sh  # Override cores
sbatch --mem=64G reticle-etl.sh         # Override memory
```

### reticle-etl-gpu.sh (GPU)

GPU variant using RAPIDS for acceleration.

**SBATCH Directives:**
```bash
#SBATCH --gres=gpu:1                    # 1 GPU
#SBATCH --cpus-per-task=16              # 16 CPU cores
#SBATCH --mem=48G                       # 48GB RAM
#SBATCH --partition=gpu                 # GPU partition
#SBATCH --time=00:15:00                 # 15 minutes (faster with GPU)
```

**What It Does:**
1. Loads CUDA modules
2. Loads RAPIDS environment
3. Verifies GPU accessibility
4. Runs `hpc_etl_gpu.py`
5. Logs results

**Submit Directly:**
```bash
sbatch reticle-etl-gpu.sh               # Single GPU
sbatch --gres=gpu:2 reticle-etl-gpu.sh  # Dual GPU
```

## Environment Setup

### env-setup.sh (CPU)

Loads Python environment for CPU jobs.

**What It Does:**
- Loads SLURM-specific modules (if needed)
- Activates conda environment `reticle-etl`
- Verifies required packages (pandas, numpy, psycopg2)
- Falls back to system Python if conda unavailable

**Customize for Your Cluster:**
```bash
# Edit these lines for your HPC modules:
# module load gcc/11.2.0
# module load openmpi/4.1.2
```

### env-setup-gpu.sh (GPU)

Loads CUDA, cuDNN, and RAPIDS for GPU jobs.

**What It Does:**
- Loads CUDA module
- Loads cuDNN module
- Creates/activates RAPIDS conda environment
- Verifies GPU access
- Tests cuDF and CuPy

**Customize for Your Cluster:**
```bash
# Edit CUDA version for your cluster:
# module load cuda/12.0  (or whatever version you have)
# module load cudnn/8.6
```

## Configuration Examples

### Small Cluster (< 32 cores, no GPU)
```bash
# CPU-only job
./submit-etl-job.sh 2 --cores 8 --mem 32

# Output: ~20 seconds
```

### Medium Cluster (32-64 cores, 1-2 GPUs)
```bash
# CPU multi-core
./submit-etl-job.sh 2 --cores 32 --mem 128

# GPU
./submit-etl-job.sh 2 --gpu --gpus 1

# Output: CPU ~10 seconds, GPU ~5 seconds
```

### Large Cluster (64+ cores, 8+ GPUs)
```bash
# CPU with all cores
./submit-etl-job.sh 2 --cores 64 --mem 256

# GPU with multiple GPUs
./submit-etl-job.sh 2 --gpu --gpus 4

# Output: CPU ~5 seconds, GPU ~2 seconds
```

### For Human Dataset (26M genes)
```bash
# CPU option
./submit-etl-job.sh 3 --cores 32 --mem 256 --time 03:00:00

# GPU option (recommended)
./submit-etl-job.sh 3 --gpu --gpus 2 --time 01:00:00
```

## Performance Estimates

### Mouse Dataset (1.9M genes)
| Mode | Cores/GPUs | Time | Speedup |
|------|-----------|------|---------|
| CPU | 8 | 15 sec | 1x |
| CPU | 16 | 8 sec | 2x |
| CPU | 32 | 5 sec | 3x |
| GPU | 1 | 5 sec | 3x |
| GPU | 2 | 3 sec | 5x |

### Human Dataset (26M genes) - Estimates
| Mode | Cores/GPUs | Time | Speedup |
|------|-----------|------|---------|
| CPU | 32 | 120 sec | 1x |
| CPU | 64 | 60 sec | 2x |
| GPU | 2 | 45 sec | 2.7x |
| GPU | 4 | 25 sec | 4.8x |

## Common Tasks

### Check Job Queue
```bash
squeue -n "reticle-etl*"        # All RETICLE jobs
squeue -u $USER                 # Your jobs
squeue -l                       # Long format
```

### Monitor Running Job
```bash
./monitor-etl-jobs.sh 12345 tail    # Live output
sstat -j 12345                      # Resource usage
```

### View Completed Job
```bash
./monitor-etl-jobs.sh 12345 log     # Full log
sacct -j 12345 --format=all         # Job accounting
```

### Cancel Job
```bash
scancel 12345                       # Kill one job
scancel -n reticle-etl              # Kill all RETICLE jobs
```

## Troubleshooting

### "Job submission failed"
- Check SLURM is available: `sinfo`
- Verify quota: `sshare`
- Check partition exists: `sinfo -N`

### "GPU not accessible"
- Verify module loaded: `module list | grep cuda`
- Check GPU visibility: `nvidia-smi`
- Test RAPIDS: `python3 -c "import cudf; print(cudf.__version__)"`

### "Out of memory"
- Increase memory: `./submit-etl-job.sh 2 --mem 128`
- Reduce cores: `--cores 16` (uses less memory per thread)
- Use GPU: `--gpu` (more efficient)

### "Timeout"
- Increase time: `--time 01:00:00`
- Use GPU: Typically 3-5x faster
- Increase cores: Better parallelism

### "RAPIDS not installed"
```bash
# On GPU node, install RAPIDS
conda create -n rapids-gpu -c nvidia -c conda-forge rapids=24.02
conda activate rapids-gpu
```

## Database Logging

ETL pipeline logs to `etl_job_log` table:
```sql
SELECT slurm_job_id, version_id, duration_seconds, status, completed_at
FROM etl_job_log
ORDER BY completed_at DESC
LIMIT 10;
```

Example:
```
slurm_job_id | version_id | duration_seconds | status    | completed_at
12345        | 2          | 14.23            | completed | 2026-06-08 09:47:23
12344        | 2          | 18.45            | completed | 2026-06-08 09:35:12
12343        | 1          | 2.10             | completed | 2026-06-08 09:20:01
```

## Integration with Workflows

### SLURM → Database Pipeline
```bash
#!/bin/bash
# Example: process multiple versions in sequence

for VERSION in 2 3 4; do
    JOB_ID=$(./submit-etl-job.sh $VERSION | grep "Job ID" | awk '{print $NF}')
    echo "Submitted version $VERSION: Job ID $JOB_ID"
    squeue -j $JOB_ID  # Show job status
done
```

### Watch All Jobs
```bash
watch -n 5 'squeue -n "reticle-etl*"'  # Refresh every 5 seconds
```

## Advanced: Custom Partitions

If your cluster has special partitions:
```bash
# High-priority GPU partition
./submit-etl-job.sh 2 --gpu --partition gpu-priority

# Low-latency compute
./submit-etl-job.sh 2 --cores 64 --partition compute-express

# Memory-intensive
./submit-etl-job.sh 3 --mem 512 --partition memory-large
```

## References

- SLURM Documentation: https://slurm.schedmd.com/
- squeue manual: `man squeue`
- sbatch manual: `man sbatch`
- RAPIDS: https://rapids.ai/
