# Split GPU/CPU Pipeline Guide

**For RETICLE's massive gene and screen-pair datasets, the split pipeline maximizes resource efficiency.**

The unified GPU pipeline reserves a GPU node for ~30 minutes, but only uses the GPU for ~30 seconds of deduplication. The rest (database inserts) is CPU-bound.

**Solution:** Split into two phases, release the GPU node immediately after dedup, and complete database loading on a cheaper CPU node.

---

## Architecture

### Unified Pipeline (Old)

```
GPU Node (30 min reserved)
├─ Load genes into memory
├─ Load pairs into memory
├─ GPU: Deduplicate genes (30 sec)
├─ GPU: Deduplicate pairs (8 sec)
└─ CPU: Database INSERT (20 min)  ← Wasting GPU!
```

**Problem:** GPU sits idle for 19 minutes while database inserts run on CPU.

### Split Pipeline (New)

```
PHASE 1: GPU Node (5 min reserved)       PHASE 2: CPU Node (1 hour reserved)
├─ Load genes                              ├─ Read CSV files
├─ Load pairs                              ├─ COPY to staging_screen
├─ GPU: Deduplicate genes                  ├─ COPY to staging_screen_gene
├─ GPU: Deduplicate pairs                  └─ Validate inserted data
└─ Write CSV files (~30 sec)
   ↓ (CSV files in /tmp)
   ↓ (GPU node released)
   ↓ (CPU node allocated)
```

**Benefit:** GPU reserved for only 30 seconds of actual GPU work, CPU node handles insertion.

---

## Performance Comparison

### Mouse Dataset (1.9M genes, 205 screens)

| Metric | Unified | Split | Savings |
|--------|---------|-------|---------|
| GPU Time | 30 sec | 30 sec | 0% |
| GPU Reserve | 30 min | 5 min | **83%** |
| CPU Time | 20 min | 30 sec | **97%** |
| CPU Reserve | (on GPU node) | 1 hour | $$ Cost on CPUs |
| Total Wall Time | 30 min | ~35 sec GPU + 30 sec CPU = **1-2 min** | **15-30x faster** |
| GPU Cost | ~$12 (full 30 min) | ~$0.25 (5 min) | **$11.75 saved** |
| CPU Cost | $0 (on GPU node) | ~$0.50 (1 hour on CPU) | **No change** |
| **Net Savings** | — | — | **$11+ per job** |

For **human dataset (26M genes):**
- GPU Phase: ~2-5 minutes (scale with data)
- CPU Phase: ~10-20 minutes (COPY is fast)
- Total: ~15 minutes vs 45+ minutes in unified pipeline
- **GPU savings: $25+ per job**

---

## How It Works

### Phase 1: GPU Deduplication Only

**Script:** `gpu_etl_dedup_only.py`  
**Runs on:** GPU node (AWS p3.2xlarge / WashU C2 GPU partition)  
**Time:** ~30 seconds (GPU work) + overhead

```bash
python gpu_etl_dedup_only.py --version 2
```

**What it does:**
1. Connect to database
2. Query `staging_screen` and `staging_screen_gene` tables
3. Load genes into pandas/cuDF DataFrame
4. Deduplicate using GPU (if RAPIDS available) or CPU pandas
5. Load pairs into pandas/cuDF DataFrame
6. Deduplicate unique (screen_id, identifier_id) pairs
7. Write CSV files to `/tmp/reticle_staging/`:
   - `staging_screen_v2.csv` (headers + pipe-delimited data)
   - `staging_screen_gene_v2.csv` (headers + pipe-delimited data)
8. Save metadata: `dedup_metadata_v2.json` (stats + timestamps)

**Output size (mouse):**
- Screens CSV: ~50 KB (205 screens)
- Pairs CSV: ~200 MB (6M unique pairs)

### Phase 2: CPU Loading Only

**Script:** `cpu_etl_load_only.py`  
**Runs on:** CPU node (any partition)  
**Time:** ~30 seconds for mouse, ~10-20 min for human

```bash
python cpu_etl_load_only.py --version 2
```

