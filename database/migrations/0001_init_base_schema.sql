/**
 * RETICLE Base Schema Bootstrap (0001)
 *
 * Creates foundational tables for RETICLE data model:
 * - PUBLICATION: Paper/study metadata (1 per BioGrid ORCS entry)
 * - GENE: Reference gene data (symbol, IDs, organism)
 * - LIBRARY: CRISPR library metadata (Brunello, Brie, etc.)
 * - SCREEN: Individual experimental screens
 * - SCREEN_CONDITION: Treatment/control conditions within a screen
 * - SCREEN_COMPARISON: Pairwise comparisons between conditions
 * - SCREEN_GENE_SCORE: Raw scored genes (fact table, typically in Parquet)
 * - GENE_ORTHOLOG: Cross-species gene mapping (mouse ↔ human)
 *
 * This bootstrap creates the minimum schema needed by downstream migrations
 * and ETL pipelines. All tables use IF NOT EXISTS for idempotency.
 */

-- ============================================================================
-- PUBLICATION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS publication (
    publication_id SERIAL PRIMARY KEY,
    pmid VARCHAR(20) UNIQUE,
    title TEXT,
    journal VARCHAR(255),
    year INTEGER,
    doi VARCHAR(100),
    methods_text TEXT,
    full_text_available BOOLEAN DEFAULT FALSE,
    abstract_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_publication_pmid ON publication(pmid);
CREATE INDEX IF NOT EXISTS idx_publication_year ON publication(year);

-- ============================================================================
-- GENE TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS gene (
    gene_id SERIAL PRIMARY KEY,
    gene_symbol VARCHAR(100) NOT NULL,
    entrez_id VARCHAR(50),
    ensembl_id VARCHAR(100),
    organism VARCHAR(50) NOT NULL, -- homo_sapiens, mus_musculus
    chromosome VARCHAR(10),
    gene_type VARCHAR(50), -- protein_coding, lncRNA, pseudogene, etc.
    description TEXT,
    darkness_score FLOAT, -- 0.0 to 10.0, Phase 4 output
    pubmed_count INTEGER DEFAULT 0,
    n_specific_go_terms INTEGER DEFAULT 0,
    last_darkness_update DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(gene_symbol, organism),
    UNIQUE(entrez_id, organism) -- Only unique within an organism
);

CREATE INDEX IF NOT EXISTS idx_gene_symbol ON gene(gene_symbol);
CREATE INDEX IF NOT EXISTS idx_gene_entrez ON gene(entrez_id);
CREATE INDEX IF NOT EXISTS idx_gene_organism ON gene(organism);

-- ============================================================================
-- GENE ORTHOLOG TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS gene_ortholog (
    gene_ortholog_id SERIAL PRIMARY KEY,
    gene_id_1 INT NOT NULL REFERENCES gene(gene_id) ON DELETE CASCADE,
    gene_id_2 INT NOT NULL REFERENCES gene(gene_id) ON DELETE CASCADE,
    confidence VARCHAR(20), -- HIGH, MEDIUM, LOW
    source VARCHAR(100), -- Ensembl, NCBI, manual
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(gene_id_1, gene_id_2),
    CHECK (gene_id_1 < gene_id_2) -- Enforce ordering to prevent duplicates
);

CREATE INDEX IF NOT EXISTS idx_gene_ortholog_gene1 ON gene_ortholog(gene_id_1);
CREATE INDEX IF NOT EXISTS idx_gene_ortholog_gene2 ON gene_ortholog(gene_id_2);

-- ============================================================================
-- LIBRARY TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS library (
    library_id SERIAL PRIMARY KEY,
    library_name VARCHAR(100) NOT NULL, -- Brunello, Brie, GeCKOv2, Caprano
    library_version VARCHAR(50),
    organism VARCHAR(50) NOT NULL,
    total_genes INTEGER,
    sgrnas_per_gene INTEGER,
    total_sgrnas INTEGER,
    source VARCHAR(100), -- Addgene, GPP, custom
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(library_name, library_version, organism)
);

CREATE INDEX IF NOT EXISTS idx_library_organism ON library(organism);

-- ============================================================================
-- LIBRARY_GENE JUNCTION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS library_gene (
    library_gene_id SERIAL PRIMARY KEY,
    library_id INT NOT NULL REFERENCES library(library_id) ON DELETE CASCADE,
    gene_id INT NOT NULL REFERENCES gene(gene_id) ON DELETE CASCADE,
    n_sgrnas INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(library_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_library_gene_library ON library_gene(library_id);
CREATE INDEX IF NOT EXISTS idx_library_gene_gene ON library_gene(gene_id);

-- ============================================================================
-- SCREEN TABLE (Core experimental metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen (
    screen_id SERIAL PRIMARY KEY,
    biogrid_screen_id VARCHAR(100),
    depmap_screen_id VARCHAR(100),
    publication_id INT NOT NULL REFERENCES publication(publication_id) ON DELETE RESTRICT,
    library_id INT REFERENCES library(library_id) ON DELETE SET NULL,
    organism VARCHAR(50) NOT NULL,
    cell_line VARCHAR(255),
    cell_type VARCHAR(100),
    screen_modality VARCHAR(50), -- KO, CRISPRa, CRISPRi
    algorithm VARCHAR(100),
    algorithm_version VARCHAR(50),
    coverage_type VARCHAR(50), -- FULL, HITS_ONLY, UNKNOWN
    total_genes_deposited INTEGER,
    annotation_source VARCHAR(100), -- BIOGRID, DEPMAP, MANUAL, LLM_EXTRACTED
    annotation_confidence FLOAT CHECK (annotation_confidence >= 0.0 AND annotation_confidence <= 1.0),
    direction_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_screen_biogrid ON screen(biogrid_screen_id);
CREATE INDEX IF NOT EXISTS idx_screen_publication ON screen(publication_id);
CREATE INDEX IF NOT EXISTS idx_screen_organism ON screen(organism);

-- ============================================================================
-- SCREEN_CONDITION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen_condition (
    condition_id SERIAL PRIMARY KEY,
    screen_id INT NOT NULL REFERENCES screen(screen_id) ON DELETE CASCADE,
    condition_name VARCHAR(255) NOT NULL, -- e.g., "IFNγ+TNF", "Mock", "CTA"
    condition_type VARCHAR(50), -- TREATMENT, CONTROL, DRUG, COMBINATION
    treatment_agent VARCHAR(255),
    concentration VARCHAR(255),
    timepoint_hours INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(screen_id, condition_name)
);

CREATE INDEX IF NOT EXISTS idx_screen_condition_screen ON screen_condition(screen_id);

-- ============================================================================
-- SCREEN_COMPARISON TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen_comparison (
    comparison_id SERIAL PRIMARY KEY,
    screen_id INT NOT NULL REFERENCES screen(screen_id) ON DELETE CASCADE,
    condition_a_id INT NOT NULL REFERENCES screen_condition(condition_id) ON DELETE CASCADE,
    condition_b_id INT NOT NULL REFERENCES screen_condition(condition_id) ON DELETE CASCADE,
    comparison_label VARCHAR(255),
    selection_method VARCHAR(100), -- VIABILITY, FACS, DROPOUT, OTHER
    selection_direction VARCHAR(50), -- POSITIVE, NEGATIVE
    comparison_direction VARCHAR(50), -- A_MINUS_B, B_MINUS_A
    coverage_type VARCHAR(50), -- FULL, HITS_ONLY
    hit_threshold_type VARCHAR(50), -- FDR, SCORE, CUSTOM
    hit_threshold_value FLOAT,
    n_replicates INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(screen_id, condition_a_id, condition_b_id, comparison_direction),
    CHECK (condition_a_id != condition_b_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_comparison_screen ON screen_comparison(screen_id);
CREATE INDEX IF NOT EXISTS idx_screen_comparison_conditions ON screen_comparison(condition_a_id, condition_b_id);

-- ============================================================================
-- SCREEN_GENE_SCORE TABLE (Fact table - large volume)
-- ============================================================================

CREATE TABLE IF NOT EXISTS screen_gene_score (
    score_id SERIAL PRIMARY KEY,
    comparison_id INT NOT NULL REFERENCES screen_comparison(comparison_id) ON DELETE CASCADE,
    gene_id INT NOT NULL REFERENCES gene(gene_id) ON DELETE CASCADE,
    raw_score FLOAT,
    normalized_percentile FLOAT CHECK (normalized_percentile >= 0.0 AND normalized_percentile <= 1.0),
    rank INTEGER,
    fdr FLOAT,
    mean_lfc FLOAT,
    n_sgrnas_scored INTEGER,
    hit_flag BOOLEAN DEFAULT FALSE,
    direction_flag VARCHAR(50), -- POSITIVE, NEGATIVE, NEUTRAL
    adj_score FLOAT,
    data_state VARCHAR(50), -- FULL_SCORE, HIT_ONLY, NOT_IN_LIB
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(comparison_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_gene_score_comparison ON screen_gene_score(comparison_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_score_gene ON screen_gene_score(gene_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_score_hit ON screen_gene_score(hit_flag) WHERE hit_flag = TRUE;

-- ============================================================================
-- RESIDUAL_ANALYSIS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS residual_analysis (
    residual_id SERIAL PRIMARY KEY,
    screen_id INT NOT NULL REFERENCES screen(screen_id) ON DELETE CASCADE,
    comparison_a_id INT NOT NULL REFERENCES screen_comparison(comparison_id) ON DELETE CASCADE,
    comparison_b_id INT NOT NULL REFERENCES screen_comparison(comparison_id) ON DELETE CASCADE,
    analysis_label VARCHAR(255),
    spline_knots JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(screen_id, comparison_a_id, comparison_b_id)
);

CREATE INDEX IF NOT EXISTS idx_residual_analysis_screen ON residual_analysis(screen_id);

-- ============================================================================
-- RESIDUAL_GENE_SCORE TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS residual_gene_score (
    residual_score_id SERIAL PRIMARY KEY,
    residual_id INT NOT NULL REFERENCES residual_analysis(residual_id) ON DELETE CASCADE,
    gene_id INT NOT NULL REFERENCES gene(gene_id) ON DELETE CASCADE,
    score_a FLOAT,
    score_b FLOAT,
    residual_score FLOAT,
    sunbeam_zone VARCHAR(50), -- 8-zone classification
    rank INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(residual_id, gene_id)
);

CREATE INDEX IF NOT EXISTS idx_residual_gene_score_residual ON residual_gene_score(residual_id);
CREATE INDEX IF NOT EXISTS idx_residual_gene_score_sunbeam ON residual_gene_score(sunbeam_zone);

-- ============================================================================
-- METADATA_ANNOTATION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS metadata_annotation (
    annotation_id SERIAL PRIMARY KEY,
    screen_id INT NOT NULL REFERENCES screen(screen_id) ON DELETE CASCADE,
    annotated_by VARCHAR(100), -- LLM, HUMAN, HYBRID
    annotation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    llm_confidence JSONB, -- {field_name: confidence_score}
    review_status VARCHAR(50), -- PENDING, IN_REVIEW, APPROVED, REJECTED
    reviewed_at TIMESTAMP,
    changes_made JSONB,
    review_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metadata_annotation_screen ON metadata_annotation(screen_id);
CREATE INDEX IF NOT EXISTS idx_metadata_annotation_status ON metadata_annotation(review_status);

-- ============================================================================
-- SUMMARY STATISTICS TABLE (Denormalized for dashboard queries)
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_warehouse_summary (
    summary_id SERIAL PRIMARY KEY,
    organism VARCHAR(50) NOT NULL,
    total_publications INTEGER,
    total_screens INTEGER,
    total_genes INTEGER,
    total_libraries INTEGER,
    total_screen_genes INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(organism)
);

-- ============================================================================
-- AUDIT/LOGGING TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    description TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    execution_time_ms INTEGER
);

INSERT INTO schema_migrations (version, description, execution_time_ms)
VALUES ('0001', 'init_base_schema', 0)
ON CONFLICT DO NOTHING;
