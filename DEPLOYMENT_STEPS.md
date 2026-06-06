# RETICLE Versioned Data Warehouse - Deployment Steps

## Prerequisites (One-time Setup)

### 1. Install Python Dependencies

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts
pip install psycopg2-binary sqlalchemy python-dotenv tabulate
```

### 2. Verify `.env` Configuration

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts
cat .env
```

Expected content:
```
DB_HOST=reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_USER=reticle_admin
DB_PASSWORD=<your-password>
DB_NAME=reticle_biogrid
DB_SSL=true
```

If `.env` doesn't exist or is missing values, update it now.

### 3. Test Database Connection

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts
python3 database.py
```

Expected output:
```
Testing Database Connection
================================================================================
Testing psycopg2 connection...
✓ PostgreSQL: PostgreSQL 15.x on x86_64...
Testing SQLAlchemy connection...
✓ Tables in public schema: 50
✓ All database connections successful
```

**If this fails**: Check `.env` credentials and database availability.

---

## Phase 1: Apply Database Schema (Run Once)

### Step 1: Apply Migration 0009 (Create Versioned Tables)

```bash
cd /Volumes/SD\ Media/projects/RETICLE
psql \
  -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
  -U reticle_admin \
  -d reticle_biogrid \
  -f database/migrations/0009_versioned_data_warehouse.sql
```

Or if you have `$DB_HOST` etc. environment variables:
```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f database/migrations/0009_versioned_data_warehouse.sql
```

**Expected output**:
```
CREATE TABLE
CREATE TABLE
...
CREATE VIEW
CREATE INDEX
... (100+ lines)
```

**Verify success**:
```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) as table_count FROM information_schema.tables WHERE table_schema = 'public';"
```

### Step 2: Apply ETL Pipeline Functions

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f database/etl_pipeline.sql
```

**Expected output**:
```
CREATE FUNCTION
CREATE FUNCTION
... (8 functions)
```

### Step 3: Apply Maintenance Utilities

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f database/maintenance_utilities.sql
```

**Expected output**:
```
CREATE FUNCTION
CREATE VIEW
... (utilities)
```

### Step 4: Verify All Tables/Views Created

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME << 'SQL'
\dt data_load_version
\dt staging_screen_json
\dt staging_screen_gene_tsv
\dt fact_screen_gene
\dv v_current_fact_screen_gene
SQL
```

---

## Phase 2: Load Your Data

### Step 5: Make Bash Scripts Executable

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts
chmod +x warehouse-load.sh warehouse-run-etl.sh warehouse-maintenance.sh
```

### Step 6: Load Homo Sapiens Data

```bash
cd /Volumes/SD\ Media/projects/RETICLE/scripts
./warehouse-load.sh homo_sapiens
```

**Expected output**:
```
================================================================================
[INFO] Loading homo_sapiens data
[INFO] Creating version record for homo_sapiens...
[INFO] ✓ Created version_id: 1

[INFO] Loading JSON files for homo_sapiens...
[INFO] Found 1 JSON file(s)
[INFO] ✓ Loaded 2,157 screens

[INFO] Loading TSV files for homo_sapiens...
[INFO] Found 1,952 TSV file(s)
[INFO]   Processing file 100/1952...
[INFO]   Processing file 200/1952...
...
[INFO] ✓ Loaded 1,234,567 gene-screen pairs

[INFO] Validating staging data...
[INFO] ✓ Validation complete (0 error(s))

================================================================================
STAGING LOAD SUMMARY
================================================== ============================
screens_loaded ................................. 2,157
genes_loaded ................................... 1,234,567
validation_errors .............................. 0
files_processed ................................ 1,952
================================================================================
[INFO] Staging load completed successfully
[INFO] Next step: Run ./warehouse-run-etl.sh 1
```

**Note the version_id: 1**

### Step 7: Load Mus Musculus Data (Optional)

```bash
./warehouse-load.sh mus_musculus "Mouse data"
```

**Returns**: version_id: 2

---

## Phase 3: Run ETL Pipeline

### Step 8: Run ETL for Version 1

```bash
./warehouse-run-etl.sh 1 --show-info
```

**Expected output**:
```
================================================================================
ETL PIPELINE EXECUTION
================================================================================
Version ID: 1
Pipeline Version: 1.0.0

VERSION INFORMATION
================================================================================
Version ID:        1
Organism:          homo_sapiens
Load Date:         2026-06-05 10:30:45.123456
Status:            valid
Is Current:        False
Screens:           2,157
Genes:             53,173
Gene-Screen Hits:  1,234,567
Files Processed:   1,952
================================================================================

Executing run_etl_pipeline() function...

================================================================================
ETL PIPELINE RESULT
================================================================================
Run ID:       1
Status:       completed
Duration:     245.3s
Message:      ETL pipeline completed successfully
================================================================================

