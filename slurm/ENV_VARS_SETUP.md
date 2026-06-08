# Environment Variables Setup

RETICLE scripts use environment variables for maximum portability across users and systems.

---

## Key Environment Variables

### `RETICLE_DIR` (Required)

Path to the RETICLE project root directory.

```bash
# Example paths
export RETICLE_DIR=/Volumes/SD\ Media/projects/RETICLE      # macOS
export RETICLE_DIR=$HOME/projects/RETICLE                    # Linux home
export RETICLE_DIR=/scratch/user/RETICLE                     # HPC scratch
export RETICLE_DIR=/gscratch/user/RETICLE                    # NERSC
```

### `DATA_DIR` (Optional)

Path to raw data directory. Default: `$RETICLE_DIR/Domain/Data`

```bash
export DATA_DIR=/scratch/datasets/biogrid-orcs
```

---

## Setup by Environment

### Development (macOS/Linux Workstation)

**Option 1: Add to `~/.bashrc` or `~/.zshrc`**

```bash
# Add this line to ~/.bashrc
export RETICLE_DIR=/Volumes/SD\ Media/projects/RETICLE

# Or if in home directory
export RETICLE_DIR=$HOME/projects/RETICLE

# Reload shell
source ~/.bashrc
```

**Option 2: Set in current shell**

```bash
export RETICLE_DIR=/Volumes/SD\ Media/projects/RETICLE
cd $RETICLE_DIR/slurm
./submit-etl-job.sh 2
```

---

### WashU C2 HPC Cluster

**Recommended: Add to `~/.bashrc` on login node**

```bash
# Edit ~/.bashrc on C2
nano ~/.bashrc

# Add this at the end:
export RETICLE_DIR=$HOME/projects/RETICLE

# Save and reload
source ~/.bashrc
```

**Verify it's set:**

```bash
echo $RETICLE_DIR
# Should output: /home/arifs/projects/RETICLE

# If RETICLE is installed there, use it
ls $RETICLE_DIR/slurm/submit-etl-job.sh
```

**Then submit jobs normally:**

```bash
cd $RETICLE_DIR/slurm
./submit-etl-job.sh 2
```

---

### XSEDE/ACCESS Clusters (Stampede3, Frontera, Bridges)

```bash
# ~/.bashrc on login node
export RETICLE_DIR=$WORK/RETICLE           # Using WORK allocation
# or
export RETICLE_DIR=$SCRATCH/RETICLE        # Using SCRATCH allocation
```

---

### NERSC (Perlmutter, Cori)

```bash
# ~/.bashrc on login node
export RETICLE_DIR=$PSCRATCH/RETICLE       # Using project scratch
```

---

### Multiple Users on Same System

Each user sets their own `RETICLE_DIR`:

```bash
# User 1 (arifs)
# ~/.bashrc
export RETICLE_DIR=/home/arifs/RETICLE

# User 2 (collaborator)
# ~/.bashrc
export RETICLE_DIR=/home/collaborator/RETICLE
```

Each uses their own installation path, preventing conflicts.

---

## How Environment Variables Flow

```
1. User sets environment variable
   export RETICLE_DIR=/path/to/RETICLE

2. User submits job
   ./submit-etl-job.sh 2

3. submit-etl-job.sh reads RETICLE_DIR and passes to SLURM
   sbatch --export=RETICLE_DIR=/path/to/RETICLE,VERSION_ID=2

4. Compute node receives variable
   Runs reticle-etl.sh with RETICLE_DIR=/path/to/RETICLE

5. Scripts use RETICLE_DIR to find all paths
   SCRIPTS_DIR=$RETICLE_DIR/scripts
   LOGS_DIR=$RETICLE_DIR/logs
```

---

## Fallback Behavior

If `RETICLE_DIR` is not set, scripts auto-detect:

```bash
# Auto-detect from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
```

**This works on single-machine setups but may fail on HPC if paths differ between nodes.** Always set `RETICLE_DIR` explicitly on HPC clusters.

---

## Verification

Check that environment is set correctly:

```bash
# Before submitting job
echo "RETICLE_DIR=$RETICLE_DIR"
ls $RETICLE_DIR/scripts/hpc_etl_pipeline.py
ls $RETICLE_DIR/slurm/env-setup.sh

# Should all succeed
```

If any `ls` fails, fix the path:

```bash
# Find where RETICLE actually is
find $HOME -name "hpc_etl_pipeline.py" -type f

# Update RETICLE_DIR accordingly
export RETICLE_DIR=/actual/path/to/RETICLE
```

---

## Troubleshooting

### "env-setup.sh not found"

```bash
# Check RETICLE_DIR
echo $RETICLE_DIR

# Verify path exists
ls $RETICLE_DIR/slurm/env-setup.sh

# If not set
export RETICLE_DIR=/correct/path
```

### "Module not found: config"

```bash
# Check SCRIPTS_DIR is correct
echo $RETICLE_DIR/scripts

# Verify config.py exists
ls $RETICLE_DIR/scripts/config.py
```

### "Permission denied" on compute node

```bash
# Check path is on shared filesystem (not local to login node)
# Examples of shared filesystems:
# - /home/* (usually shared)
# - /scratch/* (usually shared)
# - /work/* (XSEDE)
# - /pscratch/* (NERSC)

# Examples of LOCAL filesystems (don't work on compute nodes):
# - /Volumes/* (macOS local)
# - /tmp/* (local temp)
# - /dev/shm/* (local memory)
```

If RETICLE is on a local filesystem, move it to shared:

```bash
# Example: move from local to shared
cp -r /Volumes/SD\ Media/projects/RETICLE $HOME/RETICLE
export RETICLE_DIR=$HOME/RETICLE
```

---

## Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `RETICLE_DIR` | Project root | `/home/arifs/RETICLE` |
| `SCRIPTS_DIR` | Python scripts | `$RETICLE_DIR/scripts` |
| `LOGS_DIR` | Job logs | `$RETICLE_DIR/logs` |
| `DATA_DIR` | Raw data | `$RETICLE_DIR/Domain/Data` |

---

## Summary

1. **Set `RETICLE_DIR`** in `~/.bashrc`:
   ```bash
   export RETICLE_DIR=/path/to/RETICLE
   ```

2. **Reload shell**:
   ```bash
   source ~/.bashrc
   ```

3. **Verify**:
   ```bash
   echo $RETICLE_DIR
   ls $RETICLE_DIR/slurm/submit-etl-job.sh
   ```

4. **Submit jobs**:
   ```bash
   cd $RETICLE_DIR/slurm
   ./submit-etl-job.sh 2
   ```

**Done!** Scripts now work across all systems and users. 🚀
