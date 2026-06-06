/**
 * RETICLE Versioned Data Warehouse Schema
 *
 * Replaces previous approach with versioned staging → integration → facts
 * Supports rollback, purge, and full audit trail.
 *
 * Versioning Strategy:
 * - Each data load (JSON/TSV upload) gets a version_id
 * - Each ETL run gets a run_id
 * - New data marks old versions as historical
 * - Can purge specific version or all versions
 */

-- ============================================================================
-- VERSION CONTROL TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_load_version (
    version_id SERIAL PRIMARY KEY,
    organism VARCHAR(50) NOT NULL,  -- homo_sapiens, mus_musculus
    source_type VARCHAR(20) NOT NULL,  -- 'biogrid_orcs', etc
    load_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    loaded_by VARCHAR(100),
    load_description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, valid, invalid, archived
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    num_screens INT,
    num_genes INT,
    num_gene_hits INT,
    file_count INT,
    total_file_size_bytes BIGINT,
    json_filenames TEXT[],  -- Array of JSON source filenames
    tsv_filenames TEXT[],   -- Array of TSV source filenames
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(organism, source_type, load_date)
);

CREATE TABLE IF NOT EXISTS etl_pipeline_run (
    run_id SERIAL PRIMARY KEY,
    data_load_version_id INT NOT NULL REFERENCES data_load_version(version_id),
    pipeline_version VARCHAR(50),  -- ETL code version
    run_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    total_duration_seconds NUMERIC,
    error_message TEXT,

    CONSTRAINT fk_data_load_version FOREIGN KEY (data_load_version_id)
        REFERENCES data_load_version(version_id)
);

CREATE TABLE IF NOT EXISTS etl_audit_log (
    audit_id SERIAL PRIMARY KEY,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    step_name VARCHAR(100) NOT NULL,  -- 'validate_screens', 'upsert_genes', etc
    step_order INT,
    status VARCHAR(20),  -- 'started', 'completed', 'failed'
    rows_processed INT,
    rows_inserted INT,
    rows_updated INT,
    rows_skipped INT,
    duration_seconds NUMERIC,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_data_load_version_current ON data_load_version(organism, is_current)
    WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_etl_pipeline_run_current ON etl_pipeline_run(run_id, is_current)
    WHERE is_current = TRUE;

-- ============================================================================
-- STAGING TABLES (Versioned, raw input)
-- ============================================================================

CREATE TABLE IF NOT EXISTS staging_screen (
    staging_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    screen_id INT NOT NULL,
    biogrid_screen_id VARCHAR(50) NOT NULL,
    organism VARCHAR(50) NOT NULL,
    annotation_source VARCHAR(100),
    moi TEXT,
    notes TEXT,
    validated BOOLEAN DEFAULT FALSE,
    validation_errors TEXT,
    loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, biogrid_screen_id)
);

CREATE TABLE IF NOT EXISTS staging_screen_gene (
    staging_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    screen_id INT NOT NULL,
    biogrid_screen_id VARCHAR(50) NOT NULL,
    identifier_id VARCHAR(50) NOT NULL,
    gene_symbol VARCHAR(250),
    official_symbol VARCHAR(250),
    hit_flag BOOLEAN,
    score_1 NUMERIC,
    score_2 NUMERIC,
    score_3 NUMERIC,
    score_4 NUMERIC,
    score_5 NUMERIC,
    tsv_filename VARCHAR(255),
    tsv_row_number INT,
    validated BOOLEAN DEFAULT FALSE,
    validation_errors TEXT,
    loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_staging_screen_version ON staging_screen(version_id);
CREATE INDEX IF NOT EXISTS idx_staging_screen_gene_version ON staging_screen_gene(version_id);
CREATE INDEX IF NOT EXISTS idx_staging_screen_gene_hit ON staging_screen_gene(version_id, hit_flag);

-- ============================================================================
-- INTEGRATION TABLES (Normalized reference data with version lineage)
-- ============================================================================

-- Drop old screen table, recreate with versioning
DROP TABLE IF EXISTS screen CASCADE;
CREATE TABLE screen (
    screen_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id),
    biogrid_screen_id VARCHAR(50) NOT NULL,
    organism VARCHAR(50) NOT NULL,
    annotation_source VARCHAR(100),
    moi TEXT,
    notes TEXT,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, biogrid_screen_id)
);

DROP TABLE IF EXISTS gene CASCADE;
CREATE TABLE gene (
    gene_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id),
    identifier_id VARCHAR(50) NOT NULL,
    gene_symbol VARCHAR(250),
    organism VARCHAR(50),
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, identifier_id)
);

-- Keep publication as-is (not versioned, shared across all data versions)
-- But track which versions reference it
ALTER TABLE publication ADD COLUMN IF NOT EXISTS first_referenced_version_id INT;

