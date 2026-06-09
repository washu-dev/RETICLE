# RETICLE SLURM — HPC Job Orchestration

Complete SLURM integration for submitting, monitoring, and managing RETICLE ETL jobs on HPC clusters.

---

## Quick Reference

| Script | Purpose | Recommended Use |
|--------|---------|-----------------|
| **reticle-staging.sh** ⭐ | HPC staging loader with parallel I/O | **Data Load** |
| **submit-etl-job.sh** | Submit unified ETL (CPU or GPU) | Quick testing |
| **submit-etl-job-split.sh** ⭐ | Submit split pipeline (GPU dedup, then CPU load) | **Production** |
| **reticle-etl.sh** | SLURM wrapper for CPU-only ETL | Called by submit-etl-job.sh |
| **reticle-etl-gpu.sh** | SLURM wrapper for GPU+CPU unified ETL | Called by submit-etl-job.sh |
| **reticle-etl-dedup-gpu.sh** | SLURM wrapper for Phase 1 (GPU dedup only) | Called by submit-etl-job-split.sh |
| **reticle-etl-load-cpu.sh** | SLURM wrapper for Phase 2 (CPU load only) | Called by submit-etl-job-split.sh |
| **monitor-etl-jobs.sh** | Monitor, tail, and manage running jobs | Monitoring |
| **env-setup.sh** | Environment setup for CPU jobs | Sourced by reticle-etl.sh |
| **env-setup-gpu.sh** | Environment setup for GPU jobs | Sourced by GPU scripts |

---

## Environment Variables (Configuration)

All SLURM scripts support consistent partition configuration via environment variables:

### Partition Configuration

| Variable | Scripts Using | Default | Purpose |
|----------|---------------|---------|---------|
| `RETICLE_PARTITION_CPU` | reticle-staging.sh, submit-etl-job.sh, submit-etl-job-split.sh | `"cpu"` | Default partition for CPU jobs |
| `RETICLE_PARTITION_GPU` | submit-etl-job.sh, submit-etl-job-split.sh | `"gpu"` | Default partition for GPU jobs |

**Setup:**
```bash
# Set in ~/.bashrc or ~/reticle.sh for permanent configuration
export RETICLE_PARTITION_CPU=general-cpu      # Your cluster's CPU partition
export RETICLE_PARTITION_GPU=general-gpu      # Your cluster's GPU partition

# Or set temporarily for a single session
export RETICLE_PARTITION_CPU=fast
sbatch slurm/submit-etl-job.sh 1
```

**Override via command-line:**
```bash
# All these scripts support --partition flag
sbatch slurm/reticle-staging.sh homo_sapiens --partition fast
sbatch slurm/submit-etl-job.sh 1 --partition fast
sbatch slurm/submit-etl-job-split.sh 1 --partition fast --both
```

**Or via sbatch directly:**
```bash
sbatch --partition=general-cpu slurm/submit-etl-job.sh 1
sbatch --partition=gpu-v100 slurm/submit-etl-job.sh 1 --gpu
```

---

## Data Staging (Load Phase)

### `reticle-staging.sh` ⭐ **RECOMMENDED**

**HPC-optimized parallel staging loader** — Loads JSON and TSV data into versioned staging tables with multi-threaded I/O.

**Key Benefits:**
- **4-5x faster** than sequential loading (35-45 sec vs 2-3 min for 1M genes)
- **Separate from ETL** — stage once, run dedup multiple times without re-staging
- **Parallel I/O** — efficiently uses cluster bandwidth
- **Configurable threads** — scale with available cores

**Usage:**
```bash
sbatch slurm/reticle-staging.sh <organism> [threads]
# OR
sbatch slurm/reticle-staging.sh --organism <organism> --threads <threads>
```

⚠️ **IMPORTANT:** Must be submitted with `sbatch`, not run directly

This is a **SLURM job script**. You must submit it to the job queue:

```bash
# ✅ CORRECT: Submit to SLURM
sbatch slurm/reticle-staging.sh mus_musculus 16

# ❌ WRONG: Running directly on login node
./slurm/reticle-staging.sh mus_musculus 16
```

