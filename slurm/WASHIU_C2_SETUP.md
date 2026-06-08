# RETICLE ETL Setup on WashU C2

Complete setup guide for WashU's C2 HPC cluster.

---

## Quick Start (5 Minutes)

### Step 1: Create PostgreSQL Credentials

On C2 login node:

```bash
cat > ~/.pgpass <<'EOF'
your.postgres.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD
EOF

chmod 600 ~/.pgpass
```

### Step 2: Test Environment Setup

```bash
cd /Volumes/SD Media/projects/RETICLE/slurm

# Run environment setup (creates Python venv automatically)
./env-setup.sh

# Output should show:
# ✓ pandas: Data deduplication
# ✓ numpy: Numerical computing
# ✓ psycopg2: PostgreSQL driver
# ✓ .pgpass found with correct permissions (600)
```

### Step 3: Submit Your First Job

```bash
# CPU job (8 cores, 30 min)
./submit-etl-job.sh 2

# Or GPU job (if available)
./submit-etl-job.sh 2 --gpu
```

### Step 4: Monitor

```bash
# Watch output
./monitor-etl-jobs.sh <job_id> tail

# View complete log
./monitor-etl-jobs.sh <job_id> log
```

---

## WashU C2 Specific Info

### Available Modules

```bash
# Python versions
python3     (default Python 3.x)
python39    (Python 3.9)

# Check for CUDA
module avail cuda

# Check for other tools
module avail
```

### Load Modules

```bash
# Load Python 3 (default)
module load python3

# Or Python 3.9
module load python39
```

### Virtual Environment

Scripts automatically create a Python virtual environment:

```
~/.reticle-etl-venv/          (CPU jobs)
~/.rapids-gpu-venv/            (GPU jobs, if RAPIDS installed)
```

These are created once and reused. To recreate, delete them:

```bash
rm -rf ~/.reticle-etl-venv
rm -rf ~/.rapids-gpu-venv
# Next job will recreate them
```

### CUDA/GPU Setup

Check if CUDA is available:

```bash
# See CUDA modules
module avail cuda

# Load CUDA if available
module load cuda/12.0  # or whatever version is available
```

If you want GPU acceleration, ensure `nvidia-smi` works:

```bash
# On GPU node (after job starts)
nvidia-smi

# Should show GPU info
```

---

## Network Details

### Database Connection

If your database is on WashU internal network:

```bash
# .pgpass entry
postgres.example.wustl.edu:5432:reticle_biogrid:reticle_admin:password
```

### Firewall

C2 login and compute nodes should have outbound network access. If you get "connection refused" errors:

1. Verify database is reachable from login node:
   ```bash
   nc -zv your.postgres.host 5432
   # Should say: succeeded
   ```

2. Check that credentials are correct in `.pgpass`

3. Ask C2 admin if firewall needs opening for your database host

---

## Common Tasks

### Submit CPU Job

```bash
./submit-etl-job.sh 2                    # 8 cores, default
./submit-etl-job.sh 2 --cores 16         # 16 cores
./submit-etl-job.sh 2 --cores 32 --mem 128   # 32 cores, 128GB
```

### Submit GPU Job

```bash
# Check if GPUs available on C2
sinfo --gres

# Submit GPU job
./submit-etl-job.sh 2 --gpu              # 1 GPU
./submit-etl-job.sh 2 --gpu --gpus 2     # 2 GPUs
```

### Check Job Queue

```bash
squeue -u $USER              # Your jobs
squeue -n "reticle-etl*"     # All RETICLE jobs
```

### Cancel Job

```bash
scancel <job_id>
```

---

## Troubleshooting

### "Conda not found" → This is Normal

WashU C2 doesn't have conda. Our scripts now use Python `venv` instead (built-in to Python 3, works on all clusters).

**Expected behavior:**
```
Setting up environment...
  Loading python module...
  Conda not found, using Python venv...
  Creating virtual environment at ~/.reticle-etl-venv...
  ✓ pandas: Data deduplication
  ✓ numpy: Numerical computing
  ✓ psycopg2: PostgreSQL driver
  ✓ .pgpass found
```

### "module load python3" fails

```bash
# C2 uses Lmod module system
module load python3

# If that fails, try:
module load python39

# Or check what's available:
module avail python
```

### "GPU not accessible" (GPU job)

```bash
# Check if CUDA module exists
module avail cuda

# Load CUDA
module load cuda  # (or specific version)

# Test on compute node (inside job)
nvidia-smi
```

If `nvidia-smi` fails inside GPU job, the compute node may not have GPU. Check:

```bash
# In your SLURM job, what GPU did I get?
echo $SLURM_GPUS_ON_NODE
```

### Virtual Environment Issues

If you get "command not found: python" inside job:

```bash
# Source the venv manually (normally done by env-setup.sh)
source ~/.reticle-etl-venv/bin/activate

# Or delete and let script recreate
rm -rf ~/.reticle-etl-venv
# Next job will recreate it
```

### "psycopg2: connection refused"

1. Check .pgpass exists and permissions are 600:
   ```bash
   ls -l ~/.pgpass
   # Should show: -rw------- 1 arifs arifs
   ```

2. Test connection from login node:
   ```bash
   psql -h your.postgres.host -U reticle_admin -d reticle_biogrid -c "SELECT 1"
   # Should succeed
   ```

3. Check database host is reachable:
   ```bash
   nc -zv your.postgres.host 5432
   # Should say: succeeded
   ```

---

## Performance Estimates

### Mouse Dataset (1.9M genes)

| CPUs | Time | Speedup |
|------|------|---------|
| 8 | 15 sec | 1x |
| 16 | 8 sec | 2x |
| 32 | 5 sec | 3x |

### GPU (if available)

| GPUs | Time | Speedup |
|------|------|---------|
| 1 | 5 sec | 3x |
| 2 | 3 sec | 5x |

---

## Files

- `env-setup.sh` — Auto-creates Python venv, loads packages
- `submit-etl-job.sh` — Submits job to SLURM
- `monitor-etl-jobs.sh` — Monitors running jobs
- `reticle-etl.sh` — SLURM job script (CPU)
- `reticle-etl-gpu.sh` — SLURM job script (GPU)
- `PGPASS_SETUP.md` — Detailed .pgpass setup
- `README.md` — General SLURM guide

---

## Next Steps

1. ✅ Create `~/.pgpass` on C2
2. ✅ Test: `./env-setup.sh`
3. ✅ Submit job: `./submit-etl-job.sh 2`
4. ✅ Monitor: `./monitor-etl-jobs.sh <job_id>`

**You're ready to go!** 🚀
