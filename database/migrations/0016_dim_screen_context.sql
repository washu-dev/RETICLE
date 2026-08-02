/**
 * 0016 — dim_screen_context (deliverable P3)
 *
 * Deferred from migration 0014 (see its header + tail comments): P3 materializes
 * one row per (version_id, screen_id) carrying the assay/condition/cell-line
 * facets that drive the contextual-convergence channel (D8) and the Channel-5
 * expectation model's context-group means (D5b). It DELIBERATELY reuses
 * screen_harmonization (migration 0012) for the fields P1 already computed
 * (coverage_type, score_basis, is_directional, selection_type) rather than
 * recomputing them from the metadata JSON a second time — this table only adds
 * what P1 does not already store: assay_domain, condition, cell_line, cell_type,
 * phenotype, and the denormalized context_key used to bucket pairs.
 *
 * Populated by scripts/populate_screen_context.py. Idempotent, no table rewrite
 * risk (new table). Apply before running D8 (contextual convergence) or D5b
 * (novelty channel).
 */

-- selection_type/coverage_type/is_directional/score_basis are denormalized from
-- screen_harmonization (P1) so a D8/D5b read never needs a second join; NOT
-- recomputed here. context_key is the deterministic bucket label for the
-- contextual channel, e.g. "stress|doxorubicin|hela" (lowercased
-- assay_domain|condition|cell_line, missing facets omitted) — denormalized for
-- cheap GROUP BY / joins. context_meta keeps raw/derived slots for provenance
-- (dosage, rule confidence, ...).
-- (No blank lines inside the column list below — some SQL clients treat a
-- blank line as a statement separator and would split this CREATE TABLE.)
CREATE TABLE IF NOT EXISTS dim_screen_context (
    dim_screen_context_id SERIAL PRIMARY KEY,
    version_id        INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id            INT REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    screen_id         INT NOT NULL,
    biogrid_screen_id VARCHAR(100),
    organism          VARCHAR(50) NOT NULL,
    assay_domain      VARCHAR(120),   -- fitness | stress | reporter | other (rule on PHENOTYPE)
    condition         VARCHAR(250),   -- CONDITION_NAME (+ CONDITION_DOSAGE)
    cell_line         VARCHAR(120),
    cell_type         VARCHAR(120),
    phenotype         VARCHAR(250),
    selection_type    VARCHAR(100),
    coverage_type     VARCHAR(20),
    is_directional    BOOLEAN,
    score_basis       TEXT,
    context_key       VARCHAR(200),
    context_meta      JSONB,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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

CREATE OR REPLACE VIEW v_current_screen_context AS
    SELECT * FROM dim_screen_context WHERE is_current = TRUE;
