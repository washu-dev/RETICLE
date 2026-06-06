# RETICLE Scripts — Versioned Data Warehouse

Fast bulk data loader for CRISPR screen data using PostgreSQL COPY operations.

## Architecture

```
BioGrid ORCS Data Files (JSON/TSV)
         ↓
    staging_loader.py
    (bulk INSERT via executemany + COPY)
         ↓
   staging_screen
   staging_screen_gene
         ↓
   run_etl_pipeline.py
   (transformation & aggregation)
         ↓
   screen, gene, screen_gene_raw
   fact_screen_gene, dim_screen, dim_gene
         ↓
   PostgreSQL (versioned data warehouse)
```

## Quick Start

### 1. Setup

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials
```

### 2. Load Data

```bash
# Load Homo sapiens CRISPR screen data
./warehouse-load.sh homo_sapiens

# Or with description
./warehouse-load.sh homo_sapiens "Human screens v2 - fixes gene names"

# Load Mus musculus data
./warehouse-load.sh mus_musculus
```

This creates:
- **Version record** in `data_load_version`
- **Staging records** in `staging_screen` and `staging_screen_gene`
- **Validation checks** on all imported data

### 3. Run ETL Pipeline

```bash
# Transform staging data to analytics-ready tables
./warehouse-run-etl.sh <version_id>

# Example:
./warehouse-run-etl.sh 1
```

### 4. Manage Data

```bash
# List all versions
./warehouse-maintenance.sh --list-versions

# Show storage usage
./warehouse-maintenance.sh --show-storage

# Purge old versions
./warehouse-maintenance.sh --purge-old

# Purge specific version
./warehouse-maintenance.sh --purge-version 2
```

## Scripts

### `staging_loader.py`
**Fast bulk data loader** using PostgreSQL COPY (100x faster than ORM).

Features:
- JSON screens → `staging_screen` via executemany() batching
- TSV gene results → CSV → `staging_screen_gene` via COPY command
- Progress bars with tqdm
- Automatic validation & error logging
- Source filenames tracked in `data_load_version`

**Usage:**
```bash
python staging_loader.py --organism homo_sapiens [--description "optional notes"]
```

### `run_etl_pipeline.py`
**Transform & aggregate** staging data into analytics tables.

Executed steps:
1. Validate staging data
2. Upsert `screen` and `gene` records
3. Build `screen_gene_raw` normalized pairs
4. Compute `fact_screen_gene` aggregations
5. Build `dim_screen` and `dim_gene` dimensions

**Usage:**
```bash
python run_etl_pipeline.py --version <version_id>
```

### `maintenance.py`
**Data warehouse operations**: purge, rollback, storage reporting.

**Usage:**
```bash
python maintenance.py --list-versions
python maintenance.py --show-storage
python maintenance.py --purge-version 2
```

### `config.py`
**Configuration management** — reads `.env` or environment variables.

Handles:
- Database connection (host, port, user, password)
- Organism definitions (patterns for JSON/TSV files)
- Data directory paths
- Logging configuration

### `database.py`
**Database utilities** — connection pooling, cursor management, context managers.

### Shell Wrappers

- **`warehouse-load.sh`** — Run staging_loader with colorized output
- **`warehouse-run-etl.sh`** — Run ETL pipeline with error handling
- **`warehouse-maintenance.sh`** — Run maintenance operations with user-friendly UI

## Database Schema

### Version Control

**`data_load_version`** — Track each data import
- `version_id` — Unique version identifier
- `organism` — homo_sapiens or mus_musculus
- `source_type` — biogrid_orcs, etc.
- `json_filenames[]` — Source JSON files
- `tsv_filenames[]` — Source TSV files
- `num_screens`, `num_genes` — Load counts
- `status` — pending, valid, invalid
- `is_current` — Active version flag

### Staging Tables (Raw Ingest)

**`staging_screen`** — Raw screen metadata (no UNIQUE constraints)
- `screen_id`, `biogrid_screen_id`
- `organism`, `annotation_source`
- `moi`, `notes` — Structured fields
- `validated`, `validation_errors`

**`staging_screen_gene`** — Raw gene-screen pairs
- `screen_id`, `identifier_id` (gene)
- `gene_symbol`, `official_symbol`
- `hit_flag`, `score_1`..`score_5`
- `tsv_filename`, `tsv_row_number` — Audit trail

### Integration Tables (Normalized)

**`screen`** — Deduplicated screens
**`gene`** — Deduplicated genes
**`screen_gene_raw`** — Normalized gene-screen pairs

### Analytics Tables (Aggregated)

**`fact_screen_gene`** — Gene-level aggregations (hits, publications)
**`dim_screen`** — Screen dimensions (total genes, avg hit %)
**`dim_gene`** — Gene dimensions (total screens, avg hit %)

## Environment Setup

Create `.env` from `.env.example`:

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=reticle_survey
DB_USER=reticle_user
DB_PASSWORD=your_password

# Data
DATA_DIR=/path/to/biogrid_orcs_data/

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

## Performance

### Bulk Loading Speed

- **JSON screens** (executemany): ~1,952 screens in 2-3 seconds
- **TSV genes** (COPY): ~1.9M gene-screen pairs in 5 seconds

### Database Optimization

- Indexes on `(version_id, is_current)`
- Indexes on `(version_id, screen_id)` and `(version_id, gene_id)`
- Cascade deletes on `data_load_version` cleanup

## Workflow Example

```bash
# 1. Load screens from JSON files
./warehouse-load.sh homo_sapiens "BioGrid ORCS - June 2026"
# Output: version_id = 1