-- ============================================================================
-- PROCESSING TABLE (Denormalized working data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen_gene_raw (
    screen_gene_raw_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    biogrid_screen_id VARCHAR(50),
    identifier_id VARCHAR(50),
    hit_flag BOOLEAN,
    score_1 NUMERIC,
    score_2 NUMERIC,
    score_3 NUMERIC,
    score_4 NUMERIC,
    score_5 NUMERIC,
    raw_score NUMERIC,  -- Aggregate of scores
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_version ON screen_gene_raw(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_screen ON screen_gene_raw(screen_id, version_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_gene ON screen_gene_raw(gene_id, version_id);

-- ============================================================================
-- FACT/DIMENSION TABLES (Versioned for analytics)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fact_screen_gene (
    fact_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),

    -- Aggregations
    hit_count INT,
    hit_percentage NUMERIC(5,2),
    avg_raw_score NUMERIC,
    total_publications INT,
    condition_count INT,

    -- Metadata
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id)
);

CREATE TABLE IF NOT EXISTS dim_screen (
    dim_screen_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    biogrid_screen_id VARCHAR(50),
    organism VARCHAR(50),
    annotation_source VARCHAR(100),
    moi TEXT,
    notes TEXT,

    -- Denormalized aggregates
    total_genes INT,
    total_genes_hit INT,
    total_publications INT,
    avg_hit_percentage NUMERIC(5,2),

    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id)
);

CREATE TABLE IF NOT EXISTS dim_gene (
    dim_gene_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    identifier_id VARCHAR(50),
    gene_symbol VARCHAR(250),
    organism VARCHAR(50),

    -- Denormalized aggregates
    total_screens INT,
    total_screens_hit INT,
    total_publications INT,
    avg_hit_percentage NUMERIC(5,2),

    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, gene_id)
);

CREATE TABLE IF NOT EXISTS fact_screen_gene_publication (
    fact_pub_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    publication_id INT NOT NULL REFERENCES publication(publication_id),

    hit_flag BOOLEAN,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id, publication_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_version ON fact_screen_gene(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_screen_version ON dim_screen(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_gene_version ON dim_gene(version_id, is_current);

-- ============================================================================
-- VIEWS FOR CURRENT DATA (Convenience)
-- ============================================================================

CREATE OR REPLACE VIEW v_current_fact_screen_gene AS
SELECT * FROM fact_screen_gene WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_current_dim_screen AS
SELECT * FROM dim_screen WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_current_dim_gene AS
SELECT * FROM dim_gene WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_current_fact_screen_gene_publication AS
SELECT * FROM fact_screen_gene_publication WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_data_load_versions AS
SELECT
    version_id,
    organism,
    load_date,
    status,
    is_current,
    num_screens,
    num_genes,
    num_gene_hits,
    file_count,
    ROUND(total_file_size_bytes / 1024 / 1024, 2) as total_file_size_mb,
    created_at
FROM data_load_version
ORDER BY load_date DESC;

CREATE OR REPLACE VIEW v_etl_pipeline_history AS
SELECT
    r.run_id,
    v.version_id,
    v.organism,
    v.load_date,
    r.run_date,
    r.status,
    r.is_current,
    r.total_duration_seconds,
    r.error_message,
    (SELECT COUNT(*) FROM etl_audit_log WHERE run_id = r.run_id) as audit_log_entries
FROM etl_pipeline_run r
JOIN data_load_version v ON r.data_load_version_id = v.version_id
ORDER BY r.run_date DESC;

-- ============================================================================
-- STORAGE TRACKING VIEW
-- ============================================================================

CREATE OR REPLACE VIEW v_version_storage_usage AS
SELECT
    v.version_id,
    v.organism,
    v.load_date,
    v.is_current,
    pg_size_pretty(
        pg_total_relation_size('staging_screen'::regclass) *
        (SELECT COUNT(*) FROM staging_screen WHERE version_id = v.version_id) /
        NULLIF((SELECT COUNT(*) FROM staging_screen), 0)
    ) as staging_screen_size,
    pg_size_pretty(
        pg_total_relation_size('staging_screen_gene'::regclass) *
        (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = v.version_id) /
        NULLIF((SELECT COUNT(*) FROM staging_screen_gene), 0)
    ) as staging_screen_gene_size,
    (SELECT COUNT(*) FROM staging_screen WHERE version_id = v.version_id) as screen_json_rows,
    (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = v.version_id) as screen_gene_tsv_rows,
    (SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = v.version_id) as screen_gene_raw_rows,
    (SELECT COUNT(*) FROM fact_screen_gene WHERE version_id = v.version_id) as fact_screen_gene_rows
FROM data_load_version v
ORDER BY v.load_date DESC;
