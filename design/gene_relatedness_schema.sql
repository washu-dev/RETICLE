-- ============================================================================
-- RETICLE — CRISPR Gene-Relatedness Scorecard — DDL DRAFT
-- ============================================================================
--
-- STATUS: DESIGN DRAFT (design/). This is NOT a numbered migration.
--         Implementation (deliverable D1) will split this file into idempotent,
--         numbered migrations under database/migrations/ (e.g. 0012..00NN),
--         each guarded with IF NOT EXISTS / DO $$ ... duplicate_object blocks
--         and applied via `python database/run_migration.py <path>` BEFORE any
--         backend/compute code that reads the new columns is deployed.
--
-- HOME:   public schema of database `reticle_biogrid` (PostgreSQL / AWS RDS),
--         versioned exactly like the existing warehouse (version_id / run_id
--         lineage, SERIAL surrogate PKs, JSONB for flexible payloads).
--
-- CONVENTIONS (match 0006_versioned_data_warehouse.sql):
--   * SERIAL surrogate PK per table.
--   * version_id  -> data_load_version(version_id)   (data lineage; CASCADE)
--   * run_id      -> etl_pipeline_run(run_id)         (compute lineage; CASCADE)
--   * is_current BOOLEAN flag + v_current_* convenience views.
--   * FKs on surrogate screen_id / gene_id are declared here for design clarity.
--     PROD REALITY: the existing derived warehouse tables do NOT carry FKs on
--     screen_id / gene_id (only version_id / run_id are enforced). Implementation
--     MAY drop the screen_id/gene_id FKs to match prod load performance; they are
--     documented here to make the relationships explicit in the ERD. version_id
--     and run_id FKs are load-bearing and MUST be kept.
--
-- NEW OBJECTS (this subsystem):
--   Config / provenance : relatedness_config, relatedness_profile
--   Scorecard star      : fact_gene_pair (header)
--                         dim_gene_pair_screen, dim_gene_pair_context,
--                         dim_gene_pair_publication
--   Context / cache     : dim_screen_context, dim_pubmed_article
--   Novelty channel     : dim_gene_expectation_model (Channel-5 residual fit provenance)
--   Insight subsystem   : dim_gene_insight, dim_gene_pair_insight
--
-- PREREQUISITE EXTENSIONS to EXISTING tables (P1..P3) are at the bottom.
-- ============================================================================


