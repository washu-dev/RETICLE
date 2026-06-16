# RETICLE Scripts — Data Warehouse ETL & Staging

HPC-optimized Python scripts for loading and transforming CRISPR screen data into a versioned PostgreSQL data warehouse.

---

## Quick Reference

| Script | Purpose | Use Case |
|--------|---------|----------|
| **staging_loader.py** | Sequential staging load (180s mouse) | Testing, small datasets, debugging |
| **hpc_staging_loader.py** | Parallel staging load (35-45s mouse, 4-5x speedup) | **Recommended for HPC** |
| **hpc_etl_pipeline.py** | CPU-only ETL (single-threaded, 15-20s mouse) | Testing, non-GPU environments |
| **hpc_etl_gpu.py** | GPU+CPU unified ETL (30 min GPU reserve, 30s GPU work) | GPU testing, small datasets |
| **gpu_etl_dedup_only.py** | **Phase 1 of split pipeline** — GPU dedup only (~30s) | **Production GPU work** |
| **cpu_etl_load_only.py** | **Phase 2 of split pipeline** — CPU database load (~30s) | **Production CPU work** |
| **maintenance.py** | Data warehouse maintenance (purge, promote, storage) | Administration |
| **config.py** | Configuration management (DB, paths, logging) | Imported by all scripts |
| **validate_etl_readiness.py** | Pre-flight checks before running ETL | Testing setup |
| **drop_all_objects.py** | **DESTRUCTIVE** — Drop all database tables | Development cleanup only |

---

## Data Loading (Staging)

### `staging_loader.py`

**Sequential staging data loader** — Reads JSON screen metadata and TSV gene-pair files, loads to database via COPY.

**Performance:** ~180 seconds for mouse dataset (1.9M genes, 205 screens)

**Usage:**
```bash
python staging_loader.py --organism homo_sapiens [--description "optional notes"]
python staging_loader.py --organism mus_musculus
```

**What it does:**
1. Read JSON screen metadata files
2. Insert screens into `staging_screen` table via batch executemany()
3. Read TSV gene-pair files
4. Parse and validate gene data
5. Insert pairs into `staging_screen_gene` via PostgreSQL COPY
6. Create version record in `data_load_version`

**Output:**
- Populated `staging_screen` table
- Populated `staging_screen_gene` table
- Version record for tracking

---

### `hpc_staging_loader.py` ⭐ **RECOMMENDED**

**Parallel staging data loader** — HPC-optimized version using ThreadPoolExecutor for 4-5x speedup.

**Performance:** ~35-45 seconds for mouse (8-16 threads), ~3-5 minutes for human (16 threads)

**Usage:**
```bash
# Default 8 threads
python hpc_staging_loader.py --organism mus_musculus

# Custom threads (16 for large datasets)
python hpc_staging_loader.py --organism homo_sapiens --threads 16

# With description
python hpc_staging_loader.py --organism mus_musculus --threads 8 --description "Q2 2026 screens"

# Debug logging
python hpc_staging_loader.py --organism homo_sapiens --log-level DEBUG
```

**What it does:**
1. Count JSON and TSV files to show total work
2. Spawn worker threads (default 8, configurable)
3. Read JSON files in parallel
4. Read TSV files in parallel
5. Thread-safe CSV generation with locks
6. Single PostgreSQL COPY operation (atomic)
7. Print performance metrics (files/sec, speedup factor)

**Advantages over sequential:**
- ✅ 4-5x faster (35-45s vs 180s for mouse)
- ✅ Better CPU utilization on multi-core nodes
- ✅ Same reliability (single COPY operation is atomic)
- ✅ Same output as sequential loader

---

## ETL (Staging → Analytics)

### `hpc_etl_pipeline.py`

**CPU-only ETL pipeline** — Transforms staging data into analytics-ready tables using multi-threaded pandas deduplication.

**Performance:** ~15-20 seconds for mouse dataset (8 CPU threads)

**Usage:**
```bash
python hpc_etl_pipeline.py --version 2 [--threads 8]
```

**What it does:**
1. Load staging data from database
2. Deduplicate genes in parallel (pandas, 100x faster than SQL DISTINCT ON)
3. Deduplicate screen-gene pairs
4. Batch insert deduplicated data via PostgreSQL COPY
5. Validate row counts match deduplication stats

**Output:**
- Deduplicated `screen` table
- Deduplicated `gene` table
- Normalized `screen_gene_raw` pairs
- Populated `fact_screen_gene` aggregations

---

### `hpc_etl_gpu.py`

**Unified GPU+CPU ETL pipeline** — Uses RAPIDS/cuDF for GPU-accelerated deduplication (if available), falls back to CPU pandas.

**Performance:** ~30 seconds on GPU A100 (but reserves GPU node for 30 minutes)