**Why?**
- Direct execution runs on login node (not intended for heavy workloads)
- SLURM variables (`$SLURM_JOB_ID`, `$SLURM_CPUS_PER_TASK`, etc.) are empty
- No resource isolation or scheduling
- Risks overloading shared login node

**Arguments (positional or flags):**
```
organism               homo_sapiens or mus_musculus (required)
                       --organism homo_sapiens (flag format)
threads                Number of parallel threads (default: 8)
                       --threads 16 (flag format)
                       Should match --cpus-per-task for efficiency
--description TEXT     Custom description (optional, flag format only)
```

**Examples:**
```bash
# Positional: Default (8 threads)
sbatch slurm/reticle-staging.sh homo_sapiens

# Positional: Mouse data with 16 threads
sbatch slurm/reticle-staging.sh mus_musculus 16

# Flags: Same, using flag format
sbatch slurm/reticle-staging.sh --organism mus_musculus --threads 16

# Mixed: positional organism, flag threads
sbatch slurm/reticle-staging.sh mus_musculus --threads 16

# Override SLURM cores (positional)
sbatch --cpus-per-task=16 slurm/reticle-staging.sh homo_sapiens 16

# Override SLURM cores (flags)
sbatch --cpus-per-task=16 slurm/reticle-staging.sh --organism homo_sapiens --threads 16

# Custom description
sbatch slurm/reticle-staging.sh --organism homo_sapiens --threads 8 --description "Q2 2026 run"
```

**What it does:**
1. Validate database connection
2. Verify data directory (`$DATA_DIR`) exists
3. Spawn `hpc_staging_loader.py` with parallel threads
4. Read JSON files (screen metadata) in parallel
5. Read TSV files (gene/screen records) in parallel
6. Single atomic PostgreSQL COPY operation
7. Create versioned `staging_*` tables
8. Return version ID and staging statistics

**Output:**
```
========================================
RETICLE Staging Loader - SLURM Job
========================================

SLURM Job ID:     12345
Job Name:         reticle-staging
Nodes:            1
CPUs per task:    8
Memory:           16G
Partition:        general-cpu

Staging Configuration:
Organism:         homo_sapiens
Threads:          8
Description:      Auto-loaded homo_sapiens data (SLURM Job 12345)

[SETUP] Loading environment...
[SETUP] Validating database connection...
✓ Database connected (2 versions found)
[SETUP] Validating data directory...
✓ Data directory found (1,234 files)

[RUN] Starting HPC staging loader...
Loading homo_sapiens data...
✓ Staging completed successfully

========================================
✓ STAGING COMPLETED SUCCESSFULLY

Next steps:
1. Check staging results: python3 maintenance.py --show-storage
2. Run ETL pipeline:
   sbatch /path/to/slurm/reticle-etl.sh <version_id>          # CPU
   sbatch /path/to/slurm/reticle-etl-dedup-gpu.sh <version_id> # GPU
========================================
Total Duration: 0m 42s
Job ID:         12345
```

**Workflow:**

Always use `sbatch` to submit the job:

```bash
# Step 1: Submit staging (wait for completion)
JOB_ID=$(sbatch slurm/reticle-staging.sh homo_sapiens | awk '{print $NF}')
echo "Submitted staging job: $JOB_ID"

# Step 2: Monitor completion
squeue -j $JOB_ID

# Step 3: Check results (once complete)
tail -20 logs/reticle-staging-${JOB_ID}.out

# Step 4: Check version created
python3 scripts/maintenance.py --show-storage

# Step 5: Submit desired dedup variant
# Option A: CPU dedup (cheaper, slower)
sbatch slurm/reticle-etl.sh 3

# Option B: GPU dedup (expensive, faster) + CPU load (chained)
sbatch slurm/reticle-etl-dedup-gpu.sh 3
```

**Resource Requirements:**
- **CPU cores:** 8-16 (scales linearly with cores)
- **Memory:** 16GB (constant, regardless of data size)
- **Time:** 1-10 minutes (depends on dataset size and thread count)
- **I/O:** High bandwidth needed (fast parallel filesystem recommended)

**Performance:** (approximate)
- Mouse (1.9M genes): 35-45 seconds (8 threads)
- Human (31M genes): 3-5 minutes (8 threads), 2-3 minutes (16 threads)