-- ============================================================================
-- 0. CONFIGURATION & PROFILE (first-class what-if objects — locked decision #2/#3)
-- ============================================================================

-- relatedness_profile: cheap PROFILER snapshot of the data shape for a data load.
-- Holds screen counts, coverage distributions, and threshold -> projected-pair-
-- count / projected-cost CURVES. Co-hit / co-citation projections are EXACT
-- (sparse Hᵀ·H over hit / pub sets); co-essentiality volume is ESTIMATED from a
-- random sample of selective genes and carries a confidence band. Never computes
-- the n×n cartesian product.
CREATE TABLE IF NOT EXISTS relatedness_profile (
    profile_id            SERIAL PRIMARY KEY,
    data_load_version_id  INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,
    -- snapshot JSONB shape (documented, not enforced):
    --   { "screens": {"total": .., "full_coverage": .., "hit_only": ..},
    --     "coverage_distribution": {...},
    --     "selective_gene_count": .., "pan_essential_dropped": .., "pan_inert_dropped": ..,
    --     "projection_curves": [ {"threshold": {...}, "projected_pairs": .., "projected_cost_units": ..,
    --                             "estimation_method": "EXACT|SAMPLED", "ci_low": .., "ci_high": ..}, ... ],
    --     "sample": {"n_genes": .., "seed": ..} }
    snapshot              JSONB NOT NULL,
    profiler_version      VARCHAR(50),
    created_by            VARCHAR(100),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (data_load_version_id, organism, created_at)
);
CREATE INDEX IF NOT EXISTS idx_relatedness_profile_version
    ON relatedness_profile(data_load_version_id, organism);

-- relatedness_config: an ACCEPTED what-if threshold configuration. Multiple
-- configs per data load coexist and are A/B comparable (locked decision #3).
-- thresholds live in JSONB (locked decision #2 — empirical, never hardcoded).
CREATE TABLE IF NOT EXISTS relatedness_config (
    config_id             SERIAL PRIMARY KEY,
    data_load_version_id  INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    profile_id            INT REFERENCES relatedness_profile(profile_id) ON DELETE SET NULL,
    organism              VARCHAR(50) NOT NULL,
    label                 VARCHAR(200),          -- human A/B label, e.g. "budget-8h-strict"
    -- thresholds JSONB shape (documented, not enforced):
    --   { "min_shared_full_screens": .., "min_cohit_screens": .., "min_copub_count": ..,
    --     "tail_percentile": 0.10, "abs_rho_min": .., "jaccard_min": .., "pmi_min": ..,
    --     "fdr_alpha": 0.01, "selective_gene_filter": {...},
    --     "tier_cuts": {"co_essentiality": {...}, "overall": {...}},
    --     "compute_mode": "EXACT|ANN_TOPK", "ann_topk": .. }
    thresholds            JSONB NOT NULL,
    compute_budget        JSONB NOT NULL,        -- {"cpu_hours": .., "gpu_hours": .., "max_pairs": ..}
    projected_pairs       BIGINT,                -- what the profiler projected for THIS config
    projected_cost_units  NUMERIC,
    status                VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft, accepted, building, built, superseded, failed
    created_by            VARCHAR(100),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (data_load_version_id, organism, label)
);
CREATE INDEX IF NOT EXISTS idx_relatedness_config_status
    ON relatedness_config(data_load_version_id, organism, status);


-- ============================================================================
-- 1. SCREEN CONTEXT (P3 — captured during staging; feeds contextual convergence)
-- ============================================================================

-- dim_screen_context: one row per (version, screen). Assay domain / condition /
-- cell line etc. drive the "related under oxidative stress" contextual channel.
-- coverage_type (FULL | HIT_ONLY) routes a screen to the continuous (co-ess) vs
-- binary (co-hit) engine. Ported from harmonize_scores.py per-screen output.
CREATE TABLE IF NOT EXISTS dim_screen_context (
    dim_screen_context_id SERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id                INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id             INT NOT NULL REFERENCES screen(screen_id),
    biogrid_screen_id     VARCHAR(100),
    organism              VARCHAR(50) NOT NULL,

    assay_domain          VARCHAR(120),   -- e.g. oxidative_stress, viral_infection, drug_resistance
    condition             VARCHAR(250),   -- treatment / perturbagen / pressure
    cell_line             VARCHAR(120),
    cell_type             VARCHAR(120),
    phenotype             VARCHAR(250),
    selection_type        VARCHAR(60),    -- Negative / Positive / Positive and Negative / Phenotype
    coverage_type         VARCHAR(20),    -- FULL | HIT_ONLY
    is_directional        BOOLEAN,        -- sign came from a directional metric (vs selection type)
    score_basis           VARCHAR(200),   -- provenance of S_raw (SCORE_BASIS from harmonization)
    -- context_key is the deterministic hash/label used to bucket pairs into a context
    -- (e.g. md5(assay_domain||'|'||condition||'|'||cell_line)); denormalized for joins.
    context_key           VARCHAR(200),
    context_meta          JSONB,          -- raw extracted / normalized methods slots

    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (version_id, screen_id)
);
CREATE INDEX IF NOT EXISTS idx_dim_screen_context_version
    ON dim_screen_context(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_screen_context_domain
    ON dim_screen_context(version_id, assay_domain);
CREATE INDEX IF NOT EXISTS idx_dim_screen_context_coverage
    ON dim_screen_context(version_id, coverage_type);
CREATE INDEX IF NOT EXISTS idx_dim_screen_context_key
    ON dim_screen_context(version_id, context_key);


-- dim_gene_expectation_model: provenance for the LIGHT additive expectation model
-- (Channel 5 residualization — NOT a Gaussian process). One row per
-- (version_id, config_id): the fitted gene baselines, screen baselines, and
-- context-group means used to compute E[g,i] = expected harmonized percentile.
-- Stored so a residual result is reproducible and auditable (NFR-1 / NFR-7).
CREATE TABLE IF NOT EXISTS dim_gene_expectation_model (
    expectation_model_id  SERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id                INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,

    method                VARCHAR(40) NOT NULL,   -- additive | median_polish | mixed_effects (NEVER gaussian_process)
    covariates            VARCHAR(200),           -- e.g. "gene_baseline,screen_baseline,modality,library,cell_line,assay_domain"
    -- params JSONB shape (documented, not enforced):
    --   { "grand_mean": .., "gene_baseline": {gene_id: ..}, "screen_baseline": {screen_id: ..},
    --     "context_group_means": {"modality": {..}, "library": {..}, "cell_line": {..}, "assay_domain": {..}},
    --     "iterations": .., "converged": true, "residual_var_explained": .. }
    params                JSONB NOT NULL,
    n_observations        BIGINT,                 -- gene×screen cells fitted
    residual_var_explained NUMERIC,               -- fraction of variance removed by the model
    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (version_id, config_id, organism)
);
CREATE INDEX IF NOT EXISTS idx_gene_expectation_model_current
    ON dim_gene_expectation_model(version_id, config_id, is_current);


-- ============================================================================
-- 2. PUBMED ARTICLE CACHE (P2 / insight subsystem — one row per PMID, shared)
-- ============================================================================

-- dim_pubmed_article: PMID-level cache. Article JSON is fetched ONCE from NCBI
-- efetch / PMC, stored in S3 (s3://<bucket>/pubmed/<pmid>.json), and recorded
-- here. Not versioned (shared like `publication`). s3_uri is the source of truth
-- for the full record; this row holds only lightweight facets + provenance.
CREATE TABLE IF NOT EXISTS dim_pubmed_article (
    pmid                  BIGINT PRIMARY KEY,          -- PubMed ID is the natural key
    publication_id        INT REFERENCES publication(publication_id),  -- link to warehouse pub if known
    s3_uri                TEXT NOT NULL,               -- s3://<bucket>/pubmed/<pmid>.json
    s3_etag               VARCHAR(64),                 -- integrity / change detection
    title                 TEXT,
    journal               VARCHAR(300),
    pub_year              INT,
    abstract              TEXT,
    doi                   VARCHAR(120),
    fetch_status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, fetched, failed, not_found
    fetch_error           TEXT,
    fetched_at            TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dim_pubmed_article_status
    ON dim_pubmed_article(fetch_status);
CREATE INDEX IF NOT EXISTS idx_dim_pubmed_article_pub
    ON dim_pubmed_article(publication_id);


-- ============================================================================
-- 3. SCORECARD HEADER — fact_gene_pair (per version × config × ordered pair)
-- ============================================================================

-- One row per candidate pair that CLEARED minimum support (sub-threshold pairs
-- are NOT stored — logged as dropped in the run audit). Keyed per
-- (version_id, config_id, gene_a_id, gene_b_id) with gene_a_id < gene_b_id
-- enforced by CHECK so each unordered pair is stored exactly once. Never crosses
-- organism (guardrail — both genes share `organism`).
--
-- The four metric channels are stored as parallel attribute-groups, each with the
-- three orthogonal dimensions: effect size, support, significance (p + BH-FDR),
-- plus a per-channel tier. An overall roll-up tier + evidence_channels summarize.
CREATE TABLE IF NOT EXISTS fact_gene_pair (
    gene_pair_id          BIGSERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id                INT NOT NULL REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    organism              VARCHAR(50) NOT NULL,
    gene_a_id             INT NOT NULL REFERENCES gene(gene_id),
    gene_b_id             INT NOT NULL REFERENCES gene(gene_id),
    gene_a_symbol         VARCHAR(250),   -- denormalized for read-side convenience
    gene_b_symbol         VARCHAR(250),

    -- ---- Channel 1: Co-essentiality (tail-restricted |Spearman ρ|) — PRIMARY ---
    coess_effect          NUMERIC,        -- |ρ| tail-restricted, in [0,1]
    coess_rho             NUMERIC,        -- signed ρ (sign retained for anti-correlation)
    coess_support         INT,            -- # shared FULL-coverage screens used
    coess_p_value         NUMERIC,
    coess_fdr             NUMERIC,        -- Benjamini-Hochberg across the pair space
    coess_tier            VARCHAR(12),    -- Strong | Moderate | Weak | NULL

    -- ---- Channel 2: Co-hit enrichment (Jaccard / PMI / Fisher) — HIT_ONLY -------
    cohit_effect_jaccard  NUMERIC,
    cohit_effect_pmi      NUMERIC,
    cohit_support         INT,            -- # screens where both are hits
    cohit_a_hits          INT,            -- marginal support (for PMI / Fisher)
    cohit_b_hits          INT,
    cohit_screens_total   INT,            -- N screens both were measured/eligible
    cohit_fisher_p        NUMERIC,
    cohit_fdr             NUMERIC,
    cohit_tier            VARCHAR(12),

    -- ---- Channel 3: Co-citation (co-occurrence in publications; PMI) ------------
    cocite_effect_pmi     NUMERIC,
    cocite_effect_jaccard NUMERIC,
    cocite_support        INT,            -- # shared publications
    cocite_a_pubs         INT,
    cocite_b_pubs         INT,
    cocite_p_value        NUMERIC,
    cocite_fdr            NUMERIC,
    cocite_tier           VARCHAR(12),

    -- ---- Channel 4: Contextual convergence (roll-up of dim_gene_pair_context) ---
    context_effect        NUMERIC,        -- strongest / aggregated context effect
    context_support       INT,            -- # contexts clearing support
    context_best_key      VARCHAR(200),   -- e.g. oxidative_stress context_key
    context_best_fdr      NUMERIC,
    context_tier          VARCHAR(12),

    -- ---- Channel 5: Novelty / mechanistic-divergence (ADDITIVE) -----------------
    -- "find genes that break the same rule." Reuses Channel-1's percentile matrix
    -- and P3 context metadata (dim_screen_context) via a LIGHT additive expectation
    -- model (NOT a Gaussian process). See dim_gene_expectation_model for the fit.
    resid_rho             NUMERIC,        -- signed tail-restricted Spearman ρ of RESIDUAL profiles
    resid_effect          NUMERIC,        -- |resid_rho| (effect size)
    resid_support         INT,            -- # shared FULL screens used for residual correlation
    resid_p_value         NUMERIC,
    resid_fdr             NUMERIC,        -- BH-FDR across the pair space
    resid_tier            VARCHAR(12),    -- Strong | Moderate | Weak | NULL
    novelty_score         NUMERIC,        -- contrast resid_rho vs coess_rho (high resid + low raw = novel)
    is_antagonistic       BOOLEAN,        -- strongly NEGATIVE raw/residual ρ (anti-β flag)
    is_buffering_candidate BOOLEAN,       -- HYPOTHESIS flag, NOT a measured edge (see buffering_basis)
    buffering_basis       TEXT,           -- why flagged: near-inert + paralog/homolog + complementary; "testable by combinatorial KO"

    -- ---- Overall roll-up --------------------------------------------------------
    relatedness_tier      VARCHAR(12) NOT NULL,   -- Strong | Moderate | Weak
    relatedness_score     NUMERIC,                -- optional unified 0..1 roll-up
    evidence_channels     VARCHAR(60),            -- e.g. "coess,cohit,cocite" contributing channels
    evidence_channel_count SMALLINT,
    total_support         INT,                    -- shared screens + hits + pubs (breadth of evidence)
    min_fdr               NUMERIC,                -- best (smallest) FDR across channels

    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- unordered-pair uniqueness + canonical ordering + organism guardrail
    CONSTRAINT chk_gene_pair_order CHECK (gene_a_id < gene_b_id),
    CONSTRAINT uq_fact_gene_pair UNIQUE (version_id, config_id, gene_a_id, gene_b_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_current
    ON fact_gene_pair(version_id, config_id, is_current);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_gene_a
    ON fact_gene_pair(version_id, config_id, gene_a_id);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_gene_b
    ON fact_gene_pair(version_id, config_id, gene_b_id);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_tier
    ON fact_gene_pair(version_id, config_id, relatedness_tier);
CREATE INDEX IF NOT EXISTS idx_fact_gene_pair_organism
    ON fact_gene_pair(version_id, config_id, organism);


-- ============================================================================
-- 4. SCORECARD EVIDENCE DIMENSIONS
-- ============================================================================

-- dim_gene_pair_screen: the per-pair × per-screen evidence rows that back the
-- co-essentiality and co-hit channels (auditability / provenance — a claim like
-- "co-essential across 48 oxidative-stress screens" resolves through here).
CREATE TABLE IF NOT EXISTS dim_gene_pair_screen (
    gene_pair_screen_id   BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    screen_id             INT NOT NULL REFERENCES screen(screen_id),

    both_measured         BOOLEAN NOT NULL,   -- both genes have a harmonized percentile here
    both_hit              BOOLEAN,            -- both genes are hits in this screen
    gene_a_percentile     NUMERIC,            -- harmonized PERCENTILE_SCORE [-1,1] for gene A
    gene_b_percentile     NUMERIC,            -- harmonized PERCENTILE_SCORE [-1,1] for gene B
    gene_a_residual       NUMERIC,            -- Channel 5: observed - expected (E from dim_gene_expectation_model)
    gene_b_residual       NUMERIC,            -- Channel 5: observed - expected
    gene_a_is_hit         BOOLEAN,
    gene_b_is_hit         BOOLEAN,
    in_tail               BOOLEAN,            -- observation fell in the correlation tail window
    coverage_type         VARCHAR(20),        -- FULL | HIT_ONLY (denormalized)
    context_key           VARCHAR(200),       -- denormalized from dim_screen_context

    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (gene_pair_id, screen_id)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_pair
    ON dim_gene_pair_screen(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_screen
    ON dim_gene_pair_screen(version_id, screen_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_screen_context
    ON dim_gene_pair_screen(gene_pair_id, context_key);


-- dim_gene_pair_context: per pair × context stratification (Channel 4). One row
-- per (pair, context_type, context_value) that cleared support — lets an edge say
-- "related under oxidative stress" with its own effect / significance / tier.
CREATE TABLE IF NOT EXISTS dim_gene_pair_context (
    gene_pair_context_id  BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,

    context_type          VARCHAR(60) NOT NULL,   -- assay_domain | condition | cell_line | cell_type | phenotype
    context_value         VARCHAR(250) NOT NULL,  -- e.g. oxidative_stress
    context_key           VARCHAR(200),

    cohit_count           INT,            -- # screens in this context where both are hits
    screens_in_context    INT,            -- N eligible screens in this context
    jaccard               NUMERIC,
    pmi                   NUMERIC,
    coess_rho             NUMERIC,        -- within-context co-essentiality where FULL coverage exists
    fisher_p              NUMERIC,
    fdr                   NUMERIC,
    tier                  VARCHAR(12),

    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (gene_pair_id, context_type, context_value)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_context_pair
    ON dim_gene_pair_context(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_context_value
    ON dim_gene_pair_context(version_id, config_id, context_type, context_value);


-- dim_gene_pair_publication: per pair × PMID co-citation evidence (Channel 3).
-- Links the pair to the shared publication, the screens that cited it, and the
-- S3 object holding the fetched article (dual-grounding / citation contract).
CREATE TABLE IF NOT EXISTS dim_gene_pair_publication (
    gene_pair_pub_id      BIGSERIAL PRIMARY KEY,
    gene_pair_id          BIGINT NOT NULL REFERENCES fact_gene_pair(gene_pair_id) ON DELETE CASCADE,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT NOT NULL REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    publication_id        INT REFERENCES publication(publication_id),
    pmid                  BIGINT REFERENCES dim_pubmed_article(pmid),

    screen_ids            INT[],          -- screens through which this pub links the pair
    both_cited            BOOLEAN,        -- both genes appear in this publication's screen set
    s3_uri                TEXT,           -- denormalized from dim_pubmed_article for convenience

    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (gene_pair_id, publication_id)
);
CREATE INDEX IF NOT EXISTS idx_gene_pair_pub_pair
    ON dim_gene_pair_publication(gene_pair_id);
CREATE INDEX IF NOT EXISTS idx_gene_pair_pub_pmid
    ON dim_gene_pair_publication(pmid);


-- ============================================================================
-- 5. INSIGHT SUBSYSTEM (LLM-generated, human-curatable, per gene AND per pair)
-- ============================================================================

-- Both insight tables carry the SAME structure: three epistemic sections stored
-- as structured JSON so each claim can be individually edited / accepted /
-- rejected, and every claim satisfies the dual-grounding citation contract
-- (>= 1 external PMID AND/OR an internal evidence ref). Unsupported claims are
-- dropped/flagged upstream and never persisted as 'approved'.
--
-- sections JSONB shape (documented, not enforced):
--   { "established_knowledge":  [ {claim, pmids:[..], internal_refs:[{type,ref_id,detail}], confidence, status}, ... ],
--     "recognized_gaps":        [ ... same claim shape ... ],
--     "open_uncertainty":       [ ... same claim shape ... ] }
-- internal_refs point at fact_gene_pair / dim_gene_pair_screen / dim_gene_pair_context rows.

-- dim_gene_insight: per gene (per version × config so insights are comparable A/B).
CREATE TABLE IF NOT EXISTS dim_gene_insight (
    gene_insight_id       BIGSERIAL PRIMARY KEY,
    version_id            INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    config_id             INT REFERENCES relatedness_config(config_id) ON DELETE CASCADE,
    run_id                INT REFERENCES etl_pipeline_run(run_id) ON DELETE SET NULL,
    gene_id               INT NOT NULL REFERENCES gene(gene_id),
    organism              VARCHAR(50),

    sections              JSONB NOT NULL,     -- 3-section structured claims (see above)
    citations             JSONB,              -- flattened list of external PMIDs cited
    internal_refs         JSONB,              -- flattened list of internal evidence refs
    agency_level          VARCHAR(4),         -- L0 | L1 | L2 (agent mode used)
    model                 VARCHAR(60),        -- claude-opus | claude-sonnet | claude-haiku | claude-fable
    prompt_version        VARCHAR(50),
    generated_at          TIMESTAMP,

    -- human curation
    user_annotation       TEXT,
    annotated_by          VARCHAR(100),
    status                VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft | edited | approved | rejected
    version               INT NOT NULL DEFAULT 1,   -- insight revision (bumped on human edit / regen)
    is_current            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (version_id, config_id, gene_id, version)
);
CREATE INDEX IF NOT EXISTS idx_gene_insight_gene
    ON dim_gene_insight(version_id, gene_id, is_current);
CREATE INDEX IF NOT EXISTS idx_gene_insight_status
    ON dim_gene_insight(version_id, config_id, status);

-- dim_gene_pair_insight: per gene-pair, same structure as dim_gene_insight.
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
CREATE INDEX IF NOT EXISTS idx_gene_pair_insight_pair
    ON dim_gene_pair_insight(gene_pair_id, is_current);
CREATE INDEX IF NOT EXISTS idx_gene_pair_insight_status
    ON dim_gene_pair_insight(version_id, config_id, status);


-- ============================================================================
-- 6. CONVENIENCE VIEWS (current-only, mirror existing v_current_* pattern)
-- ============================================================================

CREATE OR REPLACE VIEW v_current_fact_gene_pair AS
    SELECT * FROM fact_gene_pair WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_current_gene_insight AS
    SELECT * FROM dim_gene_insight WHERE is_current = TRUE;

CREATE OR REPLACE VIEW v_current_gene_pair_insight AS
    SELECT * FROM dim_gene_pair_insight WHERE is_current = TRUE;


-- ============================================================================
-- 7. PREREQUISITE EXTENSIONS TO EXISTING WAREHOUSE TABLES
--     (implemented as their own numbered migrations BEFORE this subsystem)
-- ============================================================================

-- P1 [backlog #9-#12]: port harmonize_scores.py per-(screen,gene) outputs into
-- fact_screen_gene as harmonization columns. Co-essentiality reads these.
ALTER TABLE fact_screen_gene ADD COLUMN IF NOT EXISTS harmonized_score  NUMERIC;   -- unified biological axis
ALTER TABLE fact_screen_gene ADD COLUMN IF NOT EXISTS percentile_score  NUMERIC;   -- [-1,1] within-screen rank
ALTER TABLE fact_screen_gene ADD COLUMN IF NOT EXISTS robust_z_score    NUMERIC;
ALTER TABLE fact_screen_gene ADD COLUMN IF NOT EXISTS is_hit            BOOLEAN;
CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_percentile
    ON fact_screen_gene(version_id, gene_id) WHERE percentile_score IS NOT NULL;

-- P2: populate fact_screen_gene_publication (currently a 0-row stub) with
-- screen -> PMID -> gene links. No schema change required (table exists in 0006);
-- prerequisite is a POPULATION job, plus this backfill index for the co-citation
-- and PubMed-prefetch reads.
CREATE INDEX IF NOT EXISTS idx_fsgp_gene_pub
    ON fact_screen_gene_publication(version_id, gene_id, publication_id);

-- P3: screen-context metadata + cited PMIDs are materialized into
-- dim_screen_context (section 1) and dim_pubmed_article (section 2) during
-- staging — no change to `screen` itself required.

-- ============================================================================
-- END DDL DRAFT
-- ============================================================================
