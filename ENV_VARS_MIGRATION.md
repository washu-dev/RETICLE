# Environment Variables Refactor Complete

Upgraded RETICLE scripts to use **environment variables** for maximum portability across users and systems.

---

## Why Environment Variables?

| Approach | Hardcoded Path | Relative Path | Env Variables |
|----------|---|---|---|
| **Portability** | ❌ Single user | ⚠️ Shared filesystem | ✅ Universal |
| **Multi-user** | ❌ No | ⚠️ Complex | ✅ Yes |
| **HPC clusters** | ❌ Login-only | ⚠️ Assumes structure | ✅ Yes |
| **Different systems** | ❌ No | ⚠️ Relative to script | ✅ Yes |
| **Explicit** | ❌ Hidden | ⚠️ Implicit | ✅ Clear |

---

## What Changed

### Before ❌

**Hardcoded paths** in job scripts:
```bash
RETICLE_DIR="/Volumes/SD Media/projects/RETICLE"  # Only works on one machine
SCRIPTS_DIR="$RETICLE_DIR/scripts"
```

**Problems:**
- Only worked for one user
- Only worked on one machine
- Breaks on HPC with different filesystem mounts
- Different users on same HPC can't share scripts

### After ✅

**Environment variables** with fallback:
```bash
# Use environment variable (set by user)
if [ -z "$RETICLE_DIR" ]; then
    # Fallback: auto-detect from script location
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    RETICLE_DIR="$(dirname "$SCRIPT_DIR")"
fi

SCRIPTS_DIR="$RETICLE_DIR/scripts"
```

**Benefits:**
- Works for all users
- Works on all systems
- Works on all HPC clusters
- Explicit and configurable
- Fallback for convenience

---

## Files Updated

### 1. `slurm/submit-etl-job.sh`
- Reads `RETICLE_DIR` from environment
- Auto-detects if not set
- **Passes to SLURM via `--export`**
  ```bash
  sbatch --export=RETICLE_DIR=$RETICLE_DIR,VERSION_ID=2
  ```

### 2. `slurm/reticle-etl.sh`
- Receives `RETICLE_DIR` from SLURM
- Uses it to find all paths
- Fallback auto-detect if not set

### 3. `slurm/reticle-etl-gpu.sh`
- Same environment variable approach

### 4. `slurm/ENV_VARS_SETUP.md` (NEW)
- Complete guide to setting environment variables
- Examples for all systems (macOS, HPC clusters)
- Troubleshooting section

### 5. `slurm/WASHIU_C2_SETUP.md` (UPDATED)
- Added Step 0: Set environment variables
- Links to `ENV_VARS_SETUP.md`

---

## Usage

### For Users

**One-time setup:**

```bash
# Add to ~/.bashrc
export RETICLE_DIR=$HOME/projects/RETICLE

# Reload
source ~/.bashrc

# Verify
echo $RETICLE_DIR
```

**Then use normally:**

```bash
cd $RETICLE_DIR/slurm
./submit-etl-job.sh 2
```

### How It Works

```
User ~/.bashrc:
  export RETICLE_DIR=/home/arifs/RETICLE

submit-etl-job.sh:
  Reads $RETICLE_DIR
  Passes to SLURM: --export=RETICLE_DIR=/home/arifs/RETICLE,VERSION_ID=2

SLURM job on compute node:
  reticle-etl.sh receives RETICLE_DIR
  Uses it to find scripts, logs, data
  No hardcoded paths needed
```

---

## Flexible Paths

Users can place RETICLE anywhere:

```bash
# User 1: Home directory
export RETICLE_DIR=$HOME/projects/RETICLE

# User 2: Shared project directory
export RETICLE_DIR=/project/shared/RETICLE

# User 3: HPC scratch
export RETICLE_DIR=$SCRATCH/RETICLE

# User 4: Different HPC system
export RETICLE_DIR=$GSCRATCH/RETICLE
```

All work with the same scripts, no modifications needed.

---

## Multi-User on Same System

```bash
# User 1 (arifs)
# ~/.bashrc
export RETICLE_DIR=/home/arifs/RETICLE

# User 2 (collaborator)
# ~/.bashrc
export RETICLE_DIR=/home/collaborator/RETICLE

# Both run the same scripts
cd $RETICLE_DIR/slurm
./submit-etl-job.sh 2
```

Each user's jobs use their own RETICLE installation. No conflicts.

---

## Fallback Behavior

If `RETICLE_DIR` not set, scripts auto-detect:

```bash
# This works on:
# ✅ Single-machine development (macOS, Linux)
# ✅ Same filesystem on all nodes

# This may fail on:
# ❌ HPC where login/compute nodes have different mounts
# ❌ Different user installations
```

**Best practice:** Always set `RETICLE_DIR` on HPC clusters.

---

## Documentation

- **Setup guide:** `slurm/ENV_VARS_SETUP.md` — How to set environment variables
- **WashU C2:** `slurm/WASHIU_C2_SETUP.md` — C2-specific instructions
- **General SLURM:** `docs/SLURM_GUIDE.md`

---

## Backward Compatible

Existing scripts still work:

```bash
# All these work:

# 1. With environment variable set
export RETICLE_DIR=/path/to/RETICLE
cd /path/to/RETICLE/slurm
./submit-etl-job.sh 2

# 2. Without environment variable (auto-detects)
cd /path/to/RETICLE/slurm
./submit-etl-job.sh 2

# 3. From anywhere (if RETICLE_DIR set)
./submit-etl-job.sh 2
```

No breaking changes.

---

## Next Steps

1. **Set `RETICLE_DIR`** in `~/.bashrc`:
   ```bash
   export RETICLE_DIR=$HOME/projects/RETICLE
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

4. **Submit jobs normally**:
   ```bash
   cd $RETICLE_DIR/slurm
   ./submit-etl-job.sh 2
   ```

---

## Summary

✅ **Environment variables** make scripts portable across all users and systems  
✅ **Explicit configuration** instead of hidden hardcoded paths  
✅ **Fallback auto-detect** for convenience  
✅ **Multi-user support** — each user uses their own installation  
✅ **HPC-ready** — works on any cluster with proper configuration  

**Much better than hardcoded or relative paths!** 🚀