**Optional Environment Variables:**
```bash
export STAGING_DESCRIPTION="Q2 2026 human screens"  # Custom description
export RETICLE_DIR=/path/to/RETICLE                 # Override repo path
```

---

## Submission Scripts

### `submit-etl-job.sh` ⭐ **PRIMARY**

**High-level job submission wrapper** — Submits unified ETL pipeline (all work on one node) for quick testing.

**Usage:**
```bash
./submit-etl-job.sh <version_id> [options]
```

**Options:**
```
--cores N          CPU cores (default: 8)
--mem MB           Memory in GB (default: auto = 4GB per core)
--gpu              GPU mode (default: CPU)
--gpus N           Number of GPUs (default: 1, only with --gpu)
--time HH:MM:SS    Time limit (default: 30 min CPU, 15 min GPU)
--partition NAME   SLURM partition (default: env RETICLE_PARTITION_CPU/GPU)
--help             Show help
```

**Examples:**
```bash
# CPU job (8 cores, 30 minutes)
./submit-etl-job.sh 2

# CPU job (16 cores, 128GB RAM)
./submit-etl-job.sh 2 --cores 16 --mem 128

# GPU job (1 GPU, 16 cores, 15 minutes)
./submit-etl-job.sh 2 --gpu

# GPU job (2 GPUs, custom time)
./submit-etl-job.sh 2 --gpu --gpus 2 --time 00:30:00

# Custom partition
./submit-etl-job.sh 2 --partition compute-gpu
```

**Output:**
```
Job submitted successfully!
Job ID:           1234567
Status:           Check with: squeue -j 1234567
Output:           /Volumes/SD Media/projects/RETICLE/logs/reticle-etl-1234567.out
```

**When to use:**
- ✅ Quick testing (small datasets)
- ✅ Debugging
- ❌ Production (wastes GPU resources if using --gpu)

---

### `submit-etl-job-split.sh` ⭐ **PRODUCTION RECOMMENDED**

**Split pipeline submission** — Submits Phase 1 (GPU dedup) and Phase 2 (CPU load) separately for maximum efficiency.

**Usage:**
```bash
./submit-etl-job-split.sh <version_id> [options]
```

**Options:**
```
--gpu              Submit Phase 1 only (GPU dedup) [default]
--cpu              Submit Phase 2 only (CPU load)
--both             Submit both phases with auto-chaining [RECOMMENDED]
--gpu-time HH:MM   Time limit for Phase 1 (default: 5 min)
--gpu-cores N      CPU cores for Phase 1 (default: 8)
--gpu-gpus N       Number of GPUs for Phase 1 (default: 1)
--cpu-time HH:MM   Time limit for Phase 2 (default: 1 hour)
--cpu-cores N      CPU cores for Phase 2 (default: 8)
--partition NAME   SLURM partition (overrides defaults)
--help             Show help
```

**Examples:**
```bash
# Both phases with automatic chaining
./submit-etl-job-split.sh 2 --both

# Phase 1 only (GPU dedup)
./submit-etl-job-split.sh 2 --gpu

# Phase 2 only (CPU load, manual - Phase 1 must be done)
./submit-etl-job-split.sh 2 --cpu

# Custom time limits
./submit-etl-job-split.sh 2 --both --gpu-time 00:10:00 --cpu-time 02:00:00

# Custom cores
./submit-etl-job-split.sh 2 --gpu-cores 16 --cpu-cores 32
```

**Output:**
```
PHASE 1 (GPU Deduplication)
  GPU Cores:        8
  GPUs:             1
  Time Limit:       00:05:00
  Partition:        gpu-v100

[STEP] Submitting Phase 1 (GPU Dedup)...
[INFO] Phase 1 submitted successfully!
Job ID:           1234567
...

PHASE 2 (CPU Loading)
  CPU Cores:        8
  Time Limit:       01:00:00
  Partition:        general-cpu
  Depends on:       Phase 1 (job 1234567)

[STEP] Submitting Phase 2 (CPU Load) with dependency on Phase 1...
[INFO] Phase 2 submitted successfully!
Job ID:           1234568
...

BOTH PHASES SUBMITTED
Phase 1 (GPU):    Job 1234567
Phase 2 (CPU):    Job 1234568
Phase 2 will start automatically after Phase 1 completes.
```