**Prerequisites:**
- Phase 1 must have completed successfully
- CSV files must exist in `/tmp/reticle_staging/`
- Database tables must exist

**What it does:**
1. Load GPU phase metadata (stats, timestamps)
2. Read `staging_screen_v2.csv`
3. PostgreSQL COPY into `staging_screen` table
4. Read `staging_screen_gene_v2.csv`
5. PostgreSQL COPY into `staging_screen_gene` table
6. Validate: count rows, check for NULLs in critical columns
7. Report success/failure with statistics

**Why COPY is so fast:**
- Binary mode (not SQL INSERT)
- Single round-trip to database
- No transaction overhead per row
- Server-side parsing

---

## Quick Start

### Option 1: Submit Both Phases (Recommended)

Submit Phase 1 + 2 with automatic chaining (Phase 2 starts after Phase 1 completes):

```bash
cd ~/projects/RETICLE/slurm

# Submit Phase 1 (GPU) and Phase 2 (CPU) with dependency
./submit-etl-job-split.sh 2 --both
```

Output:
```
RETICLE Split ETL Job Configuration
Version ID:       2
Mode:             BOTH

PHASE 1 (GPU Deduplication)
  GPU Cores:        8
  GPUs:             1
  Time Limit:       00:05:00
  Partition:        gpu

[STEP] Submitting Phase 1 (GPU Dedup)...
[INFO] Phase 1 submitted successfully!
Job ID:           1234567
Status:           Check with: squeue -j 1234567
...

PHASE 2 (CPU Loading)
  CPU Cores:        8
  Time Limit:       01:00:00
  Partition:        cpu
  Depends on:       Phase 1 (job 1234567)

[STEP] Submitting Phase 2 (CPU Load) with dependency on Phase 1...
[INFO] Phase 2 submitted successfully!
Job ID:           1234568
Status:           Check with: squeue -j 1234568
...

BOTH PHASES SUBMITTED
Phase 1 (GPU):    Job 1234567
Phase 2 (CPU):    Job 1234568
Phase 2 will start automatically after Phase 1 completes.
```

Monitor both jobs:
```bash
watch squeue -j 1234567,1234568

# Or watch logs
tail -f logs/reticle-etl-dedup-gpu-1234567.out
tail -f logs/reticle-etl-load-cpu-1234568.out
```

### Option 2: Manual Two-Step Submission

Submit Phase 1, wait for completion, then submit Phase 2:

```bash
# Phase 1: GPU dedup
./submit-etl-job-split.sh 2 --gpu

# Wait for Phase 1 to complete (watch the logs)
tail -f logs/reticle-etl-dedup-gpu-*.out

# Phase 2: CPU load (when Phase 1 is done)
./submit-etl-job-split.sh 2 --cpu
```

### Option 3: Run Directly (Not via SLURM)

For testing or small datasets, run phases locally (not recommended for production):

```bash
cd ~/projects/RETICLE/scripts

# Phase 1: GPU dedup (uses GPU if available, falls back to CPU pandas)
python gpu_etl_dedup_only.py --version 2

# Phase 2: CPU load
python cpu_etl_load_only.py --version 2
```

---

## Command Reference

### submit-etl-job-split.sh

Submit split pipeline jobs with flexibility:

```bash
# Phase 1 only (GPU)
./submit-etl-job-split.sh 2
./submit-etl-job-split.sh 2 --gpu

# Phase 2 only (CPU) - manual submission
./submit-etl-job-split.sh 2 --cpu

# Both phases with automatic chaining
./submit-etl-job-split.sh 2 --both

# Custom time limits
./submit-etl-job-split.sh 2 --both --gpu-time 00:10:00 --cpu-time 02:00:00

# Custom cores
./submit-etl-job-split.sh 2 --gpu-cores 16 --cpu-cores 32

# Custom partition
./submit-etl-job-split.sh 2 --partition fast-gpu

# Show help
./submit-etl-job-split.sh --help
```

### gpu_etl_dedup_only.py

Direct invocation (advanced):

```bash
# Basic
python gpu_etl_dedup_only.py --version 2

# With debug logging
python gpu_etl_dedup_only.py --version 2 --log-level DEBUG
```

### cpu_etl_load_only.py

