# RETICLE Versioned Data Warehouse - Usage Guide

## Overview

The new versioned data warehouse replaces the Python-based approach with an **all-SQL pipeline** that:

- Versions every data load (Homo Sapiens, Mus Musculus)
- Versions every ETL run
- Supports rollback, purge, and full audit trail
- Tracks storage usage per version
- Provides data quality reports

## Architecture

```
JSON/TSV Files
    ↓
Staging Tables (versioned)
    ↓
Validation & Integration
    ↓
Denormalized Processing (screen_gene_raw)
    ↓
Fact & Dimension Tables (versioned)
    ↓
Current Data Views (for analysis)
```

## Workflow

### 1. Initialize Migration

```sql
-- Run one-time setup
\i database/migrations/0009_versioned_data_warehouse.sql
\i database/etl_pipeline.sql
\i database/maintenance_utilities.sql
```

### 2. Load Staging Data

```python
# In Python script (load_data_staging.py)
# Load JSON files into staging_screen_json
# Load TSV files into staging_screen_gene_tsv

# Create version record:
INSERT INTO data_load_version (
    organism, source_type, load_description, file_count, total_file_size_bytes
) VALUES (
    'homo_sapiens',
    'biogrid_orcs',
    'Human screen data - Q2 2026',
    1952,
    98765432
)
RETURNING version_id;

-- Returns: version_id = 1
```

### 3. Run ETL Pipeline

```sql
-- Execute the entire pipeline
SELECT * FROM run_etl_pipeline(
    p_version_id := 1,
    p_pipeline_version := '1.0.0'
);

-- Output:
-- run_id │ status    │ duration_seconds │ message
-- ────────┼───────────┼──────────────────┼──────────────────────
--   1    │ completed │ 245.3            │ ETL pipeline completed
```

### 4. Verify Results

```sql
-- View current data
SELECT * FROM v_current_fact_screen_gene LIMIT 10;

-- Check load history
SELECT * FROM v_data_load_versions;

-- View ETL run history
SELECT * FROM v_etl_pipeline_history;

-- Check storage usage
SELECT * FROM get_version_storage_details();

-- View validation issues (if any)
SELECT * FROM v_validation_issues;
```

---

## Common Operations

### Re-upload Same Organism (New Version)

When you want to update Homo Sapiens data after fixing issues:

```python
# Load new JSON/TSV files
INSERT INTO data_load_version (
    organism, source_type, load_description
) VALUES (
    'homo_sapiens',
    'biogrid_orcs',
    'Human data v2 - Fixed gene names'
)
RETURNING version_id;  -- Returns: version_id = 2
```

```sql
-- Run ETL on new version
SELECT * FROM run_etl_pipeline(p_version_id := 2);

-- The pipeline automatically marks version 1 as historical
SELECT * FROM v_data_load_versions;
-- v1 (homo_sapiens): is_current = FALSE
-- v2 (homo_sapiens): is_current = TRUE
```

### Query Current Data

All current data is available through views—no version filtering needed:

```sql
-- Get current facts
SELECT * FROM v_current_fact_screen_gene
WHERE hit_percentage > 50
ORDER BY hit_percentage DESC;

-- Get current dimensions
SELECT * FROM v_current_dim_screen
WHERE organism = 'homo_sapiens';

-- Get current genes by screen count
SELECT * FROM v_current_dim_gene
ORDER BY total_screens DESC
LIMIT 20;
```

### Query Historical Versions

```sql
-- Compare results across versions
SELECT
    f.version_id,
    f.screen_id,
    f.gene_id,
    f.hit_count,
    f.avg_raw_score,
    v.load_date
FROM fact_screen_gene f
JOIN data_load_version v ON f.version_id = v.version_id
WHERE f.screen_id = 3060
ORDER BY v.load_date DESC;
```

---

## Purge Operations

### Check Space Before Purging

```sql
-- Estimate space to be freed
SELECT * FROM estimate_purge_space(p_version_id := 1);

-- View storage breakdown
SELECT * FROM get_version_storage_details(p_version_id := 1);
```

### Purge Specific Version

```sql
-- Delete version 1 and all its data
SELECT * FROM purge_version(p_version_id := 1);

-- Output:
-- status  │ versions_deleted │ staging_rows_deleted │ storage_freed_mb │ message
-- ────────┼──────────────────┼──────────────────────┼──────────────────┼──────────
-- success │ 1                │ 1952                 │ 245.3            │ Version 1 purged...
```

### Purge All Old Versions (Keep Current)

```sql
-- Safely remove all historical versions
SELECT * FROM purge_old_versions();

-- Output: Purges v1, v3, v4 (keeps v2 if it's current)
-- Returns: versions_deleted = 3, storage_freed_mb = 1024.5
```

### Purge Everything (⚠️ Destructive)

```sql
-- WARNING: Removes all data warehouse versions and history
-- Use only for complete reset
SELECT * FROM purge_all_data();
```

---

## Rollback Capabilities

### Promote Previous Version to Current

If v2 has issues and you need to go back to v1:

```sql
-- Promote v1 back to current
SELECT * FROM promote_version_to_current(p_version_id := 1);

-- Result:
-- status  │ message
-- ────────┼──────────────────────────────────────
-- success │ Version 1 promoted to current

-- Verify
SELECT * FROM v_data_load_versions;
-- v1 (homo_sapiens): is_current = TRUE
-- v2 (homo_sapiens): is_current = FALSE
```

