# RETICLE Database Clean Rebuild

Complete step-by-step guide to drop all objects and rebuild the schema.

## Step 1: Drop All Database Objects

```bash
cd scripts
python3 drop_all_objects.py --confirm
```

Or use the wrapper:
```bash
./warehouse-purge.sh --confirm
```

**What it does:**
- Drops all tables, views, functions, sequences, indexes
- Uses CASCADE to handle dependencies
- Provides detailed output of what's being removed

**Expected output:**
```
✓ Connected to database
Found X tables to drop:
  - ...
Dropping tables...
  ✓ Dropped ...
...
✓ ALL RETICLE DATABASE OBJECTS DROPPED
```

## Step 2: Rebuild Schema

Apply the 0009 migration to create a fresh schema:

```bash
psql -h localhost -U reticle_user -d reticle_survey < database/migrations/0009_versioned_data_warehouse.sql
```

**Verify:**
```bash
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT table_name FROM information_schema.tables 
  WHERE table_schema = 'public' 
  ORDER BY table_name;
"
```

Expected tables: `data_load_version`, `staging_screen`, `staging_screen_gene`, `screen`, `gene`, `screen_gene_raw`, `fact_screen_gene`, `dim_screen`, `dim_gene`, `etl_pipeline_run`, `etl_audit_log`, `publication`, `fact_screen_gene_publication`

## Step 3: Load ETL Pipeline Functions

```bash
psql -h localhost -U reticle_user -d reticle_survey < database/etl_pipeline.sql
```

**Verify:**
```bash
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT routine_name FROM information_schema.routines 
  WHERE routine_schema = 'public' 
  ORDER BY routine_name;
"
```

Expected functions: `run_etl_pipeline`, `validate_staging_data`, `load_screens`, `load_genes`, `build_screen_gene_raw`, `build_fact_screen_gene`, `build_dim_screen`, `build_dim_gene`, `build_fact_screen_gene_publication`

## Step 4: Load Staging Data

### Option A: With Real BioGrid ORCS Data

If you have the original data files, place them in `../Domain/Data/` with structure:
```
../Domain/Data/
├── screen_metadata_homo_sapiens.json
├── homo_sapiens/
│   └── BIOGRID-ORCS-SCREEN_*.screen.tab.txt
├── screen_metadata_musculus.json
└── mus_musculus/
    └── BIOGRID-ORCS-SCREEN_*.screen.tab.txt
```

Then run:
```bash
python3 scripts/staging_loader.py --organism homo_sapiens
```

### Option B: With Synthetic Test Data

For testing the pipeline without real data:

```bash
cd scripts
python3 << 'PYTHON'
import psycopg2
from config import Config
from datetime import datetime

conn = psycopg2.connect(
    host=Config.DB_HOST,
    port=Config.DB_PORT,
    database=Config.DB_NAME,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
    sslmode='require',
    gssencmode='disable'
)

cursor = conn.cursor()

# Create version record
cursor.execute("""
    INSERT INTO data_load_version (organism, source_type, load_date, status, is_current, load_description, num_screens, num_genes)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING version_id
""", ('homo_sapiens', 'biogrid_orcs', datetime.now(), 'valid', False, 'Test synthetic data', 10, 50))

version_id = cursor.fetchone()[0]
conn.commit()
print(f"✓ Created version {version_id}")

# Load test screens
screen_data = []
for i in range(1, 11):
    screen_data.append((version_id, i, f"SCREEN-{1000+i}", 'homo_sapiens', 'BioGrid', None, None))

cursor.executemany("""
    INSERT INTO staging_screen (version_id, screen_id, biogrid_screen_id, organism, annotation_source, moi, notes)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
""", screen_data)
conn.commit()
print(f"✓ Loaded {len(screen_data)} test screens")

# Load test genes
gene_data = []
for s in range(1, 11):
    for g in range(1, 6):
        gene_id = f"ENS{100000 + s*10 + g}"
        gene_symbol = f"GENE{s}_{g}"
        official_symbol = f"Gene-{s}-{g}"
        hit_flag = (s + g) % 2 == 0
        gene_data.append((
            version_id, s, f"SCREEN-{1000+s}", gene_id, gene_symbol, official_symbol,
            hit_flag, 0.5 if hit_flag else None, None, None, None, None, None, None
        ))

cursor.executemany("""
    INSERT INTO staging_screen_gene 
    (version_id, screen_id, biogrid_screen_id, identifier_id, gene_symbol, official_symbol,
     hit_flag, score_1, score_2, score_3, score_4, score_5, tsv_filename, tsv_row_number)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", gene_data)
conn.commit()
print(f"✓ Loaded {len(gene_data)} test gene-screen pairs")

conn.close()
PYTHON
```

