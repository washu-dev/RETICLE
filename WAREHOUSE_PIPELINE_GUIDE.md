# RETICLE Warehouse Pipeline Guide

This guide explains how to run the RETICLE data warehouse pipeline locally or on HPC, covering data staging through ETL processing.

---

## A. Scripts Folder vs SLURM Folder: Relationship & Roles

### Quick Reference

| Folder | Role | Primary Users | Execution |
|--------|------|---------------|-----------|
| **`scripts/`** | Core Python ETL logic + convenience wrappers | Local dev, HPC batch jobs | Direct Python invocation or shell wrapper |
| **`slurm/`** | Job submission & monitoring for HPC | HPC users only | SLURM (`sbatch`), dispatch to `scripts/` |

### Data Flow

```
Data Files (TSV/JSON)
        ↓
    ┌───────────────────────────────────────────────┐
    │ STAGING (Load into warehouse)                 │
    ├───────────────────────────────────────────────┤
    │ • Local:   scripts/staging_loader.py           │
    │ • HPC:     scripts/hpc_staging_loader.py       │
    │            (called from slurm/reticle-etl.sh)  │
    └───────────────────────────────────────────────┘
        ↓
    PostgreSQL staging_* tables (versioned)
        ↓
    ┌───────────────────────────────────────────────┐
    │ ETL PIPELINE (Deduplicate & Transform)        │
    ├───────────────────────────────────────────────┤
    │ • Local CPU:     scripts/run_etl_pipeline.py   │
    │ • HPC Unified:   scripts/hpc_etl_pipeline.py   │
    │ • HPC Split GPU: scripts/hpc_etl_gpu.py        │
    │ • HPC Split CPU: scripts/cpu_etl_load_only.py  │
    │                                                 │
    │ SLURM Wrappers:                                │
    │ • slurm/submit-etl-job.sh                      │
    │ • slurm/submit-etl-job-split.sh                │
    │ • slurm/reticle-etl.sh (direct SLURM job)     │
    │ • slurm/reticle-etl-gpu.sh (GPU variant)      │
    │ • slurm/reticle-etl-dedup-gpu.sh (Phase 1)    │
    │ • slurm/reticle-etl-load-cpu.sh (Phase 2)     │
    └───────────────────────────────────────────────┘
        ↓
    PostgreSQL processed data tables (screen, gene, fact_*)
        ↓
    ┌───────────────────────────────────────────────┐
    │ MONITORING & MAINTENANCE                      │
    ├───────────────────────────────────────────────┤
    │ • scripts/maintenance.py (purge, rollback)     │
    │ • slurm/monitor-etl-jobs.sh (SLURM monitor)   │
    │ • scripts/validate_etl_readiness.py            │
    └───────────────────────────────────────────────┘
```

### Key Relationships

**Direct Python Execution (Local Development)**
- Developer runs `python3 scripts/staging_loader.py` → loads data
- Developer runs `python3 scripts/run_etl_pipeline.py` → processes data
- Developer runs `python3 scripts/maintenance.py` → manages versions

**Shell Wrapper Convenience (Both Local & HPC)**
- Colorized output and argument validation
- Scripts folder wrappers: `warehouse-load.sh`, `warehouse-run-etl.sh`, etc.
- Examples: `./warehouse-load.sh homo_sapiens` → `python3 staging_loader.py ...`

**HPC Batch Execution (SLURM)**
- User submits: `sbatch slurm/reticle-etl.sh 2` → schedules in job queue
- SLURM script sets environment, runs HPC-optimized Python script
- Output logged to `${LOG_DIR}/reticle-etl-${JOB_ID}.log`
- Dependencies managed via `#SBATCH --dependency=afterok:${PHASE_1_ID}`

---

## B. Entry Points: Local vs HPC (with/without GPU)

### Local Development (Single Machine)

**Minimal Setup:** PostgreSQL running, Python 3.12+, environment configured

#### Workflow 1: Full Pipeline (Local)
```bash
# Terminal 1: Load data
cd /path/to/RETICLE/scripts
source /path/to/reticle.sh          # Load environment
python3 staging_loader.py --organism homo_sapiens --description "Test load"
# Output: "✓ Created version 1"

# Terminal 2: Run ETL
python3 run_etl_pipeline.py --version 1
# Output: "✓ ETL completed: 30,039 genes processed"

# Terminal 3: Verify & cleanup
python3 maintenance.py --show-storage
python3 maintenance.py --purge-old
```

#### Workflow 2: Using Shell Wrappers (Local)
```bash
cd /path/to/RETICLE/scripts
source /path/to/reticle.sh

./warehouse-load.sh homo_sapiens "Human data v1"
./warehouse-run-etl.sh 1
./warehouse-maintenance.sh --show-storage
```