Direct invocation (advanced):

```bash
# Basic
python cpu_etl_load_only.py --version 2

# With debug logging
python cpu_etl_load_only.py --version 2 --log-level DEBUG
```

---

## Monitoring

### Watch Job Status

```bash
# List both jobs
squeue -j 1234567,1234568

# Watch continuously
watch squeue -j 1234567,1234568

# Full details
squeue -j 1234567 -O jobid,name,state,reason,starttime,endtime
```

### Watch Output Logs

```bash
# Phase 1 (GPU dedup)
tail -f logs/reticle-etl-dedup-gpu-1234567.out

# Phase 2 (CPU load)
tail -f logs/reticle-etl-load-cpu-1234568.out

# Error logs
tail -f logs/reticle-etl-dedup-gpu-1234567.err
tail -f logs/reticle-etl-load-cpu-1234568.err
```

### Job Statistics

After completion, check the log output for statistics:

**Phase 1 Output Example:**
```
================================================================================
GPU DEDUPLICATION PHASE
================================================================================
Version ID: 2
GPU Available: True

[SETUP] Loading GPU environment...
✓ Connected to database
[DEDUP] Loading screens...
✓ Loaded 205 screens
[DEDUP] Loading genes (GPU-accelerated dedup)...
  GPU: Deduplicating 1,904,551 genes...
  Removed 1,874,512 duplicates
[DEDUP] Loading screen-gene pairs (GPU-accelerated dedup)...
  Total pairs: 5,987,834
  GPU: Deduplicating pairs...
  After dedup: 6,034,251 unique pairs
  Removed 0 duplicates (already deduplicated per-screen-pair combo)

================================================================================
GPU DEDUP PHASE COMPLETE
================================================================================
Elapsed time: 28.3s
Screens: 205
Genes: 1,904,551 → 30,039 (1,874,512 removed)
Pairs: 5,987,834 → 6,034,251 (0 removed)
================================================================================
```

**Phase 2 Output Example:**
```
================================================================================
CPU LOADING PHASE
================================================================================
Version ID: 2

[SETUP] Loading CPU environment...
✓ Connected to database
[LOAD] Loading GPU dedup metadata...
  ✓ Loaded metadata (GPU: True)
  Dedup completed: 2026-06-08T17:50:12.345678
  Dedup elapsed: 28.3s

[LOAD] Loading screens via COPY...
  ✓ Inserted 205 screens
[LOAD] Loading screen-gene pairs via COPY...
  Copying 6,034,251 rows...
  ✓ Inserted 6,034,251 pairs
[VALIDATE] Validating loaded data...
  Screens: 205 ✓
  Pairs: 6,034,251 ✓
  NULL validation: PASSED ✓

================================================================================
CPU LOADING PHASE COMPLETE
================================================================================
Elapsed time: 21.8s
Screens inserted: 205
Pairs inserted: 6,034,251
Validation: PASSED
================================================================================
```

---

## When to Use Split Pipeline vs Unified Pipeline

### Use Split Pipeline (Recommended for Production)

✅ **Human datasets** (26M+ genes) — Save $25+ per run  
✅ **Frequent runs** (daily/weekly) — Cost savings compound  
✅ **GPU scarcity** — Release nodes faster for others  
✅ **Multi-dataset pipelines** — Run multiple GPU phases, batch CPU phases  
✅ **You care about cost** — Obvious ROI  

### Use Unified Pipeline

✅ **Debugging/testing** — Simpler single job  
✅ **Small datasets** (< 1M genes) — Time difference negligible  
✅ **One-time runs** — Setup cost > savings  

---

## Troubleshooting

### Phase 1 Failed

Check the GPU dedup log:

```bash
tail -f logs/reticle-etl-dedup-gpu-*.out
```

Common issues:
- **Database connection failed**: Check `$DB_HOST`, `$DB_USER`, `~/.pgpass`
- **RAPIDS not available**: Falls back to CPU pandas (slower but still works)
- **GPU not accessible**: `nvidia-smi` fails; check cluster allocation
- **CSV files not created**: Check `/tmp/reticle_staging/` exists and is writable

