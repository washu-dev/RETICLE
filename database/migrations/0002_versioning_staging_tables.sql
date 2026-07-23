/**
 * RETICLE Versioning & Staging Tables (0004)
 *
 * Creates tables for tracking data versions and staging ETL inputs:
 * - data_load_version: Version control for each data load
 * - etl_pipeline_run: ETL execution records
 * - etl_audit_log: Detailed step-level audit trail
 * - staging_screen, staging_screen_gene: Raw input from JSON/TSV
 * - screen_gene_raw, fact_screen_gene: Denormalized working data
 * - dim_screen, dim_gene: Dimensional tables
 * - fact_screen_gene_publication: Publication fact table
 *
 * These tables support the versioned data warehouse model where each
 * data load gets a version_id and can be independently managed.
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

CREATE INDEX IF NOT EXISTS idx_data_load_version_current ON data_load_version(organism, is_current)
    WHERE is_current = TRUE;

CREATE TABLE IF NOT EXISTS etl_pipeline_run (
    run_id SERIAL PRIMARY KEY,
    data_load_version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    pipeline_version VARCHAR(50),  -- ETL code version
    run_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    total_duration_seconds NUMERIC,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_etl_pipeline_run_current ON etl_pipeline_run(run_id, is_current)
    WHERE is_current = TRUE;

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

-- ============================================================================
-- STAGING TABLES (Versioned, raw input)
-- ============================================================================

CREATE TABLE IF NOT EXISTS staging_screen (
    staging_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    screen_id INT NOT NULL,
    biogrid_screen_id VARCHAR(100) NOT NULL,
    organism VARCHAR(50) NOT NULL,
    annotation_source VARCHAR(100),
    moi TEXT,
    notes TEXT,
    validated BOOLEAN DEFAULT FALSE,
    validation_errors TEXT,
    loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, biogrid_screen_id)
);

CREATE INDEX IF NOT EXISTS idx_staging_screen_version ON staging_screen(version_id);

CREATE TABLE IF NOT EXISTS staging_screen_gene (
    staging_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    screen_id INT NOT NULL,
    identifier_id VARCHAR(250) NOT NULL,
    gene_symbol VARCHAR(100),
    biogrid_screen_id VARCHAR(100),
    hit_flag BOOLEAN,
    score_1 NUMERIC,
    score_2 NUMERIC,
    score_3 NUMERIC,
    score_4 NUMERIC,
    score_5 NUMERIC,
    validated BOOLEAN DEFAULT FALSE,
    validation_errors TEXT,
    loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, biogrid_screen_id, identifier_id)
);

CREATE INDEX IF NOT EXISTS idx_staging_screen_gene_version ON staging_screen_gene(version_id);

-- ============================================================================
-- PROCESSED TABLES (Versioned, working data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen_gene_raw (
    screen_gene_raw_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    biogrid_screen_id VARCHAR(100),
    identifier_id VARCHAR(250),
    hit_flag BOOLEAN,
    score_1 NUMERIC,
    score_2 NUMERIC,
    score_3 NUMERIC,
    score_4 NUMERIC,
    score_5 NUMERIC,
    raw_score NUMERIC,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_version ON screen_gene_raw(version_id, is_current);

CREATE TABLE IF NOT EXISTS fact_screen_gene (
    fact_screen_gene_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    hit_count INT,
    hit_percentage NUMERIC,
    avg_raw_score NUMERIC,
    total_publications INT,
    condition_count INT,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_version ON fact_screen_gene(version_id, is_current);

CREATE TABLE IF NOT EXISTS dim_screen (
    dim_screen_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    biogrid_screen_id VARCHAR(100),
    organism VARCHAR(50),
    annotation_source VARCHAR(100),
    total_genes INT,
    total_genes_hit INT,
    total_publications INT,
    avg_hit_percentage NUMERIC,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id)
);

CREATE INDEX IF NOT EXISTS idx_dim_screen_version ON dim_screen(version_id, is_current);

CREATE TABLE IF NOT EXISTS dim_gene (
    dim_gene_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    identifier_id VARCHAR(250),
    gene_symbol VARCHAR(100),
    organism VARCHAR(50),
    total_screens INT,
    total_screens_hit INT,
    total_publications INT,
    avg_hit_percentage NUMERIC,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_dim_gene_version ON dim_gene(version_id, is_current);

CREATE TABLE IF NOT EXISTS fact_screen_gene_publication (
    fact_screen_gene_publication_id SERIAL PRIMARY KEY,
    version_id INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id INT NOT NULL REFERENCES screen(screen_id),
    gene_id INT NOT NULL REFERENCES gene(gene_id),
    publication_id INT NOT NULL REFERENCES publication(publication_id),
    hit_flag BOOLEAN,
    score_1 NUMERIC,
    score_2 NUMERIC,
    score_3 NUMERIC,
    score_4 NUMERIC,
    score_5 NUMERIC,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(version_id, screen_id, gene_id, publication_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_publication_version ON fact_screen_gene_publication(version_id, is_current);