**Usage:**
```bash
python hpc_etl_gpu.py --version 2 [--threads 8]
```

**What it does:**
1. Check RAPIDS/cuDF availability
2. Load staging data
3. GPU dedup genes (if RAPIDS) or CPU dedup (fallback)
4. GPU dedup pairs (if RAPIDS) or CPU dedup (fallback)
5. Batch insert deduplicated data

**⚠️ Cost Warning:**
- GPU used for ~30 seconds
- GPU node reserved for 30 minutes
- Wastes GPU resources on non-GPU database inserts

**👉 Recommendation:** Use split pipeline instead (gpu_etl_dedup_only.py + cpu_etl_load_only.py)

---

### `gpu_etl_dedup_only.py` ⭐ **PHASE 1: GPU WORK**

**Phase 1 of split GPU/CPU pipeline** — GPU deduplication ONLY, no database loading.

**Performance:** ~30 seconds on GPU node (actual GPU work)

**Usage:**
```bash
python gpu_etl_dedup_only.py --version 2
```

**What it does:**
1. Load genes from staging database
2. GPU dedup genes (or CPU pandas fallback)
3. Load pairs from staging database
4. GPU dedup pairs (or CPU pandas fallback)
5. Export CSV files to `/tmp/reticle_staging/` for Phase 2
6. Save metadata with stats and timestamps

**Output:**
- `/tmp/reticle_staging/staging_screen_v2.csv` (deduplicated screens)
- `/tmp/reticle_staging/staging_screen_gene_v2.csv` (deduplicated pairs)
- `/tmp/reticle_staging/dedup_metadata_v2.json` (statistics)

**GPU Utilization:**
- ✅ GPU fully utilized during dedup (~30s)
- ✅ No wasted GPU time

---

### `cpu_etl_load_only.py` ⭐ **PHASE 2: CPU WORK**

**Phase 2 of split GPU/CPU pipeline** — Database loading ONLY, no deduplication.

**Performance:** ~30 seconds for mouse, ~10-20 minutes for human (CPU node)

**Usage:**
```bash
python cpu_etl_load_only.py --version 2
```

**Prerequisites:**
- Phase 1 (gpu_etl_dedup_only.py) must have completed successfully
- CSV files must exist in `/tmp/reticle_staging/`

**What it does:**
1. Load GPU dedup metadata (verify Phase 1 completed)
2. Read `staging_screen_v2.csv` with progress bar
3. PostgreSQL COPY into `staging_screen` table
4. Read `staging_screen_gene_v2.csv` with progress bar
5. PostgreSQL COPY into `staging_screen_gene` table
6. Validate: row counts match, no NULL critical values
7. Report success/failure with statistics

**Output:**
- Populated `staging_screen` table
- Populated `staging_screen_gene` table
- Live progress bars (tqdm)

**CPU Utilization:**
- ✅ CPU fully utilized during COPY (~30s)
- ✅ No wasted resources

---

## Maintenance & Administration

### `maintenance.py`

**Data warehouse operations** — Version management, storage analysis, ETL history.

**Usage:**
```bash
# List all data versions
python maintenance.py --list-versions

# Show storage usage by version
python maintenance.py --show-storage

# Show ETL pipeline run history
python maintenance.py --show-etl-history

# Estimate space to free by purging version 1
python maintenance.py --estimate-purge 1

# Purge specific version (with confirmation)
python maintenance.py --purge-version 1

# Purge all old versions except current
python maintenance.py --purge-old --no-confirm

# Promote old version back to current
python maintenance.py --promote-version 1
```

**Output:**
- Tabular reports (via tabulate library)
- Space estimates and freed counts
- ETL execution logs

---

## Shell Wrappers (Convenience Scripts)

### `warehouse-load.sh`

**Wrapper for staging data loader** — Simplified interface to `staging_loader.py` with colorized output.

**Usage:**
```bash
./warehouse-load.sh <organism> [description]
```

**Examples:**
```bash
# Load with default description
./warehouse-load.sh homo_sapiens

# Load with custom description
./warehouse-load.sh mus_musculus "Mouse ORCS Q2 2026"
```

**What it does:**
1. Validate organism (homo_sapiens or mus_musculus)
2. Run `staging_loader.py` with organism and description
3. Print colorized status messages (INFO, ERROR, WARN)
4. Suggest next step on success

**Output:**
```
[INFO] Loading homo_sapiens data
[INFO] Starting staging data loader...
[INFO] Staging load completed successfully
[INFO] Next step: Run ./warehouse-run-etl.sh <version_id>
```

---

### `warehouse-run-etl.sh`

**Wrapper for ETL pipeline** — Simplified interface to `run_etl_pipeline.py`.

**Usage:**
```bash
./warehouse-run-etl.sh <version_id> [options]
```