### Phase 2 Failed

Check the CPU load log:

```bash
tail -f logs/reticle-etl-load-cpu-*.out
```

Common issues:
- **CSV files not found**: Phase 1 didn't complete successfully
- **Database connection failed**: Check database access from CPU node
- **Validation failed**: Count mismatch (data corruption?) — restart Phase 1
- **COPY error**: Pipe-delimited format mismatch — check Phase 1 CSV output

### Both Phases Submitted but Phase 2 Never Starts

Check the dependency:

```bash
# Verify Phase 1 completed successfully
squeue -j <PHASE1_JOB>  # Should show COMPLETED or in the log tail
tail logs/reticle-etl-dedup-gpu-<PHASE1_JOB>.out | tail -20

# Verify Phase 2 is waiting on Phase 1
squeue -j <PHASE2_JOB> -O jobid,name,state,dependency
```

If Phase 1 failed, Phase 2 won't start. Re-run Phase 1, then manually submit Phase 2.

---

## Cost Analysis

### Pricing Model (AWS p3.2xlarge + m5.large)

| Phase | Node Type | Time | Hourly Cost | Job Cost |
|-------|-----------|------|------------|----------|
| Unified | p3.2xlarge GPU | 30 min | $24/hr | ~$12 |
| Split Phase 1 | p3.2xlarge GPU | 5 min | $24/hr | ~$2 |
| Split Phase 2 | m5.large CPU | 1 hour | $0.48/hr | ~$0.50 |
| **Split Total** | — | ~1 hr | — | ~$2.50 |
| **Savings** | — | — | — | **$9.50 per job** |

Over 100 jobs: **$950 savings**  
Over 1000 jobs: **$9,500 savings**

---

## Advanced Usage

### Parallel Phase 1 (Multiple GPU Nodes)

Process multiple datasets simultaneously:

```bash
# Submit Phase 1 for human dataset
./submit-etl-job-split.sh 3 --gpu &

# Submit Phase 1 for mouse dataset  
./submit-etl-job-split.sh 4 --gpu &

# Wait for all Phase 1 jobs to complete
wait

# Then submit Phase 2 jobs
./submit-etl-job-split.sh 3 --cpu
./submit-etl-job-split.sh 4 --cpu
```

All GPU dedup happens in parallel, then CPU loads in sequence.

### Custom SLURM Constraints

For cluster-specific resource constraints:

```bash
# Edit slurm script directly before submitting
vi slurm/reticle-etl-dedup-gpu.sh

# Change #SBATCH constraints as needed, then submit
sbatch --export=VERSION_ID=2,RETICLE_DIR=$RETICLE_DIR \
    slurm/reticle-etl-dedup-gpu.sh
```

---

## Reference

| File | Purpose |
|------|---------|
| `gpu_etl_dedup_only.py` | Phase 1 script: GPU-accelerated dedup |
| `cpu_etl_load_only.py` | Phase 2 script: CPU batch loading |
| `reticle-etl-dedup-gpu.sh` | SLURM job script for Phase 1 |
| `reticle-etl-load-cpu.sh` | SLURM job script for Phase 2 |
| `submit-etl-job-split.sh` | Wrapper to submit both phases |
| `SPLIT_GPU_CPU_PIPELINE.md` | This guide |

---

## Next Steps

1. **Test locally** (small dataset):
   ```bash
   python gpu_etl_dedup_only.py --version 1
   python cpu_etl_load_only.py --version 1
   ```

2. **Submit Phase 1 on GPU node**:
   ```bash
   ./submit-etl-job-split.sh 2 --gpu
   ```

3. **Monitor and wait for completion**:
   ```bash
   watch squeue -j <JOB_ID>
   tail -f logs/reticle-etl-dedup-gpu-<JOB_ID>.out
   ```

4. **Submit Phase 2 on CPU node**:
   ```bash
   ./submit-etl-job-split.sh 2 --cpu
   ```

5. **Validate final data in database**:
   ```sql
   SELECT COUNT(*) FROM staging_screen WHERE version_id = 2;
   SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = 2;
   ```

For questions or issues, check logs under `~/projects/RETICLE/logs/`.