**Cost & Performance:**
- GPU reserved: 5 minutes (vs 30 min in unified)
- Total time: ~1-2 minutes wall-clock
- **Cost savings: $9.50+ per run**

**When to use:**
- ✅ Production (large datasets)
- ✅ Cost-conscious workflows
- ✅ Multi-dataset pipelines

---

## SLURM Job Scripts

### `reticle-etl.sh`

**SLURM job wrapper for CPU-only ETL** — Configures environment, validates database, runs `hpc_etl_pipeline.py`.

**SBATCH Directives:**
```
--job-name=reticle-etl
--nodes=1
--ntasks=1
--cpus-per-task=8 (can override with submit-etl-job.sh)
--mem=32G (auto-calculated: 4GB per core)
--time=00:30:00 (default, override with --time flag)
--output=logs/reticle-etl-%j.out
--error=logs/reticle-etl-%j.err
# --partition set by submit-etl-job.sh (not hardcoded here)
```

**Environment Variables (set by submit-etl-job.sh):**
- `VERSION_ID` — Data load version number
- `NUM_THREADS` — Number of parallel threads
- `RETICLE_DIR` — Path to RETICLE directory

**What it does:**
1. Load environment via `env-setup.sh`
2. Validate database connection
3. Change to scripts directory
4. Run `hpc_etl_pipeline.py` with VERSION_ID and NUM_THREADS
5. Report success/failure with timing

**Called by:**
- `submit-etl-job.sh` (when --gpu not specified)

**Do NOT run directly:**
```bash
# Wrong - missing environment setup
./reticle-etl.sh 2

# Correct - use submit-etl-job.sh wrapper
./submit-etl-job.sh 2
```

---

### `reticle-etl-gpu.sh`

**SLURM job wrapper for GPU+CPU unified ETL** — Configures GPU environment, verifies RAPIDS, runs `hpc_etl_gpu.py`.

**SBATCH Directives:**
```
--job-name=reticle-etl-gpu
--nodes=1
--ntasks=1
--cpus-per-task=16 (default, override with --gpu-cores)
--mem=48G (auto-calculated: 4GB per core)
--time=00:15:00 (default, override with --time)
--gres=gpu:1 (default, override with --gpus)
--output=logs/reticle-etl-gpu-%j.out
--error=logs/reticle-etl-gpu-%j.err
# --partition set by submit-etl-job.sh
```

**Environment Variables (set by submit-etl-job.sh):**
- `VERSION_ID` — Data load version
- `NUM_THREADS` — Number of CPU threads

**What it does:**
1. Load GPU environment via `env-setup-gpu.sh`
2. Verify GPU availability with `nvidia-smi`
3. Verify RAPIDS/cuDF installation
4. Validate database connection
5. Run `hpc_etl_gpu.py` with dedup on GPU (or fallback to CPU pandas)
6. Report timing (should show GPU dedup and CPU load)

**Called by:**
- `submit-etl-job.sh` (when --gpu specified)

**⚠️ Note:**
- GPU used for ~30 seconds
- GPU node reserved for 15 minutes
- Wastes GPU resources on database operations

**Recommendation:**
- Use split pipeline instead for production

---

### `reticle-etl-dedup-gpu.sh`

**SLURM job wrapper for Phase 1 (GPU dedup only)** — Configures GPU environment, runs `gpu_etl_dedup_only.py`.

**SBATCH Directives:**
```
--job-name=reticle-etl-dedup-gpu
--nodes=1
--ntasks=1
--cpus-per-task=8 (default)
--mem=32G (4GB per core)
--time=00:05:00 (default, only 5 min for dedup work!)
--gres=gpu:1
--output=logs/reticle-etl-dedup-gpu-%j.out
--error=logs/reticle-etl-dedup-gpu-%j.err
```

**Environment Variables (set by submit-etl-job-split.sh):**
- `VERSION_ID` — Data load version
- `RETICLE_DIR` — Path to RETICLE directory

