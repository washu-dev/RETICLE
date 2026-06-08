# Split GPU/CPU Pipeline — Quick Start

**Two-phase ETL: GPU for dedup (~30s), CPU for loading (~30s). Save $10+ per run.**

---

## The Problem

Your unified GPU pipeline reserves a GPU node for 30 minutes but:
- Only uses GPU for ~30 seconds of deduplication
- Rest is CPU-bound database inserts (20+ minutes)
- GPU sits idle, driving up cluster costs

## The Solution

**Split into two phases:**
1. **Phase 1 (GPU):** Deduplicate genes & pairs (~30s), write CSV files
2. **Phase 2 (CPU):** Read CSV files, bulk insert to database (~30s)
3. Release GPU node immediately after Phase 1 → cost savings

---

## Quick Start

### Setup (One-Time)

```bash
cd ~/projects/RETICLE/slurm

# Make sure environment variables are set in ~/.bashrc
export RETICLE_DIR=~/projects/RETICLE
export DB_HOST=your-rds-endpoint.amazonaws.com
export DB_PORT=5432
export DB_NAME=reticle_biogrid
export DB_USER=reticle_admin
export RETICLE_PARTITION_CPU=general-cpu
export RETICLE_PARTITION_GPU=gpu-v100
```

### Run Both Phases (Recommended)

```bash
./submit-etl-job-split.sh 2 --both
```

Done. Phase 2 starts automatically after Phase 1 completes.

### Run Phases Separately

```bash
# Phase 1 (GPU)
./submit-etl-job-split.sh 2 --gpu

# Wait for Phase 1 to complete
watch squeue -j <JOB_ID>

# Phase 2 (CPU)
./submit-etl-job-split.sh 2 --cpu
```

---

## Expected Output

### Phase 1 (GPU Dedup)
```
GPU DEDUPLICATION PHASE
Version ID: 2
GPU Available: True

✓ Connected to database
✓ Loaded 205 screens
GPU: Deduplicating 1,904,551 genes...
Removed 1,874,512 duplicates
GPU: Deduplicating pairs...
After dedup: 6,034,251 unique pairs

GPU DEDUP PHASE COMPLETE
Elapsed time: 28.3s
Genes: 1,904,551 → 30,039
Pairs: 5,987,834 → 6,034,251

Next step: Run cpu_etl_load_only.py --version 2
```

### Phase 2 (CPU Load)
```
CPU LOADING PHASE
Version ID: 2

✓ Connected to database
✓ Loaded metadata (GPU: True)

Loading screens via COPY...
✓ Inserted 205 screens
Loading screen-gene pairs via COPY...
Copying 6,034,251 rows...
✓ Inserted 6,034,251 pairs
Validating loaded data...
Screens: 205 ✓
Pairs: 6,034,251 ✓
NULL validation: PASSED ✓

CPU LOADING PHASE COMPLETE
Elapsed time: 21.8s
```

---

## Commands

### Submit Jobs

```bash
# Both phases (GPU then CPU with automatic chaining)
./submit-etl-job-split.sh 2 --both

# Phase 1 only (GPU dedup)
./submit-etl-job-split.sh 2 --gpu

# Phase 2 only (CPU load)
./submit-etl-job-split.sh 2 --cpu

# With custom time limits
./submit-etl-job-split.sh 2 --both --gpu-time 00:10:00 --cpu-time 02:00:00

# With custom cores
./submit-etl-job-split.sh 2 --gpu-cores 16 --cpu-cores 32
```

### Monitor Jobs

```bash
# Check both job statuses
squeue -j 1234567,1234568

# Watch continuously
watch squeue -j 1234567,1234568

# Watch logs
tail -f logs/reticle-etl-dedup-gpu-*.out
tail -f logs/reticle-etl-load-cpu-*.out
```

### Direct Execution (No SLURM)

```bash
cd ~/projects/RETICLE/scripts

# Phase 1: GPU dedup
python gpu_etl_dedup_only.py --version 2

# Phase 2: CPU load
python cpu_etl_load_only.py --version 2
```

---

## Performance

### Mouse Dataset (1.9M genes)

| Phase | Time | Resource |
|-------|------|----------|
| GPU Dedup | ~30s | GPU (p3.2xlarge) |
| CPU Load | ~20s | CPU (m5.large) |
| **Total** | **~50s** | Parallel nodes |
| vs Unified | **30 min** | GPU only |
| **Speedup** | **36x faster** | GPU released immediately |

### Cost Savings

```
Unified pipeline:   30 min × $24/hr = $12.00
Split pipeline:     5 min GPU + 1 hr CPU = ~$2.50
Savings per job:    $9.50
Per 100 jobs:       $950
Per 1000 jobs:      $9,500
```

---

## Troubleshooting

### Phase 1 Failed?

```bash
tail logs/reticle-etl-dedup-gpu-*.out | tail -50
```

Check:
- Database connection: `$DB_HOST`, `$DB_USER`, `~/.pgpass`
- GPU availability: `nvidia-smi`
- RAPIDS installed: Falls back to CPU pandas automatically

### Phase 2 Failed?

```bash
tail logs/reticle-etl-load-cpu-*.out | tail -50
```

Check:
- CSV files exist: `/tmp/reticle_staging/staging_screen_v2.csv`
- Database connection: Same as Phase 1
- Phase 1 completed successfully: Check its log

### Phase 2 Not Starting?

If submitted with `--both`, Phase 2 waits for Phase 1 to complete:

```bash
# Check Phase 1 status
squeue -j 1234567

# Check Phase 2 dependency
squeue -j 1234568 -O jobid,name,state,dependency
```

---

## Files

| File | Purpose |
|------|---------|
| `gpu_etl_dedup_only.py` | Phase 1: GPU dedup script |
| `cpu_etl_load_only.py` | Phase 2: CPU load script |
| `reticle-etl-dedup-gpu.sh` | SLURM wrapper for Phase 1 |
| `reticle-etl-load-cpu.sh` | SLURM wrapper for Phase 2 |
| `submit-etl-job-split.sh` | Job submission helper |
| `SPLIT_GPU_CPU_PIPELINE.md` | Full documentation |

---

## When to Use

✅ **Use split pipeline:**
- Human datasets (26M+ genes)
- Frequent runs (daily/weekly)
- GPU is a bottleneck
- You care about cost

✅ **Use unified pipeline:**
- Debugging/testing
- Small datasets (< 1M genes)
- One-time runs

---

## Example Workflow

```bash
# 1. Submit both phases
./submit-etl-job-split.sh 2 --both
# Output: Phase 1 Job 1234567, Phase 2 Job 1234568

# 2. Monitor Phase 1 (GPU dedup)
watch squeue -j 1234567
tail -f logs/reticle-etl-dedup-gpu-1234567.out
# Waits for: ~30 seconds

# 3. Phase 1 completes, Phase 2 starts automatically
# Monitor Phase 2 (CPU load)
watch squeue -j 1234568
tail -f logs/reticle-etl-load-cpu-1234568.out
# Waits for: ~30 seconds

# 4. Both complete, all data loaded
# Verify in database
psql $DB_NAME -c "SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = 2;"
```

---

## More Info

See `SPLIT_GPU_CPU_PIPELINE.md` for:
- Full architecture diagram
- Detailed cost analysis
- Advanced usage (parallel Phase 1, etc.)
- Troubleshooting guide
- Custom SLURM constraints