# 2. Run ETL to transform and aggregate
./warehouse-run-etl.sh 1

# 3. Verify data
./warehouse-maintenance.sh --show-storage

# 4. Later, load new version
./warehouse-load.sh homo_sapiens "BioGrid ORCS - July 2026"
# Output: version_id = 2

# 5. Run new ETL
./warehouse-run-etl.sh 2

# 6. Promote v2 to current, purge v1
./warehouse-maintenance.sh --promote-version 2
./warehouse-maintenance.sh --purge-version 1
```

## Troubleshooting

### Connection Error: `FATAL: no pg_hba.conf entry`

**Cause:** RDS requires SSL encryption
**Fix:** Use `sslmode='require'` in connection string

### Connection Error: `Ticket expired` (GSSAPI)

**Cause:** Kerberos ticket timeout
**Fix:** Disable GSSAPI with `gssencmode='disable'`

### COPY Fails: `invalid input syntax for type json`

**Cause:** Newlines in JSON break pipe-delimited format
**Fix:** Use executemany() for JSON instead of CSV

### Duplicate Key Violation in `staging_screen_gene`

**Cause:** TSV files contain duplicate (screen, gene) pairs
**Fix:** Removed UNIQUE constraint from staging table; ETL deduplicates

## Monitoring

```bash
# View current data load status
psql -h localhost -U reticle_user -d reticle_survey -c \
  "SELECT version_id, organism, status, num_screens, num_genes FROM data_load_version ORDER BY version_id DESC;"

# Check staging table sizes
psql -h localhost -U reticle_user -d reticle_survey -c \
  "SELECT 
    (SELECT COUNT(*) FROM staging_screen WHERE version_id = 1) as screens,
    (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = 1) as genes;"

# Monitor ETL pipeline runs
psql -h localhost -U reticle_user -d reticle_survey -c \
  "SELECT run_id, version_id, status, total_duration_seconds FROM etl_pipeline_run ORDER BY run_date DESC LIMIT 5;"
```

## References

- **Schema**: `database/migrations/0009_versioned_data_warehouse.sql`
- **Maintenance Functions**: `database/maintenance_utilities.sql`
- **ETL Logic**: `database/etl_pipeline.sql`
- **Documentation**: `README_VERSIONED_WAREHOUSE.md`
