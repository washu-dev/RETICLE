# RETICLE Database — Schema & ETL

PostgreSQL schema and transformation logic for the versioned data warehouse.

## Files

### `migrations/` — Schema Management

**0009_versioned_data_warehouse.sql** (Current)
- Creates all versioned data warehouse tables
- Version control tables: `data_load_version`, `etl_pipeline_run`, `etl_audit_log`
- Staging tables: `staging_screen`, `staging_screen_gene` (raw ingest, no constraints)
- Integration tables: `screen`, `gene`, `screen_gene_raw` (normalized)
- Analytics tables: `fact_screen_gene`, `dim_screen`, `dim_gene` (aggregated)
- Idempotent with `CREATE TABLE IF NOT EXISTS`

**0010_drop_versioned_data_warehouse.sql** (Cleanup)
- Drops all versioned data warehouse objects
- Removes all views, functions, tables, and sequences
- Safe to run multiple times (uses `DROP IF EXISTS`)
- Use before re-applying 0009 for a fresh start

### `etl_pipeline.sql` — Data Transformation

Transforms staging data into analytics-ready tables:

1. **Staging → Integration** 
   - Upsert `screen` and `gene` records from staging
   - Build normalized `screen_gene_raw` pairs
   - Validate and deduplicate

2. **Integration → Facts**
   - Compute `fact_screen_gene` aggregations (hit counts, publications)
   - Build `dim_screen` (screen-level aggregates)
   - Build `dim_gene` (gene-level aggregates)

3. **Audit & Logging**
   - Record each step in `etl_audit_log`
   - Track row counts, durations, errors
   - Update `etl_pipeline_run` status

### `maintenance_utilities.sql` — Operations

Administrative functions:

- **`purge_version(version_id)`** — Delete specific version and dependent data
- **`purge_old_versions()`** — Delete all non-current versions
- **`purge_all_data()`** — Complete data warehouse reset (destructive!)
- **`get_version_storage_details(version_id)`** — Storage breakdown per version
- **`estimate_purge_space(version_id)`** — Estimate space freed by purge
- **`promote_version_to_current(version_id)`** — Rollback to older version

Views:
- **`v_validation_issues`** — Staging rows with errors
- **`v_etl_run_summary`** — ETL execution history

### `WAREHOUSE_USAGE_GUIDE.md`

Documentation and usage examples for the data warehouse.

## Workflow

### Initial Setup

```bash
# Create schema
psql -h localhost -U reticle_user -d reticle_survey < migrations/0009_versioned_data_warehouse.sql
```

### Data Loading

```bash
# Load data (creates version record)
./scripts/warehouse-load.sh homo_sapiens

# Run ETL (transforms to analytics tables)
./scripts/warehouse-run-etl.sh 1
```

### Maintenance

```bash
# List all versions
psql -h localhost -U reticle_user -d reticle_survey \
  -c "SELECT version_id, organism, status, num_screens, num_genes FROM data_load_version ORDER BY version_id DESC;"

# Show storage usage
psql -h localhost -U reticle_user -d reticle_survey \
  -c "SELECT * FROM get_version_storage_details();"

# Purge old versions
psql -h localhost -U reticle_user -d reticle_survey \
  -c "SELECT * FROM purge_old_versions();"

# Reset database
psql -h localhost -U reticle_user -d reticle_survey < migrations/0010_drop_versioned_data_warehouse.sql
psql -h localhost -U reticle_user -d reticle_survey < migrations/0009_versioned_data_warehouse.sql
```

## Table Architecture

### Versioning Hierarchy

```
data_load_version (v1, v2, v3, ...)
    ↓
    ├─ staging_screen (raw screens from JSON)
    ├─ staging_screen_gene (raw genes from TSV)
    │
    └─ etl_pipeline_run (ETL execution record)
        ↓
        ├─ screen (deduplicated screens)
        ├─ gene (deduplicated genes)
        ├─ screen_gene_raw (normalized pairs)
        │
        ├─ fact_screen_gene (aggregations)
        ├─ dim_screen (screen dimensions)
        └─ dim_gene (gene dimensions)
```

### Key Constraints

**Staging tables** (raw ingest):
- No UNIQUE constraints (allow duplicates)
- Foreign key to `data_load_version` with `ON DELETE CASCADE`
- Validation errors tracked in `validation_errors` column

**Integration tables** (normalized):
- UNIQUE on (version_id, identifier) to prevent duplicates
- Foreign key to `data_load_version`
- Tracks `is_current` flag for version promotion

**Analytics tables** (aggregated):
- Denormalized for fast queries
- Indexes on (version_id, is_current)
- Link back to integration tables via foreign keys

## Indexes

Performance-critical indexes on:
- `(version_id, is_current)` — for filtering by active version
- `(version_id, screen_id)` and `(version_id, gene_id)` — for joins
- `(screen_id, gene_id)` — for deduplication

## Data Integrity

**Cascade delete on version removal:**
- Removing a version cascades through all dependent tables
- Ensures no orphaned data

**Validation phase:**
- Detects missing required fields during staging
- ETL skips invalid rows during transformation
- Errors logged in audit trail

**Deduplication:**
- Staging accepts duplicates as-is (raw data)
- ETL deduplicates on (version_id, screen_id, gene_id)
- Integration layer enforces UNIQUE constraint

## References

- **Schema Creation**: migrations/0009_versioned_data_warehouse.sql
- **Cleanup**: migrations/0010_drop_versioned_data_warehouse.sql
- **ETL Logic**: etl_pipeline.sql
- **Maintenance**: maintenance_utilities.sql
- **Usage Guide**: WAREHOUSE_USAGE_GUIDE.md
- **Loader**: scripts/staging_loader.py
- **ETL Pipeline**: scripts/run_etl_pipeline.py