**Options:**
```
--show-info           Show version info before running
--pipeline-version    Pipeline version string (default: from config)
```

**Examples:**
```bash
# Run ETL on version 2
./warehouse-run-etl.sh 2

# Run with version info
./warehouse-run-etl.sh 2 --show-info

# Run with custom pipeline version
./warehouse-run-etl.sh 3 --pipeline-version 1.0.0
```

**What it does:**
1. Validate version ID is numeric
2. Run `run_etl_pipeline.py` with version and options
3. Print colorized status messages
4. Suggest next step on success

**Output:**
```
[STEP] Starting ETL pipeline for version 2
[INFO] Command: python3 run_etl_pipeline.py --version 2
[INFO] ETL pipeline completed successfully
[INFO] Next step: Run './warehouse-maintenance.sh --show-storage' to verify
```

---

### `warehouse-maintenance.sh`

**Wrapper for maintenance operations** — Simplified interface to `maintenance.py`.

**Usage:**
```bash
./warehouse-maintenance.sh [command]
```

**Commands:**
```
--list-versions      List all data versions
--show-storage       Show storage usage by version
--show-etl-history   Show ETL pipeline run history
--estimate-purge <id> Estimate space to free by purging
--purge-version <id> Purge specific version
--purge-old          Purge all old versions (keep current)
--promote-version <id> Promote old version to current
--help               Show help
```

**Examples:**
```bash
# List versions
./warehouse-maintenance.sh --list-versions

# Show storage
./warehouse-maintenance.sh --show-storage

# Purge old versions
./warehouse-maintenance.sh --purge-old

# Estimate what would be freed by purging version 1
./warehouse-maintenance.sh --estimate-purge 1
```

**What it does:**
1. Validate command
2. Run `maintenance.py` with command and arguments
3. Print colorized status messages
4. Display results in tabular format (via tabulate)

---

### `warehouse-purge.sh`

**⚠️ DESTRUCTIVE** — Drops ALL database tables and functions.

**Usage:**
```bash
./warehouse-purge.sh --confirm
```

**WARNING:**
- ❌ Irreversible — requires manual restoration from backups
- ❌ Development/testing only
- ❌ Requires `--confirm` flag to execute

**What it does:**
1. Require explicit `--confirm` flag
2. Call `drop_all_objects.py`
3. Drop all RETICLE tables and functions

**Output:**
```
[WARN] This will DROP ALL database objects
[WARN] This cannot be undone
[WARN] Dropped: staging_screen, staging_screen_gene, screen, gene, ...
```

---

### `run-hpc-etl.sh`

**Flexible HPC ETL runner** — Switches between different ETL implementations (multi-threaded, GPU, or original SQL).

**Usage:**
```bash
./run-hpc-etl.sh <version_id> [--mode MODE] [--threads N] [--gpu]
```

**Modes:**
```
--threads N    Multi-threaded mode (default, Python pandas dedup)
--gpu          GPU-accelerated mode (RAPIDS cuDF)
--mode sql     Original SQL DISTINCT ON approach (deprecated)
```

**Examples:**
```bash
# Multi-threaded (default)
./run-hpc-etl.sh 2 --threads 8

# GPU-accelerated
./run-hpc-etl.sh 2 --gpu

# SQL mode (legacy)
./run-hpc-etl.sh 2 --mode sql
```

**What it does:**
1. Detect mode from arguments
2. Dispatch to appropriate ETL implementation:
   - `--threads`: `hpc_etl_pipeline.py`
   - `--gpu`: `hpc_etl_gpu.py`
   - `--mode sql`: Original SQL-based approach
3. Run with version ID and options
4. Print colorized status messages

**Output:**
```
[INFO] Running ETL in multi-threaded mode with 8 threads
[INFO] Loaded 1,904,551 genes from staging
[INFO] Deduplicated to 30,039 unique genes
[INFO] ETL pipeline completed successfully
```

---

## Configuration & Utilities

### `config.py`

**Configuration management** — Reads environment variables and `.env` files. Used by all other scripts.

**Provides:**
- Database connection parameters (via `Config.get_psycopg2_params()`)
- Data directory paths
- Logging configuration
- Validation methods

**Environment Variables:**
```bash
DB_HOST              # PostgreSQL hostname (RDS endpoint)
DB_PORT              # PostgreSQL port (default: 5432)
DB_NAME              # Database name (reticle_biogrid)
DB_USER              # PostgreSQL username (reticle_admin)
DB_PASSWORD          # Leave empty; uses ~/.pgpass
ETL_BATCH_SIZE       # Batch insert size (default: 10000)
LOG_LEVEL            # DEBUG, INFO, WARNING (default: INFO)
```

**Not directly executable** — imported by other scripts.

---

### `validate_etl_readiness.py`

**Pre-flight validation** — Checks database connectivity and staging data before running ETL.