**Entry Points:**
- `staging_loader.py` — Load staging data
- `run_etl_pipeline.py` — Single-threaded ETL (uses CPU)
- `maintenance.py` — Manage versions

---

### HPC: CPU-Only (No GPU)

**Requirements:** SLURM cluster, NFS-mounted data directory, PostgreSQL accessible from compute nodes

#### Workflow 1: Direct SLURM Job (Recommended)
```bash
# SSH to HPC login node
ssh hpc.cluster.com
cd ~/RETICLE

# Set environment
source ~/reticle.sh

# Submit staging + ETL as single job
sbatch slurm/reticle-etl.sh 1

# Monitor
squeue -u $USER
tail -f logs/reticle-etl-${JOB_ID}.log
```

**What it does:**
- Allocates CPU cores (8 by default)
- Runs `scripts/hpc_staging_loader.py --threads 8` (parallel I/O)
- Runs `scripts/hpc_etl_pipeline.py --threads 8` (multi-threaded dedup + load)
- Total time: ~60 seconds (including setup)
- Logs to `${LOG_DIR}/reticle-etl-${JOB_ID}.log`

#### Workflow 2: Submit-Wrapper (Manual Control)
```bash
# Stage data only
./slurm/submit-etl-job.sh 1 --stage-only

# ETL only (manual staging)
./slurm/submit-etl-job.sh 1 --etl-only

# Both (default)
./slurm/submit-etl-job.sh 1
```

**Entry Points:**
- `slurm/reticle-etl.sh` — Unified staging + ETL (recommended)
- `slurm/submit-etl-job.sh` — Wrapper with options
- `scripts/hpc_staging_loader.py` — Parallel staging (called by SLURM script)
- `scripts/hpc_etl_pipeline.py` — Multi-threaded ETL (called by SLURM script)

---

### HPC: CPU + GPU (Split Pipeline)

**Requirements:** SLURM cluster with GPU nodes, NFS-mounted data, PostgreSQL accessible

#### Workflow: GPU Dedup + CPU Load

```bash
ssh hpc.cluster.com
cd ~/RETICLE
source ~/reticle.sh

# Submit Phase 1 (GPU dedup) + Phase 2 (CPU load), auto-chained
sbatch slurm/reticle-etl-dedup-gpu.sh 1

# Monitor both jobs
squeue -u $USER
tail -f logs/reticle-etl-gpu-*.log
tail -f logs/reticle-etl-load-cpu-*.log
```

**Phase 1: GPU Dedup (~30 seconds)**
- Allocates 1 GPU (A100 recommended) + 8 CPUs
- Runs `scripts/hpc_etl_gpu.py --gpu-only` (RAPIDS cuDF)
- Deduplicates 1.9M genes → 30k unique (DISTINCT ON equivalent)
- Output: Deduplicated staging_screen_gene table

**Phase 2: CPU Load (~30 seconds)**
- Allocates 8 CPU cores (no GPU)
- Waits for Phase 1 via `--dependency=afterok:${PHASE_1_ID}`
- Runs `scripts/cpu_etl_load_only.py` (final transformations)
- Output: Final fact_screen_gene, gene, screen tables

**Cost Comparison:**
- Unified (both phases on GPU): $30/hour GPU × 0.5h = **$15 per run**
- Split (Phase 1 GPU, Phase 2 CPU): $30/h GPU × 0.008h + $2/h CPU × 0.008h = **$0.25 per run**
- **Savings: ~60× cheaper**

**Entry Points:**
- `slurm/reticle-etl-dedup-gpu.sh` — Phase 1 only (GPU dedup)
- `slurm/reticle-etl-load-cpu.sh` — Phase 2 only (CPU load, depends on Phase 1)
- `slurm/submit-etl-job-split.sh` — Wrapper to submit both
- `scripts/hpc_etl_gpu.py` — GPU dedup implementation
- `scripts/cpu_etl_load_only.py` — CPU load implementation

#### Workflow: Custom Control
```bash
# Phase 1 only (GPU dedup)
sbatch slurm/reticle-etl-dedup-gpu.sh 1
# Output: "Submitted batch job 54321"

# Phase 2 manually (if Phase 1 succeeded)
sbatch --dependency=afterok:54321 slurm/reticle-etl-load-cpu.sh 1

# Or use the wrapper to auto-chain
./slurm/submit-etl-job-split.sh 1 --both
```

---

## C. Minimum Configuration

### Local Development

Create `~/reticle.sh` and `source` before running:

