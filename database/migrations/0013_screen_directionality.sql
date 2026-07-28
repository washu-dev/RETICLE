/**
 * 0013 — screen_directionality: versioned LLM directionality decisions
 *
 * Replaces the prototype's arbitrary JSON artifact
 * (processed_data/directionality_overrides_*.json). directionality_mapper.py
 * writes one row per (version_id, screen_id) with the LLM's sign decision for a
 * screen the deterministic harmonizer could not sign; harmonize_warehouse.py
 * reads status='auto' rows from here (flag --apply-directionality) instead of a
 * JSON file. Versioned, auditable, and co-located with the data it corrects.
 *
 * Idempotent.
 */

CREATE TABLE IF NOT EXISTS screen_directionality (
    screen_directionality_id SERIAL PRIMARY KEY,
    version_id        INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    screen_id         INT NOT NULL,            -- surrogate screen id (joins screen / screen_harmonization)
    biogrid_screen_id VARCHAR(100),
    mode              VARCHAR(20),             -- SINGLE | PAIR | UNDEFINED
    sign              SMALLINT,                -- +1 | -1 | NULL  (final sign on the LOF axis)
    positive_column   VARCHAR(20),             -- SCORE.N | NULL (PAIR mode)
    negative_column   VARCHAR(20),             -- SCORE.N | NULL (PAIR mode)
    confidence        NUMERIC,                 -- 0.0 - 1.0
    evidence          TEXT,                    -- verbatim phrase the LLM cited
    status            VARCHAR(20),             -- auto | needs_review | binary_only
    is_unresolved     BOOLEAN,                 -- true = no usable effect column (binary_only bucket)
    llm_model         VARCHAR(100),
    prompt_version    VARCHAR(50),
    raw_llm_output    TEXT,                    -- provenance: the model's raw JSON
    resolved_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(version_id, screen_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_directionality_version
    ON screen_directionality(version_id, status);

COMMENT ON TABLE screen_directionality IS 'Per-screen LLM directionality decisions (sign resolution for ambiguous screens). Only status=auto rows are applied by harmonize_warehouse --apply-directionality; needs_review rows await human adjudication.';