ETL AUDIT LOG
================================================================================

  validate_staging_data:
    Status:           completed
    Rows processed:   1952
    Rows skipped:     0
    Duration:         1.2s

  load_screens:
    Status:           completed
    Rows inserted:    2157
    Duration:         3.1s

  load_genes:
    Status:           completed
    Rows inserted:    53173
    Duration:         8.5s

  build_screen_gene_raw:
    Status:           completed
    Rows inserted:    1234567
    Duration:         145.2s

  build_fact_screen_gene:
    Status:           completed
    Rows inserted:    1234567
    Duration:         87.3s

  build_dim_screen:
    Status:           completed
    Rows inserted:    2157
    Duration:         2.1s

  build_dim_gene:
    Status:           completed
    Rows inserted:    53173
    Duration:         12.4s

  build_fact_screen_gene_publication:
    Status:           completed
    Duration:         0.1s

================================================================================
[INFO] ETL pipeline completed successfully
[INFO] Next step: Run './warehouse-maintenance.sh --show-storage' to verify
```

Takes ~4-5 minutes total.

### Step 9: Run ETL for Version 2 (if you loaded mus_musculus)

```bash
./warehouse-run-etl.sh 2
```

---

## Phase 4: Verify Results

### Step 10: List All Versions

```bash
./warehouse-maintenance.sh --list-versions
```

**Expected output**:
```
================================================================================
DATA LOAD VERSIONS
================================================================================

  Version  Organism       Date        Status   Current  Screens      Genes  Files  Description
───────────────────────────────────────────────────────────────────────────────────────────────
       2  mus_musculus   2026-06-05  valid    ✓ CURRENT  2,157  53,173  1,952  Mouse data
       1  homo_sapiens   2026-06-05  valid              2,157  53,173  1,952  Auto-loaded homo_sapiens data

================================================================================
```

### Step 11: Check Storage Usage

```bash
./warehouse-maintenance.sh --show-storage
```

### Step 12: Query Your Data

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME << 'SQL'
SELECT COUNT(*) as fact_count FROM v_current_fact_screen_gene;
SELECT COUNT(*) as screen_count FROM v_current_dim_screen;
SELECT COUNT(*) as gene_count FROM v_current_dim_gene;
SELECT DISTINCT organism FROM v_current_dim_screen;
SQL
```

---

## Complete Command Sequence (Copy-Paste)

If everything is ready, here's the complete sequence:

```bash
# 1. Install dependencies
cd /Volumes/SD\ Media/projects/RETICLE/scripts
pip install psycopg2-binary sqlalchemy python-dotenv tabulate

# 2. Test connection
python3 database.py

# 3. Apply schema (from project root)
cd /Volumes/SD\ Media/projects/RETICLE
psql -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
     -U reticle_admin \
     -d reticle_biogrid \
     -f database/migrations/0009_versioned_data_warehouse.sql

psql -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
     -U reticle_admin \
     -d reticle_biogrid \
     -f database/etl_pipeline.sql

psql -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
     -U reticle_admin \
     -d reticle_biogrid \
     -f database/maintenance_utilities.sql

# 4. Load and run ETL
cd /Volumes/SD\ Media/projects/RETICLE/scripts
chmod +x warehouse-*.sh
./warehouse-load.sh homo_sapiens
./warehouse-run-etl.sh 1 --show-info

# 5. Verify
./warehouse-maintenance.sh --list-versions
```

---

## Troubleshooting

### Database Connection Fails
```bash
# Check .env
cat .env

# Test psql directly
psql -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
     -U reticle_admin \
     -d reticle_biogrid \
     -c "SELECT version();"
```

### Schema Migration Fails
```bash
# Check if tables already exist
psql -h reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com \
     -U reticle_admin \
     -d reticle_biogrid \
     -c "\dt data_load_version"
```

### Staging Load Fails
```bash
# Check data files exist
ls -lh ../Domain/Data/homo_sapiens/BIOGRID-ORCS-SCREEN_*.screen.tab.txt | head -5
ls -lh ../Domain/Data/BIOGRID-ORCS-HOMO*.json

# Check Python environment
python3 --version
python3 -c "import psycopg2; print(psycopg2.__version__)"
```

### ETL Fails
```bash
# Check staging tables have data
psql -h $DB_HOST -U $DB_USER -d $DB_NAME \
     -c "SELECT COUNT(*) FROM staging_screen_json WHERE version_id = 1;"

# Check ETL audit log for errors
psql -h $DB_HOST -U $DB_USER -d $DB_NAME \
     -c "SELECT * FROM etl_audit_log WHERE run_id = 1 ORDER BY step_order;"
```

---

**Start here**: [Step 1 - Install Dependencies](#prerequisites-one-time-setup)