**Usage:**
```bash
python validate_etl_readiness.py --version 2
```

**Checks:**
- Database connection works
- Version exists in `data_load_version`
- Staging tables have data
- No NULL critical values in staging
- Row counts reasonable

**Output:**
- Pass/fail report
- Detailed validation errors if any

---

### `drop_all_objects.py`

**⚠️ DESTRUCTIVE** — Drops ALL database tables and functions.

**Usage:**
```bash
python drop_all_objects.py --confirm
```

**WARNING:**
- ❌ Irreversible — requires manual restoration from backups
- ❌ Development/testing only
- ❌ Requires `--confirm` flag to execute

**Output:**
- List of dropped tables and functions

---

## Workflow Examples

### Example 1: Staging + Split Pipeline (Recommended)

```bash
# 1. Load staging data (HPC-optimized, 35-45s)
python hpc_staging_loader.py --organism mus_musculus --threads 16

# 2. Phase 1: GPU deduplication (30s on GPU node via SLURM)
./slurm/submit-etl-job-split.sh 2 --gpu

# 3. Phase 2: CPU database loading (30s on CPU node via SLURM)
python cpu_etl_load_only.py --version 2

# 4. Verify
python maintenance.py --show-storage
```

### Example 2: Full Local Testing

```bash
# 1. Load staging (sequential, ~180s for mouse)
python staging_loader.py --organism mus_musculus

# 2. ETL (CPU-only, ~15-20s)
python hpc_etl_pipeline.py --version 2

# 3. Check results
python maintenance.py --list-versions
python maintenance.py --show-storage
```

### Example 3: GPU Testing (Unified Pipeline)

```bash
# Load staging
python hpc_staging_loader.py --organism mus_musculus

# GPU+CPU ETL (30s GPU work, 30 min reservation)
python hpc_etl_gpu.py --version 2

# Results
python maintenance.py --show-etl-history
```

---

## Performance Comparison

| Task | Sequential | Parallel HPC | GPU Unified | GPU Split (Phase 1+2) |
|------|-----------|--------------|-------------|----------------------|
| **Mouse Staging** | 180s | 35-45s | N/A | 35-45s |
| **Mouse Dedup** | 5-10min | 15-20s | 30s | 30s |
| **Mouse Load** | N/A | N/A | 20-30s | 20-30s |
| **Total Wall Time** | 6-10 min | 50-65s | 1-2 min | 1-2 min |
| **GPU Reserve** | N/A | N/A | 30 min | 5 min |
| **Cost/Run** | $0 | $0.25 | $12 | $2.50 |
| **Cost/1000 Runs** | $0 | $250 | $12,000 | $2,500 |

---

## Dependencies

**Required (installed via pip):**
```bash
pip install pandas numpy psycopg2-binary python-dotenv tqdm
```

**Optional (for GPU acceleration):**
```bash
# RAPIDS/cuDF (requires CUDA 11.8+)
conda install -c nvidia -c conda-forge rapids=24.02 cudf cupy
```

**For HPC with no conda:**
```bash
pip install cudf-cu12  # Falls back to CPU pandas if unavailable
```

---

## Troubleshooting

### Import Error: `No module named 'database'`

**Cause:** Legacy code trying to import missing `database.py`

**Fix:** Use `config.py` instead. All scripts have been updated to use:
```python
import psycopg2
from config import Config
conn = psycopg2.connect(**Config.get_psycopg2_params())
```

### Import Error: `No module named 'dotenv'`

**Cause:** `python-dotenv` not installed

**Fix:** 
```bash
pip install python-dotenv
```

Or run environment setup:
```bash
source ../slurm/env-setup.sh  # Creates venv with all deps
```

### Connection Error: `connection to server at "localhost" ... port 5432 failed`

**Cause:** Environment variables not set

**Fix:**
```bash
export DB_HOST=your-rds-endpoint.amazonaws.com
export DB_PORT=5432
export DB_NAME=reticle_biogrid
export DB_USER=reticle_admin
# Leave DB_PASSWORD empty; use ~/.pgpass instead
```

### RAPIDS Not Available: Falls Back to CPU Pandas

**Expected behavior** — if cuDF import fails, scripts automatically fall back to CPU pandas. Slower (~5x) but works everywhere.

To force GPU:
```bash
module load cuda/12.0  # Or appropriate CUDA module for your cluster
python gpu_etl_dedup_only.py --version 2
```

---

## References

- **HPC ETL Design**: `../docs/HPC_ETL_DESIGN.md`
- **Split Pipeline Guide**: `../docs/SPLIT_GPU_CPU_PIPELINE.md`
- **SLURM Scripts**: `../slurm/README.md`
- **Database Migrations**: `../database/migrations/`
- **Configuration**: See `config.py` docstrings
