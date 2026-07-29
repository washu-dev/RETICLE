/**
 * 0014 — Gene-Relatedness Scorecard schema (deliverable D1)
 *
 * Productionizes design/gene_relatedness_schema.sql into a numbered, idempotent
 * migration. Home: public schema of reticle_biogrid, versioned per
 * (data_load_version × relatedness_config).
 *
 * Adaptations vs the design draft:
 *   - Surrogate gene_id / screen_id FKs are NOT declared (matches the existing
 *     derived warehouse tables, which enforce only version_id/run_id). Lineage
 *     FKs (version_id, run_id, config_id) and the intra-subsystem gene_pair_id FK
 *     ARE kept.
 *   - dim_screen_context is DEFERRED to P3 (it overlaps screen_harmonization from
 *     migration 0012; the merge-vs-separate decision is made when contextual
 *     convergence / P3 is built). dim_gene_pair_context still lands here (empty
 *     until P3), keyed by a denormalized context_key.
 *
 * Idempotent. Apply before any compute/reader that touches these tables.
 */

-- ============================================================================
-- 0. Config & profile (first-class what-if objects — decisions #2/#3)
-- ============================================================================

CREATE TABLE IF NOT EXISTS relatedness_profile (
    profile_id            SERIAL PRIMARY KEY,
    data_load_version_id  INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,
    snapshot              JSONB NOT NULL,          -- screen counts, coverage dists, threshold->projected-pairs/cost curves
    profiler_version      VARCHAR(50),
    created_by            VARCHAR(100),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (data_load_version_id, organism, created_at)
);
CREATE INDEX IF NOT EXISTS idx_relatedness_profile_version
    ON relatedness_profile(data_load_version_id, organism);

CREATE TABLE IF NOT EXISTS relatedness_config (
    config_id             SERIAL PRIMARY KEY,
    data_load_version_id  INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    profile_id            INT REFERENCES relatedness_profile(profile_id) ON DELETE SET NULL,
    organism              VARCHAR(50) NOT NULL,
    label                 VARCHAR(200),
    thresholds            JSONB NOT NULL,          -- empirical, never hardcoded (decision #2)
    compute_budget        JSONB NOT NULL,          -- {cpu_hours, gpu_hours, max_pairs}
    projected_pairs       BIGINT,
    projected_cost_units  NUMERIC,
    status                VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft|accepted|building|built|superseded|failed
    created_by            VARCHAR(100),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (data_load_version_id, organism, label)
);
CREATE INDEX IF NOT EXISTS idx_relatedness_config_status
    ON relatedness_config(data_load_version_id, organism, status);

-- Channel-5 residual expectation-model provenance (light additive model, NOT a GP)
CREATE TABLE IF NOT EXISTS dim_gene_expectation_model (
    expectation_model_id  SERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id                INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,
    method                VARCHAR(40) NOT NULL,    -- additive | median_polish | mixed_effects (NEVER gaussian_process)
    covariates            VARCHAR(200),
    params                JSONB NOT NULL,          -- gene/screen baselines + context-group means
    n_observations        BIGINT,
    residual_var_explained NUMERIC,
    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (version_id, config_id, organism)
);
CREATE INDEX IF NOT EXISTS idx_gene_expectation_model_current
    ON dim_gene_expectation_model(version_id, config_id, is_current);

-- ============================================================================
-- 1. PubMed article cache (one row per PMID; article JSON lives in S3)
-- ============================================================================

CREATE TABLE IF NOT EXISTS dim_pubmed_article (
    pmid                  BIGINT PRIMARY KEY,
    publication_id        INT REFERENCES publication(publication_id),
    s3_uri                TEXT NOT NULL,
    s3_etag               VARCHAR(64),
    title                 TEXT,
    journal               VARCHAR(300),
    pub_year              INT,
    abstract              TEXT,
    doi                   VARCHAR(120),
    fetch_status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|fetched|failed|not_found
    fetch_error           TEXT,
    fetched_at            TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dim_pubmed_article_status ON dim_pubmed_article(fetch_status);
CREATE INDEX IF NOT EXISTS idx_dim_pubmed_article_pub    ON dim_pubmed_article(publication_id);

-- ============================================================================
-- 2. Scorecard header — fact_gene_pair (one row per cleared candidate pair)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fact_gene_pair (
    gene_pair_id          BIGSERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id                INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,
    gene_a_id             INT NOT NULL,        -- surrogate gene ids (no FK, matches prod convention)
    gene_b_id             INT NOT NULL,
    gene_a_symbol         VARCHAR(250),
    gene_b_symbol         VARCHAR(250),

    -- Channel 1: Co-essentiality (tail-restricted |Spearman ρ|) — PRIMARY
    coess_effect          NUMERIC,
    coess_rho             NUMERIC,
    coess_support         INT,
    coess_p_value         NUMERIC,
    coess_fdr             NUMERIC,
    coess_tier            VARCHAR(12),

    -- Channel 2: Co-hit enrichment (Jaccard / PMI / Fisher)
    cohit_effect_jaccard  NUMERIC,
    cohit_effect_pmi      NUMERIC,
    cohit_support         INT,
    cohit_a_hits          INT,
    cohit_b_hits          INT,
    cohit_screens_total   INT,
    cohit_fisher_p        NUMERIC,
    cohit_fdr             NUMERIC,
    cohit_tier            VARCHAR(12),

    -- Channel 3: Co-citation (PMI over shared publications)
    cocite_effect_pmi     NUMERIC,
    cocite_effect_jaccard NUMERIC,
    cocite_support        INT,
    cocite_a_pubs         INT,
    cocite_b_pubs         INT,
    cocite_p_value        NUMERIC,
    cocite_fdr            NUMERIC,
    cocite_tier           VARCHAR(12),

    -- Channel 4: Contextual convergence (roll-up of dim_gene_pair_context)
    context_effect        NUMERIC,
    context_support       INT,
    context_best_key      VARCHAR(200),
    context_best_fdr      NUMERIC,
    context_tier          VARCHAR(12),

    -- Channel 5: Novelty / mechanistic-divergence (additive; residual co-essentiality)
    resid_rho             NUMERIC,
    resid_effect          NUMERIC,
    resid_support         INT,
    resid_p_value         NUMERIC,
    resid_fdr             NUMERIC,
    resid_tier            VARCHAR(12),
    novelty_score         NUMERIC,
    is_antagonistic       BOOLEAN,
    is_buffering_candidate BOOLEAN,
    buffering_basis       TEXT,

    -- Overall roll-up
    relatedness_tier      VARCHAR(12) NOT NULL,   -- Strong | Moderate | Weak
    relatedness_score     NUMERIC,
    evidence_channels     VARCHAR(60),
    evidence_channel_count SMALLINT,
    total_support         INT,
    min_fdr               NUMERIC,

    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_gene_pair_order CHECK (gene_a_id < gene_b_id),
    CONSTRAINT uq_fact_gene_pair UNIQUE (version_id, config_id, gene_a_id, gene_b_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_current  ON fact_gene_pair(version_id, config_id, is_current);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_gene_a   ON fact_gene_pair(version_id, config_id, gene_a_id);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_gene_b   ON fact_gene_pair(version_id, config_id, gene_b_id);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_tier     ON fact_gene_pair(version_id, config_id, relatedness_tier);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_organism ON fact_gene_pair(version_id, config_id, organism);

-- ============================================================================
-- 3. Scorecard evidence dimensions
-- ============================================================================

CREATE TABLE IF NOT EXISTS dim_gene_pair_screen (
    gene_pair_screen_id   BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    screen_id             INT NOT NULL,
    both_measured         BOOLEAN NOT NULL,
    both_hit              BOOLEAN,
    gene_a_percentile     NUMERIC,
    gene_b_percentile     NUMERIC,
    gene_a_residual       NUMERIC,
    gene_b_residual       NUMERIC,
    gene_a_is_hit         BOOLEAN,
    gene_b_is_hit         BOOLEAN,
    in_tail               BOOLEAN,
    coverage_type         VARCHAR(20),
    context_key           VARCHAR(200),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gene_pair_id, screen_id)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_pair    ON dim_gene_pair_screen(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_screen  ON dim_gene_pair_screen(version_id, screen_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_context ON dim_gene_pair_screen(gene_pair_id, context_key);

CREATE TABLE IF NOT EXISTS dim_gene_pair_context (
    gene_pair_context_id  BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    context_type          VARCHAR(60) NOT NULL,   -- assay_domain|condition|cell_line|cell_type|phenotype
    context_value         VARCHAR(250) NOT NULL,
    context_key           VARCHAR(200),
    cohit_count           INT,
    screens_in_context    INT,
    jaccard               NUMERIC,
    pmi                   NUMERIC,
    coess_rho             NUMERIC,
    fisher_p              NUMERIC,
    fdr                   NUMERIC,
    tier                  VARCHAR(12),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gene_pair_id, context_type, context_value)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_context_pair  ON dim_gene_pair_context(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_context_value ON dim_gene_pair_context(version_id, config_id, context_type, context_value);

CREATE TABLE IF NOT EXISTS dim_gene_pair_publication (
    gene_pair_pub_id      BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    publication_id        INT REFERENCES publication(publication_id),
    pmid                  BIGINT REFERENCES dim_pubmed_article(pmid),
    screen_ids            INT[],
    both_cited            BOOLEAN,
    s3_uri                TEXT,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gene_pair_id, publication_id)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_pub_pair ON dim_gene_pair_publication(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_pub_pmid ON dim_gene_pair_publication(pmid);

-- ============================================================================
-- 4. Insight subsystem (LLM-generated, human-curatable; per gene AND per pair)
-- ============================================================================

CREATE TABLE IF NOT EXISTS dim_gene_insight (
    gene_insight_id       BIGSERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    run_id                INT REFERENCES etl_pipeline_run(run_id) ON DELETE SET NULL,
    gene_id               INT NOT NULL,
    organism              VARCHAR(50),
    sections              JSONB NOT NULL,     -- 3 epistemic sections; per-claim, dual-grounded
    citations             JSONB,
    internal_refs         JSONB,
    agency_level          VARCHAR(4),         -- L0|L1|L2
    model                 VARCHAR(60),
    prompt_version        VARCHAR(50),
    generated_at          TIMESTAMP,
    user_annotation       TEXT,
    annotated_by          VARCHAR(100),
    status                VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft|edited|approved|rejected
    version               INT NOT NULL DEFAULT 1,
    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (version_id, config_id, gene_id, version)
);
CREATE INDEX IF NOT EXISTS idx_gene_insight_gene   ON dim_gene_insight(version_id, gene_id, is_current);
CREATE INDEX IF NOT EXISTS idx_gene_insight_status ON dim_gene_insight(version_id, config_id, status);

CREATE TABLE IF NOT EXISTS dim_gene_pair_insight (
    gene_pair_insight_id  BIGSERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    run_id                INT REFERENCES etl_pipeline_run(run_id) ON DELETE SET NULL,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    organism              VARCHAR(50),
    sections              JSONB NOT NULL,
    citations             JSONB,
    internal_refs         JSONB,
    agency_level          VARCHAR(4),
    model                 VARCHAR(60),
    prompt_version        VARCHAR(50),
    generated_at          TIMESTAMP,
    user_annotation       TEXT,
    annotated_by          VARCHAR(100),
    status                VARCHAR(20) NOT NULL DEFAULT 'draft',
    version               INT NOT NULL DEFAULT 1,
    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gene_pair_id, version)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_insight_pair   ON dim_gene_pair_insight(gene_pair_id, is_current);
CREATE INDEX IF NOT EXISTS idx_gene_pair_insight_status ON dim_gene_pair_insight(version_id, config_id, status);

-- ============================================================================
-- 5. Convenience views (current-only; mirror the existing v_current_* pattern)
-- ============================================================================

CREATE OR REPLACE VIEW v_current_fact_gene_pair    AS SELECT * FROM fact_gene_pair       WHERE is_current = TRUE;
CREATE OR REPLACE VIEW v_current_gene_insight      AS SELECT * FROM dim_gene_insight     WHERE is_current = TRUE;
CREATE OR REPLACE VIEW v_current_gene_pair_insight AS SELECT * FROM dim_gene_pair_insight WHERE is_current = TRUE;

-- ============================================================================
-- 6. Read optimization for co-essentiality (P1 follow-up; 0012 added the columns)
-- ============================================================================

-- Co-essentiality reads gene×screen percentile vectors; this partial index makes
-- "measured genes in a version" scans cheap.
CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_percentile
    ON fact_screen_gene(version_id, gene_id) WHERE percentile_score IS NOT NULL;

-- Deferred to P3: dim_screen_context (reconcile with screen_harmonization from 0012).
-- Deferred to P2: populating fact_screen_gene_publication + its co-citation index.