**What it does:**
1. Load GPU environment via `env-setup-gpu.sh`
2. Verify GPU with `nvidia-smi`
3. Validate database connection
4. Run `gpu_etl_dedup_only.py`
5. Output CSV files to `/tmp/reticle_staging/` for Phase 2
6. Print progress and next step instructions

**Output:**
```
GPU DEDUPLICATION PHASE
GPU Available: True

✓ Loaded 205 screens
GPU: Deduplicating 1,904,551 genes...
Removed 1,874,512 duplicates
GPU: Deduplicating pairs...

GPU DEDUP PHASE COMPLETE
Elapsed time: 28.3s
Genes: 1,904,551 → 30,039
Pairs: 5,987,834 → 6,034,251

Next Step: Run Phase 2 (CPU Load)
  ./submit-etl-job-split.sh 2 --cpu
```

**Called by:**
- `submit-etl-job-split.sh` (when --both or --gpu)

**GPU Utilization:**
- ✅ GPU fully utilized during dedup (~30s)
- ✅ No wasted GPU time
- ✅ Node released immediately after

---

### `reticle-etl-load-cpu.sh`

**SLURM job wrapper for Phase 2 (CPU load only)** — Loads deduplicated data into database via PostgreSQL COPY.

**SBATCH Directives:**
```
--job-name=reticle-etl-load-cpu
--nodes=1
--ntasks=1
--cpus-per-task=8 (default)
--mem=32G (4GB per core)
--time=01:00:00 (1 hour default for large datasets)
--output=logs/reticle-etl-load-cpu-%j.out
--error=logs/reticle-etl-load-cpu-%j.err
# No GPU needed
```

**Environment Variables (set by submit-etl-job-split.sh):**
- `VERSION_ID` — Data load version
- `RETICLE_DIR` — Path to RETICLE directory

**Prerequisites:**
- Phase 1 (gpu_etl_dedup_only.py) must have completed
- CSV files must exist in `/tmp/reticle_staging/`

**What it does:**
1. Load CPU environment via `env-setup.sh`
2. Validate database connection
3. Verify CSV files exist
4. Run `cpu_etl_load_only.py`
   - Read staging_screen_v{VERSION}.csv
   - PostgreSQL COPY into staging_screen
   - Read staging_screen_gene_v{VERSION}.csv
   - PostgreSQL COPY into staging_screen_gene
   - Validate: row counts match, no NULLs
5. Print results with live progress bars

**Output:**
```
CPU LOADING PHASE
Version ID: 2

✓ Database connected
Verifying CSV files from Phase 1...
  Screens CSV: 0.1 MB
  Pairs CSV:   200.0 MB

Loading screens via COPY...
  Total screens: 205
  COPY screens |████████████████| 205/205 [00:02]
  ✓ Inserted 205 screens

Loading screen-gene pairs via COPY...
  Total pairs: 6,034,251
  COPY pairs   |████████████░░░░| 4.2M/6.0M [00:18<00:08]
  ✓ Inserted 6,034,251 pairs

Validating loaded data...
  Screens: 205 ✓
  Pairs: 6,034,251 ✓
  NULL validation: PASSED ✓

CPU LOADING PHASE COMPLETE
Elapsed time: 21.8s
```

**Called by:**
- `submit-etl-job-split.sh` (when --both or --cpu)

**CPU Utilization:**
- ✅ CPU fully utilized during COPY (~30s)
- ✅ No wasted GPU resources
- ✅ Cost-efficient

---

## Monitoring & Management

### `monitor-etl-jobs.sh`

**Job monitoring and log management** — List, tail, log, error, and cancel RETICLE ETL jobs.

**Usage:**
```bash
./monitor-etl-jobs.sh [job_id] [command]
```

**Commands:**
```
(no args)            List all RETICLE jobs
<job_id>             Show job status
<job_id> status      Job status with details
<job_id> tail        Follow output in real-time (tail -f)
<job_id> log         View full output log
<job_id> error       View error log
<job_id> cancel      Cancel the job
```