```bash
#!/bin/bash
# Local development environment for RETICLE

export RETICLE_DIR=/Users/username/projects/RETICLE

# PostgreSQL (local or remote)
export DB_HOST=localhost                          # or: remote-db.example.com
export DB_PORT=5432
export DB_USER=postgres
export DB_NAME=reticle_biogrid
# DB_PASSWORD will be read from ~/.pgpass (recommended)
# OR: export DB_PASSWORD=<your-password>       # NOT recommended in scripts

# Data & Logs
export DATA_DIR=/path/to/biogrid/data            # TSV/JSON files
export LOG_DIR=${RETICLE_DIR}/logs
export LOG_LEVEL=INFO                             # DEBUG for verbose

# ETL tuning (optional, defaults shown)
# export ETL_BATCH_SIZE=10000                     # Rows per insert batch
# export ETL_COMMIT_INTERVAL=50000                # Rows before commit
export PIPELINE_VERSION=2026-06-09                # For logging/audit

# Optional
export VALIDATE_ON_LOAD=true                      # Skip invalid rows
export SKIP_INVALID_ROWS=true
```

**Setup Steps:**
1. Create `~/.pgpass` with credentials (mode 600):
   ```
   localhost:5432:reticle_biogrid:postgres:mypassword
   ```
2. Create `~/reticle.sh` (see template above)
3. Add to `~/.bashrc`: `source ~/reticle.sh` (optional, auto-load on login)

**Verify Configuration:**
```bash
source ~/reticle.sh
python3 scripts/validate_etl_readiness.py
# Output: ✓ All checks passed
```

---

### HPC (SLURM Cluster)

Create `/home/username/reticle.sh` and `source` before submitting jobs:

```bash
#!/bin/bash
# HPC environment for RETICLE on SLURM cluster

export RETICLE_DIR=/home/username/RETICLE

# SLURM Partitions (cluster-specific)
export RETICLE_PARTITION_CPU=general-cpu          # For CPU jobs
export RETICLE_PARTITION_GPU=general-gpu          # For GPU jobs

# PostgreSQL (RDS or on-cluster)
export DB_HOST=reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com
export DB_PORT=5432
export DB_USER=reticle_admin
export DB_NAME=reticle_biogrid
# DB_PASSWORD will be read from ~/.pgpass (MUST use this for HPC)

# Data & Logs (NFS-mounted)
export DATA_DIR=/storage3/fs1/aorvedahl-RETICLE/Active/data/latest_biogrid_screens
export LOG_DIR=${RETICLE_DIR}/logs
export LOG_LEVEL=INFO                             # DEBUG for verbose

# ETL tuning (optional, defaults shown)
# export ETL_BATCH_SIZE=10000
# export ETL_COMMIT_INTERVAL=50000
export PIPELINE_VERSION=2026-06-09

# Optional: GPU settings (for GPU jobs)
# export CUDA_VISIBLE_DEVICES=0                   # Use GPU 0 (set by SLURM)
# export RAPIDS_DEVICE_MEMORY_FRACTION=0.8        # GPU memory usage
```

**Setup Steps on HPC:**
1. Create `~/.pgpass` (mode 600):
   ```
   reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com:5432:reticle_biogrid:reticle_admin:password
   chmod 600 ~/.pgpass
   ```
2. Create `/home/username/reticle.sh` (see template above)
3. Clone RETICLE repo:
   ```bash
   mkdir -p /home/username/RETICLE
   cd /home/username/RETICLE
   git clone <repo> .
   ```
4. Create logs directory:
   ```bash
   mkdir -p /home/username/RETICLE/logs
   ```

**Verify Configuration:**
```bash
source ~/reticle.sh
cd ~/RETICLE
python3 scripts/validate_etl_readiness.py
# Output: ✓ All checks passed
```

**Test Job Submission:**
```bash
sbatch slurm/reticle-etl.sh 1
# Output: Submitted batch job 12345
# Check status: squeue -j 12345
# View output: cat logs/reticle-etl-12345.log
```

---

### Environment Variables Reference

| Variable | Local | HPC | Purpose |
|----------|-------|-----|---------|
| `RETICLE_DIR` | `/Users/username/projects/RETICLE` | `/home/username/RETICLE` | Root directory |
| `DB_HOST` | `localhost` or `remote-db.example.com` | `reticle-db.cn8saqya88cd...rds.amazonaws.com` | Database server |
| `DB_PORT` | `5432` | `5432` | Database port |
| `DB_USER` | `postgres` | `reticle_admin` | Database user |
| `DB_NAME` | `reticle_biogrid` | `reticle_biogrid` | Database name |
| `DB_PASSWORD` | From `~/.pgpass` (preferred) | From `~/.pgpass` (required) | **Never export** |
| `DATA_DIR` | `/Users/.../RETICLE/Domain/Data` | `/storage3/fs1/.../latest_biogrid_screens` | Input TSV/JSON files |
| `LOG_DIR` | `${RETICLE_DIR}/logs` | `${RETICLE_DIR}/logs` | Logs output |
| `LOG_LEVEL` | `INFO` or `DEBUG` | `INFO` or `DEBUG` | Logging verbosity |
| `PIPELINE_VERSION` | `2026-06-09` | `2026-06-09` | Version string for audit |
| `RETICLE_PARTITION_CPU` | N/A | `general-cpu` | SLURM CPU partition |
| `RETICLE_PARTITION_GPU` | N/A | `general-gpu` | SLURM GPU partition |
| `ETL_BATCH_SIZE` | `10000` (default) | `10000` (default) | Rows per batch insert |
| `ETL_COMMIT_INTERVAL` | `50000` (default) | `50000` (default) | Rows before commit |