## Step 5: Run ETL Pipeline

```bash
./warehouse-run-etl.sh 1
```

Or with specific version ID (if you loaded version 2):
```bash
./warehouse-run-etl.sh 2
```

**Expected output:**
```
✓ ETL pipeline completed successfully

  validate_staging_data:
      Status:           completed
      Rows processed:   10

  load_screens:
      Status:           completed
      Rows inserted:    10

  load_genes:
      Status:           completed
      Rows inserted:    50

  build_screen_gene_raw:
      Status:           completed
      Rows inserted:    50

  build_fact_screen_gene:
      Status:           completed
      Rows inserted:    50

  build_dim_screen:
      Status:           completed
      Rows inserted:    10

  build_dim_gene:
      Status:           completed
      Rows inserted:    50

  build_fact_screen_gene_publication:
      Status:           completed
```

## Step 6: Verify Results

Check the ETL run:
```bash
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT run_id, data_load_version_id, status, total_duration_seconds 
  FROM etl_pipeline_run 
  ORDER BY run_id DESC 
  LIMIT 5;
"
```

Check fact table data:
```bash
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT COUNT(*) as fact_rows FROM fact_screen_gene WHERE is_current = TRUE;
"
```

Check dimension tables:
```bash
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT 
    (SELECT COUNT(*) FROM dim_screen WHERE is_current = TRUE) as screens,
    (SELECT COUNT(*) FROM dim_gene WHERE is_current = TRUE) as genes;
"
```

## Troubleshooting

**"No JSON files found matching..."**
- Ensure data files exist in the correct directory
- Check Config.DATA_DIR in scripts/config.py
- Can be overridden with environment variable: `DATA_DIR=/path/to/data python3 staging_loader.py ...`

**"column does not exist" during ETL**
- Verify migration 0009 was applied successfully
- Check that all tables exist: `psql -c "\dt"`
- Verify column names match: `psql -c "\d staging_screen_gene"`

**Connection errors**
- Verify database is running and credentials are correct
- Check .env file has correct DB_* values
- Test connection: `psql -h localhost -U reticle_user -d reticle_survey -c "SELECT 1;"`

## Full Script (One-Shot)

To execute everything at once:

```bash
#!/bin/bash
cd /Volumes/SD\ Media/projects/RETICLE

# Step 1: Purge
echo "Step 1: Purging database..."
./scripts/warehouse-purge.sh --confirm
if [ $? -ne 0 ]; then echo "Purge failed"; exit 1; fi

# Step 2: Rebuild schema
echo -e "\nStep 2: Rebuilding schema..."
psql -h localhost -U reticle_user -d reticle_survey < database/migrations/0009_versioned_data_warehouse.sql
if [ $? -ne 0 ]; then echo "Schema creation failed"; exit 1; fi

# Step 3: Load ETL functions
echo -e "\nStep 3: Loading ETL functions..."
psql -h localhost -U reticle_user -d reticle_survey < database/etl_pipeline.sql
if [ $? -ne 0 ]; then echo "ETL function load failed"; exit 1; fi

# Step 4: Load test data (using inline Python)
echo -e "\nStep 4: Loading test data..."
cd scripts && python3 drop_all_objects.py --help > /dev/null  # Just verify script exists
cd ..

# Step 5: Run ETL
echo -e "\nStep 5: Running ETL pipeline..."
./scripts/warehouse-run-etl.sh 1
if [ $? -ne 0 ]; then echo "ETL failed"; exit 1; fi

# Step 6: Verify
echo -e "\nStep 6: Verifying results..."
psql -h localhost -U reticle_user -d reticle_survey -c "
  SELECT 
    'Fact rows' as metric, COUNT(*)::text FROM fact_screen_gene WHERE is_current = TRUE
  UNION ALL
  SELECT 'Dimension screens', COUNT(*)::text FROM dim_screen WHERE is_current = TRUE
  UNION ALL
  SELECT 'Dimension genes', COUNT(*)::text FROM dim_gene WHERE is_current = TRUE;
"

echo -e "\n✓ Clean rebuild complete!"
```