**Examples:**
```bash
# List all RETICLE jobs
./monitor-etl-jobs.sh

# Check specific job
./monitor-etl-jobs.sh 1234567

# Watch job output live
./monitor-etl-jobs.sh 1234567 tail

# View full log
./monitor-etl-jobs.sh 1234567 log

# View errors
./monitor-etl-jobs.sh 1234567 error

# Cancel job
./monitor-etl-jobs.sh 1234567 cancel
```

**Output (list):**
```
[INFO] Active RETICLE ETL jobs:

Job ID    Name                Status   Time   Nodes  CPUs  Memory
1234567   reticle-etl         RUNNING  12:34  1      8     32G
1234568   reticle-etl-gpu     RUNNING  05:23  1      16    48G
1234569   reticle-etl-load    PENDING  00:00  1      8     32G
```

**Output (status):**
```
[INFO] Job 1234567 is in queue

[STEP] Job Details
  Job ID:       1234567
  Name:         reticle-etl
  Status:       RUNNING
  Elapsed:      12 minutes 34 seconds
  Nodes:        1
  CPUs:         8
  Memory:       32 GB
  Output:       logs/reticle-etl-1234567.out
  Error:        logs/reticle-etl-1234567.err
```

---

## Environment Setup

### `env-setup.sh`

**CPU environment configuration** — Creates Python venv, installs dependencies, validates .pgpass.

**What it does:**
1. Load Python module (if available)
2. Try conda (if available), else use venv
3. Create ~/.reticle-etl-venv (cached, reused)
4. Activate venv
5. Upgrade pip
6. Install: pandas, numpy, psycopg2-binary, python-dotenv, tqdm
7. Verify all packages are importable
8. Validate ~/.pgpass exists with permissions 600

**Sourced by:**
- `reticle-etl.sh` (CPU jobs)

**Customize for your cluster:**
```bash
# Line 12: Load modules appropriate for your HPC
module load python3
# Add more modules here if needed:
# module load gcc/11.2.0
# module load openmpi/4.1.2
```

**Output (success):**
```
Setting up environment...
  Using conda...
  Creating conda environment...
  Activating virtual environment...
  Installing packages (this may take a minute)...
  Verifying packages...
  ✓ pandas: Data deduplication
  ✓ numpy: Numerical computing
  ✓ psycopg2: PostgreSQL driver
  ✓ dotenv: Configuration management
  ✓ tqdm: Progress reporting
✓ .pgpass found with correct permissions (600)
✓ Environment ready
```

---

### `env-setup-gpu.sh`

**GPU environment configuration** — Loads CUDA, installs RAPIDS/cuDF, falls back to CPU pandas if unavailable.

**What it does:**
1. Load Python module
2. Try to load CUDA module (with fallback)
3. Verify CUDA with `nvidia-smi`
4. Try conda (if available), else use venv
5. Create ~/.rapids-gpu-venv (cached, reused)
6. Activate venv
7. Upgrade pip
8. Install cuDF (GPU-accelerated pandas) or fallback to pandas
9. Install: psycopg2-binary, python-dotenv, tqdm
10. Verify all packages (GPU packages optional)
11. Validate ~/.pgpass

**Sourced by:**
- `reticle-etl-gpu.sh` (GPU unified pipeline)
- `reticle-etl-dedup-gpu.sh` (GPU dedup phase)

**Customize for your cluster:**
```bash
# Line 20: Load CUDA module (adjust for your cluster)
module load cuda  # or cuda/12.0, cuda/11.8, etc.
```

**Output (success with GPU):**
```
Setting up GPU environment...
  Loading CUDA modules (if available)...
  ✓ cuda module loaded
  Using conda for RAPIDS...
  Creating RAPIDS conda environment...
  ✓ cuDF version: 24.02.00
  ✓ CuPy version: 12.0.0
  ✓ pandas: CPU fallback
  ✓ psycopg2: PostgreSQL
  ✓ dotenv: Configuration management
  ✓ tqdm: Progress reporting
⚠ GPU packages available - using GPU acceleration
✓ .pgpass found with correct permissions (600)
✓ GPU environment ready
```