---

## Quick Start Checklists

### ✓ Local Development (First Time)

- [ ] PostgreSQL installed and running (`psql --version`)
- [ ] Python 3.12+ installed (`python3 --version`)
- [ ] RETICLE repo cloned
- [ ] `~/.pgpass` created with database credentials (mode 600)
- [ ] `~/reticle.sh` created and customized for your paths
- [ ] `source ~/reticle.sh` before running scripts
- [ ] Test: `python3 scripts/validate_etl_readiness.py`
- [ ] Load data: `./warehouse-load.sh homo_sapiens`
- [ ] Run ETL: `./warehouse-run-etl.sh 1`
- [ ] Verify: `./warehouse-maintenance.sh --show-storage`

### ✓ HPC: CPU-Only (First Time)

- [ ] SSH access to HPC cluster
- [ ] RETICLE repo cloned to `/home/username/RETICLE`
- [ ] NFS data mounted at `$DATA_DIR`
- [ ] `~/.pgpass` created with RDS credentials (mode 600)
- [ ] `~/reticle.sh` created and customized for HPC paths
- [ ] `mkdir -p ~/RETICLE/logs`
- [ ] Test: `source ~/reticle.sh && python3 ~/RETICLE/scripts/validate_etl_readiness.py`
- [ ] Submit job: `sbatch ~/RETICLE/slurm/reticle-etl.sh 1`
- [ ] Monitor: `squeue -u $USER && tail -f ~/RETICLE/logs/reticle-etl-*.log`

### ✓ HPC: CPU + GPU (First Time)

- [ ] All HPC: CPU-Only steps completed
- [ ] GPU nodes available in `RETICLE_PARTITION_GPU`
- [ ] RAPIDS/cuDF dependencies installed (or auto-loaded via module)
- [ ] Test GPU: `sbatch ~/RETICLE/slurm/reticle-etl-dedup-gpu.sh 1`
- [ ] Monitor both phases: `squeue -u $USER`
- [ ] View logs: `ls ~/RETICLE/logs/reticle-etl-*.log`

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'config'"
**Cause:** Running from wrong directory
```bash
cd /path/to/RETICLE/scripts
python3 staging_loader.py ...  # ✓ Works
cd /elsewhere
python3 scripts/staging_loader.py ...  # ✓ Works
python3 staging_loader.py ...  # ✗ Fails (can't find config.py)
```

### "psycopg2.OperationalError: FATAL: password authentication failed"
**Cause:** `~/.pgpass` missing or incorrect
```bash
# Verify ~/.pgpass exists and has correct permissions
ls -l ~/.pgpass                    # Should be -rw------- (600)
cat ~/.pgpass | grep DB_HOST       # Check for database line
chmod 600 ~/.pgpass                # Fix permissions if needed
```

### "no such table: staging_screen" on HPC
**Cause:** Staging loader didn't run; ETL tried to run on empty database
```bash
# Run staging first:
sbatch slurm/reticle-etl.sh 1      # Runs both staging + ETL

# Or manually:
sbatch slurm/reticle-etl.sh 1 --stage-only    # Staging only
sbatch slurm/reticle-etl.sh 1 --etl-only      # ETL only (after staging)
```

### GPU job fails: "CUDA_ERROR_NOT_INITIALIZED"
**Cause:** GPU libraries not loaded or RAPIDS not installed
```bash
# On HPC, load GPU modules:
module load cuda
module load rapids  # or: conda activate rapids-env
sbatch slurm/reticle-etl-dedup-gpu.sh 1
```

### Job takes too long / hangs
**Cause:** Check logs and monitor memory/CPU
```bash
# View real-time logs
tail -f ~/RETICLE/logs/reticle-etl-${JOB_ID}.log

# Check job status
scontrol show job ${JOB_ID}

# Kill if needed
scancel ${JOB_ID}
```

---

## Next Steps

- Read [scripts/README.md](scripts/README.md) for Python script details
- Read [slurm/README.md](slurm/README.md) for SLURM job details
- For development: run local pipeline with `warehouse-load.sh` + `warehouse-run-etl.sh`
- For production HPC: submit with `sbatch slurm/reticle-etl.sh <version>` or split pipeline
- For maintenance: use `./warehouse-maintenance.sh` commands