All views now point to v1 again. No data loss—v2 remains for inspection.

---

## Monitoring & Maintenance

### View Load History

```sql
SELECT * FROM v_data_load_versions
ORDER BY load_date DESC;

-- Shows:
-- version_id │ organism      │ load_date │ is_current │ num_screens │ num_genes │ file_count
-- ───────────┼───────────────┼───────────┼────────────┼─────────────┼───────────┼────────────
--    2       │ homo_sapiens  │ 2026-06-05│ TRUE       │  2157       │  53173    │ 1952
--    1       │ homo_sapiens  │ 2026-06-04│ FALSE      │  2157       │  53173    │ 1952
```

### View ETL Performance

```sql
SELECT * FROM v_etl_pipeline_history;

-- Shows:
-- run_id │ version_id │ organism     │ run_date │ status    │ duration_seconds │ audit_entries
-- ───────┼────────────┼──────────────┼──────────┼───────────┼──────────────────┼───────────────
--   2    │    2       │ homo_sapiens │ 2026-06-05 │ completed │ 245.3            │ 8
--   1    │    1       │ homo_sapiens │ 2026-06-04 │ completed │ 248.1            │ 8
```

### View ETL Step Details

```sql
SELECT
    run_id,
    step_name,
    status,
    rows_inserted,
    rows_skipped,
    duration_seconds
FROM etl_audit_log
WHERE run_id = 2
ORDER BY step_order;

-- Shows:
-- run_id │ step_name                    │ status    │ rows_inserted │ rows_skipped │ duration
-- ───────┼──────────────────────────────┼───────────┼───────────────┼──────────────┼──────────
--   2    │ validate_staging_data        │ completed │ 0             │ 0            │ 1.2
--   2    │ load_screens                 │ completed │ 2157          │ 0            │ 3.1
--   2    │ load_genes                   │ completed │ 53173         │ 0            │ 8.5
--   2    │ build_screen_gene_raw        │ completed │ 1234567       │ 0            │ 145.2
--   2    │ build_fact_screen_gene       │ completed │ 1234567       │ 0            │ 87.3
--   2    │ build_dim_screen             │ completed │ 2157          │ 0            │ 2.1
--   2    │ build_dim_gene               │ completed │ 53173         │ 0            │ 12.4
```

### Check for Validation Issues

```sql
SELECT * FROM v_validation_issues;

-- Shows any rows with validation errors in staging tables
-- If empty: all data is valid
```

---

## Performance Tips

### Use Indexes

The schema includes indexes on:
- Version lookups: `data_load_version(organism, is_current)`
- ETL tracking: `etl_pipeline_run(run_id, is_current)`
- Version filtering: `fact_screen_gene(version_id, is_current)`

Example query (automatic index usage):

```sql
-- Fast (uses index on is_current)
SELECT * FROM v_current_fact_screen_gene
WHERE screen_id = 3060;

-- Slow (no index)
SELECT * FROM fact_screen_gene
WHERE version_id = 2
AND screen_id = 3060;  -- Should use WHERE is_current = TRUE instead
```

### Analyze Storage

```sql
-- Show biggest versions
SELECT
    version_id,
    organism,
    load_date,
    total_size_mb
FROM get_version_storage_details()
ORDER BY total_size_mb DESC;

-- Then purge the largest old versions if needed
SELECT * FROM purge_version(p_version_id := 1);
```

---

## Schema Reference

### Control Tables
- `data_load_version` – Track each staging load
- `etl_pipeline_run` – Track each ETL execution
- `etl_audit_log` – Detailed step-by-step execution log

### Staging Tables
- `staging_screen_json` – Raw JSON data (versioned)
- `staging_screen_gene_tsv` – Raw TSV data (versioned)

### Integration Tables
- `screen` – Core screens (versioned)
- `gene` – Core genes (versioned)
- `publication` – Publications (shared)

### Processing Tables
- `screen_gene_raw` – Denormalized working data (versioned)

### Fact/Dimension Tables
- `fact_screen_gene` – Aggregated relationships (versioned)
- `dim_screen` – Screen dimension (versioned)
- `dim_gene` – Gene dimension (versioned)
- `fact_screen_gene_publication` – Publication links (versioned)

### Views (Current Data Only)
- `v_current_fact_screen_gene` – Use for analysis
- `v_current_dim_screen`
- `v_current_dim_gene`
- `v_current_fact_screen_gene_publication`

### Convenience Views
- `v_data_load_versions` – Load history
- `v_etl_pipeline_history` – ETL runs
- `v_etl_run_summary` – Run summaries
- `v_validation_issues` – Data quality issues
- `v_version_storage_usage` – Storage per version

---

## Troubleshooting

### ETL Pipeline Failed

Check audit log:

```sql
SELECT * FROM etl_audit_log
WHERE run_id = 2
AND status = 'failed'
ORDER BY step_order DESC;
```

### Validation Errors in Staging

```sql
SELECT *
FROM staging_screen_json
WHERE version_id = 2
AND validation_errors IS NOT NULL;
```

### Storage Running Low

```sql
-- Identify which versions consume most space
SELECT * FROM get_version_storage_details()
ORDER BY total_size_mb DESC LIMIT 5;

-- Purge old versions
SELECT * FROM purge_old_versions();
```

### Accidentally Promoted Wrong Version

```sql
-- Promote the correct version back
SELECT * FROM promote_version_to_current(p_version_id := 2);
```