**Output (fallback to CPU):**
```
Setting up GPU environment...
  ⚠ CUDA module not found (GPU may not work)
  ⚠ cuDF installation failed - GPU acceleration unavailable
     Falling back to CPU pandas
  ✓ pandas: CPU fallback
  ✓ psycopg2: PostgreSQL
  ✓ dotenv: Configuration management
⚠ GPU packages not available - using CPU fallback
✓ .pgpass found with correct permissions (600)
✓ GPU environment ready
```

---

## Setup & Configuration

### One-Time Setup

```bash
# 1. Create .pgpass for secure credentials
cat > ~/.pgpass <<'EOF'
your.rds.endpoint.us-east-1.rds.amazonaws.com:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD
EOF
chmod 600 ~/.pgpass

# 2. Set environment variables in ~/.bashrc
export RETICLE_DIR=$HOME/projects/RETICLE
export DB_HOST=your.rds.endpoint.us-east-1.rds.amazonaws.com
export DB_PORT=5432
export DB_NAME=reticle_biogrid
export DB_USER=reticle_admin
export RETICLE_PARTITION_CPU=general-cpu    # Your cluster's CPU partition
export RETICLE_PARTITION_GPU=gpu-v100       # Your cluster's GPU partition

# 3. Test setup
source ~/.bashrc
cd ~/projects/RETICLE/slurm
./submit-etl-job.sh 2  # Submit a test job
```

---

## Workflow Examples

### Example 1: Split Pipeline (Recommended)

```bash
cd ~/projects/RETICLE/slurm

# Submit both phases with auto-chaining
./submit-etl-job-split.sh 2 --both

# Monitor Phase 1
./monitor-etl-jobs.sh <phase1_job_id> tail

# Monitor Phase 2 (starts automatically after Phase 1)
./monitor-etl-jobs.sh <phase2_job_id> tail

# View results
./monitor-etl-jobs.sh <phase2_job_id> log
```

### Example 2: Unified Pipeline (Quick Test)

```bash
# CPU test
./submit-etl-job.sh 2

# Or GPU test
./submit-etl-job.sh 2 --gpu

# Monitor
./monitor-etl-jobs.sh
./monitor-etl-jobs.sh <job_id> tail
```

### Example 3: Large Dataset (32 cores)

```bash
./submit-etl-job.sh 2 --cores 32 --mem 128 --time 01:00:00
```

---

## Performance Expectations

### Mouse Dataset (1.9M genes)

| Approach | GPU Time | Total Reserve | Cost | Speed |
|----------|----------|---|------|-------|
| CPU (8 core) | N/A | 1 min (actual) | $0 | 1x |
| CPU (16 core) | N/A | 1 min (actual) | $0 | 2x |
| GPU unified | 30s | 30 min | $12 | 1x |
| GPU split | 30s | 5 min GPU + 1h CPU | $2.50 | 1x |

### Human Dataset (26M genes)

| Approach | Estimated Time | Cost per Run |
|----------|---|---|
| CPU (32 core) | 2-3 minutes | $0.50 |
| GPU unified | 1-2 minutes | $15 |
| GPU split | 1-2 minutes | $3 |

---

## Troubleshooting

### GPU Not Found
```bash
# Check CUDA module available
module avail cuda

# Load CUDA (adjust version for your cluster)
module load cuda/12.0

# Verify GPU access
nvidia-smi
```

### Job Times Out
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

### Database Connection Error
```bash
# Check .pgpass
cat ~/.pgpass  # Should show credentials
ls -la ~/.pgpass  # Should show: -rw------- (600)

# Test psql connection
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1"
```

### Phase 2 Not Starting After Phase 1
```bash
# Check Phase 1 completed
./monitor-etl-jobs.sh <phase1_id> log

# Manually submit Phase 2
./submit-etl-job-split.sh 2 --cpu
```

---

## References

- **Scripts Overview**: See `../scripts/README.md`
- **Split Pipeline Guide**: `../docs/SPLIT_GPU_CPU_PIPELINE.md`
- **Quickstart**: `SPLIT_PIPELINE_QUICKSTART.md`
- **SLURM Reference**: `SLURM_GUIDE.md`
- **PostgreSQL Setup**: `PGPASS_SETUP.md`
- **Environment Variables**: `ENV_VARS_SETUP.md`
- **WashU C2 Specific**: `WASHIU_C2_SETUP.md`
