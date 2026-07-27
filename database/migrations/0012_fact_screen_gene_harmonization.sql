/**
 * 0012 — Harmonization columns on fact_screen_gene + per-screen provenance
 *
 * P1 of the gene-relatedness design (backlog #9). Adds the per-(screen,gene)
 * harmonized outputs to fact_screen_gene, and a per-screen provenance table for
 * the harmonization decision (coverage, basis, direction, selection/perturbation).
 *
 * Source of truth for score TYPES and screen metadata is the BioGRID metadata
 * JSON (not the warehouse); the harmonizer joins DB score values (screen_gene_raw)
 * to the JSON metadata. See scripts/harmonize_warehouse.py.
 *
 * Adding nullable columns with no default is a fast catalog-only change in
 * PostgreSQL (no table rewrite), safe on the 26M-row fact_screen_gene.
 * Idempotent: safe to re-run.
 */

ALTER TABLE fact_screen_gene
    ADD COLUMN IF NOT EXISTS harmonized_score NUMERIC,   -- S_raw * perturbation, unified LOF axis (NULL if unmeasured)
    ADD COLUMN IF NOT EXISTS percentile_score NUMERIC,   -- within-screen rank in [-1,1]; -1=most essential, +1=most enriched
    ADD COLUMN IF NOT EXISTS robust_z_score   NUMERIC;   -- (value-median)/(MAD*1.4826); NULL if degenerate/unmeasured

COMMENT ON COLUMN fact_screen_gene.harmonized_score IS 'Harmonized effect on the unified loss-of-function axis (+=knockout protective/enriching, -=gene essential). NULL if the gene was not measured in the screen.';
COMMENT ON COLUMN fact_screen_gene.percentile_score IS 'Within-screen rank of harmonized_score over measured genes, in [-1,1]. -1=most essential, +1=most enriched. Cross-screen-comparable metric for co-essentiality.';
COMMENT ON COLUMN fact_screen_gene.robust_z_score IS 'Robust z of harmonized_score: (value-median)/(MAD*1.4826), std fallback. NULL if unmeasured/degenerate.';

-- Per-screen harmonization provenance (one row per version x screen).
CREATE TABLE IF NOT EXISTS screen_harmonization (
    screen_harmonization_id SERIAL PRIMARY KEY,
    version_id        INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id            INT REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id         INT NOT NULL,
    biogrid_screen_id VARCHAR(100),
    coverage_type     VARCHAR(20),   -- FULL | HIT_ONLY (routes continuous vs binary comparison)
    score_basis       TEXT,          -- provenance: which column/path produced S_raw (e.g. DIR_POS(log2fc))
    is_directional    BOOLEAN,       -- TRUE = sign from a directional metric; FALSE = from selection type
    selection_type    VARCHAR(100),  -- Negative Selection | Positive Selection | ...
    methodology       VARCHAR(100),
    library_type      VARCHAR(100),
    perturbation_mult SMALLINT,      -- +1 KO/CRISPRi, -1 CRISPRa (activation)
    genes_measured    INT,           -- # genes with non-null harmonized_score in this screen
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_id, screen_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_harmonization_version
    ON screen_harmonization(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_screen_harmonization_coverage
    ON screen_harmonization(version_id, coverage_type);
