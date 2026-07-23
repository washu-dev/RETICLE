/**
 * RETICLE ETL PIPELINE Functions (0002)
 *
 * Migrated from: database/etl_pipeline.sql
 *
 * Creates orchestration and step functions for the ETL pipeline:
 * - run_etl_pipeline: Main orchestration function
 * - validate_staging_data, load_screens, load_genes: Data loading steps
 * - build_screen_gene_raw, build_fact_screen_gene: Fact building
 * - build_dim_screen, build_dim_gene: Dimension building
 * - build_fact_screen_gene_publication: Publication linking
 *
 * USAGE:
 *   SELECT run_etl_pipeline(p_version_id := <id>, p_pipeline_version := '1.0.0');
 *
 * All functions use CREATE OR REPLACE for idempotency.
 */

-- ============================================================================
-- PIPELINE ORCHESTRATION FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION run_etl_pipeline(
    p_version_id INT,
    p_pipeline_version VARCHAR DEFAULT '1.0'
)
RETURNS TABLE(
    run_id INT,
    status VARCHAR,
    duration_seconds NUMERIC,
    message TEXT
) AS $$
DECLARE
    v_run_id INT;
    v_start_time TIMESTAMP;
    v_rows_processed INT;
    v_error_msg TEXT;
BEGIN
    v_start_time := CURRENT_TIMESTAMP;

    -- Validate version exists and is ready
    IF NOT EXISTS (SELECT 1 FROM data_load_version WHERE version_id = p_version_id) THEN
        RAISE EXCEPTION 'Version % not found', p_version_id;
    END IF;

    -- Create run record
    INSERT INTO etl_pipeline_run (
        data_load_version_id,
        pipeline_version,
        started_at,
        status
    ) VALUES (
        p_version_id,
        p_pipeline_version,
        CURRENT_TIMESTAMP,
        'running'
    )
    RETURNING etl_pipeline_run.run_id INTO v_run_id;

    BEGIN
        -- Step 1: Validate staging data
        PERFORM validate_staging_data(v_run_id, p_version_id);

        -- Step 2: Upsert screens
        PERFORM load_screens(v_run_id, p_version_id);

        -- Step 3: Upsert genes
        PERFORM load_genes(v_run_id, p_version_id);

        -- Step 4: Build denormalized screen-gene
        PERFORM build_screen_gene_raw(v_run_id, p_version_id);

        -- Step 5: Build fact table
        PERFORM build_fact_screen_gene(v_run_id, p_version_id);

        -- Step 6: Build dimensions
        PERFORM build_dim_screen(v_run_id, p_version_id);
        PERFORM build_dim_gene(v_run_id, p_version_id);

        -- Step 7: Build publication relationships
        PERFORM build_fact_screen_gene_publication(v_run_id, p_version_id);

        -- Mark this run as current
        UPDATE etl_pipeline_run
        SET
            is_current = TRUE,
            status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            total_duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - v_start_time))
        WHERE etl_pipeline_run.run_id = v_run_id;

        -- Mark previous versions as historical
        UPDATE data_load_version
        SET is_current = FALSE
        WHERE version_id != p_version_id
        AND organism = (SELECT organism FROM data_load_version WHERE version_id = p_version_id)
        AND is_current = TRUE;

        UPDATE etl_pipeline_run
        SET is_current = FALSE
        WHERE data_load_version_id = (
            SELECT version_id FROM data_load_version
            WHERE version_id != p_version_id
            AND organism = (SELECT organism FROM data_load_version WHERE version_id = p_version_id)
        );

        RETURN QUERY
        SELECT
            v_run_id,
            'completed'::VARCHAR,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - v_start_time))::NUMERIC,
            'ETL pipeline completed successfully'::TEXT;

    EXCEPTION WHEN OTHERS THEN
        v_error_msg := SQLERRM;

        UPDATE etl_pipeline_run
        SET
            status = 'failed',
            completed_at = CURRENT_TIMESTAMP,
            error_message = v_error_msg,
            total_duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - v_start_time))
        WHERE etl_pipeline_run.run_id = v_run_id;

        RETURN QUERY
        SELECT
            v_run_id,
            'failed'::VARCHAR,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - v_start_time))::NUMERIC,
            v_error_msg::TEXT;

    END;

END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ETL STEP FUNCTIONS
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_staging_data(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_invalid_screens INT;
    v_invalid_genes INT;
    v_duplicate_genes INT;
BEGIN
    -- Check for missing biogrid_screen_id
    UPDATE staging_screen
    SET validation_errors = 'Missing biogrid_screen_id'
    WHERE version_id = p_version_id
    AND (biogrid_screen_id IS NULL OR biogrid_screen_id = '');

    SELECT COUNT(*) INTO v_invalid_screens
    FROM staging_screen
    WHERE version_id = p_version_id
    AND validation_errors IS NOT NULL;

    -- Check for missing identifier_id
    UPDATE staging_screen_gene
    SET validation_errors = 'Missing identifier_id'
    WHERE version_id = p_version_id
    AND identifier_id IS NULL;

    -- Mark duplicate gene entries (keep only first occurrence per identifier_id)
    UPDATE staging_screen_gene
    SET validation_errors = 'Duplicate identifier (duplicate marked for skip)'
    WHERE version_id = p_version_id
    AND validation_errors IS NULL
    AND identifier_id IN (
        SELECT identifier_id
        FROM staging_screen_gene s1
        WHERE s1.version_id = p_version_id
        AND s1.validation_errors IS NULL
        AND ctid > (
            SELECT MIN(ctid)
            FROM staging_screen_gene s2
            WHERE s2.version_id = p_version_id
            AND s2.identifier_id = s1.identifier_id
            AND s2.validation_errors IS NULL
        )
    );

    SELECT COUNT(*) INTO v_duplicate_genes
    FROM staging_screen_gene
    WHERE version_id = p_version_id
    AND validation_errors = 'Duplicate identifier (duplicate marked for skip)';

    SELECT COUNT(*) INTO v_invalid_genes
    FROM staging_screen_gene
    WHERE version_id = p_version_id
    AND validation_errors IS NOT NULL;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status,
        rows_processed, rows_skipped
    ) VALUES (
        p_run_id, 'validate_staging_data', 1, 'completed',
        (SELECT COUNT(*) FROM staging_screen WHERE version_id = p_version_id),
        v_invalid_screens
    );

    IF v_invalid_screens > 0 OR v_invalid_genes > 0 THEN
        RAISE NOTICE 'Validation found % invalid screens, % invalid genes (% duplicates)',
            v_invalid_screens, v_invalid_genes, v_duplicate_genes;
    END IF;

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION load_screens(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
    v_updated INT;
BEGIN
    -- Upsert screens (deduplicate by UNIQUE constraint: version_id, biogrid_screen_id)
    WITH deduped AS (
        SELECT DISTINCT ON (biogrid_screen_id)
            p_version_id as version_id,
            biogrid_screen_id,
            organism,
            annotation_source,
            TRUE as is_current
        FROM staging_screen
        WHERE version_id = p_version_id
        AND validation_errors IS NULL
        ORDER BY biogrid_screen_id, organism, annotation_source
    ),
    upsert_data AS (
        INSERT INTO screen (
            version_id, biogrid_screen_id, organism, annotation_source, is_current
        )
        SELECT version_id, biogrid_screen_id, organism, annotation_source, is_current
        FROM deduped
        ON CONFLICT (version_id, biogrid_screen_id) DO UPDATE SET
            is_current = TRUE,
            updated_at = CURRENT_TIMESTAMP
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM upsert_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'load_screens', 2, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION load_genes(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
BEGIN
    -- Upsert genes (deduplicate by UNIQUE constraint: version_id, identifier_id)
    WITH deduped AS (
        SELECT DISTINCT ON (ssg.identifier_id)
            p_version_id as version_id,
            ssg.identifier_id,
            ssg.gene_symbol,
            (SELECT organism FROM data_load_version WHERE version_id = p_version_id) as organism,
            TRUE as is_current
        FROM staging_screen_gene ssg
        WHERE ssg.version_id = p_version_id
        AND ssg.validation_errors IS NULL
        ORDER BY ssg.identifier_id, ssg.gene_symbol
    ),
    upsert_data AS (
        INSERT INTO gene (
            version_id, identifier_id, gene_symbol, organism, is_current
        )
        SELECT version_id, identifier_id, gene_symbol, organism, is_current
        FROM deduped
        ON CONFLICT (version_id, identifier_id) DO UPDATE SET
            is_current = TRUE,
            updated_at = CURRENT_TIMESTAMP
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM upsert_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'load_genes', 3, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION build_screen_gene_raw(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
BEGIN
    -- Create denormalized screen-gene pairs
    WITH raw_data AS (
        INSERT INTO screen_gene_raw (
            version_id, run_id, screen_id, gene_id,
            biogrid_screen_id, identifier_id,
            hit_flag, score_1, score_2, score_3, score_4, score_5,
            raw_score, is_current
        )
        SELECT
            p_version_id,
            p_run_id,
            s.screen_id,
            g.gene_id,
            st.biogrid_screen_id,
            st.identifier_id,
            st.hit_flag,
            st.score_1, st.score_2, st.score_3, st.score_4, st.score_5,
            COALESCE(st.score_1, 0),
            TRUE
        FROM staging_screen_gene st
        JOIN screen s ON (
            s.version_id = p_version_id
            AND s.biogrid_screen_id = st.biogrid_screen_id
        )
        JOIN gene g ON (
            g.version_id = p_version_id
            AND g.identifier_id = st.identifier_id
        )
        WHERE st.version_id = p_version_id
        AND st.validation_errors IS NULL
        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
            is_current = TRUE,
            hit_flag = EXCLUDED.hit_flag
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM raw_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_screen_gene_raw', 4, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION build_fact_screen_gene(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
BEGIN
    -- Build fact table with aggregations
    WITH fact_data AS (
        INSERT INTO fact_screen_gene (
            version_id, run_id, screen_id, gene_id,
            hit_count, hit_percentage, avg_raw_score,
            total_publications, condition_count,
            is_current
        )
        SELECT
            p_version_id,
            p_run_id,
            sgr.screen_id,
            sgr.gene_id,
            COUNT(CASE WHEN sgr.hit_flag = TRUE THEN 1 END)::INT,
            ROUND(
                100.0 * COUNT(CASE WHEN sgr.hit_flag = TRUE THEN 1 END) /
                NULLIF(COUNT(*), 0),
                2
            )::NUMERIC,
            AVG(sgr.raw_score)::NUMERIC,
            0,
            1,
            TRUE
        FROM screen_gene_raw sgr
        WHERE sgr.version_id = p_version_id
        GROUP BY sgr.screen_id, sgr.gene_id
        ON CONFLICT (version_id, screen_id, gene_id) DO UPDATE SET
            is_current = TRUE
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM fact_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_fact_screen_gene', 5, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION build_dim_screen(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
BEGIN
    -- Build screen dimension
    WITH dim_data AS (
        INSERT INTO dim_screen (
            version_id, run_id, screen_id,
            biogrid_screen_id, organism, annotation_source,
            total_genes, total_genes_hit, total_publications,
            avg_hit_percentage,
            is_current
        )
        SELECT
            p_version_id,
            p_run_id,
            s.screen_id,
            s.biogrid_screen_id,
            s.organism,
            s.annotation_source,
            COUNT(DISTINCT sgr.gene_id)::INT,
            COUNT(DISTINCT CASE WHEN sgr.hit_flag = TRUE THEN sgr.gene_id END)::INT,
            0,
            AVG(CASE WHEN sgr.hit_flag = TRUE THEN 100.0 ELSE 0 END)::NUMERIC,
            TRUE
        FROM screen s
        LEFT JOIN screen_gene_raw sgr ON (
            s.screen_id = sgr.screen_id
            AND s.version_id = sgr.version_id
        )
        WHERE s.version_id = p_version_id
        GROUP BY s.screen_id
        ON CONFLICT (version_id, screen_id) DO UPDATE SET
            is_current = TRUE
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM dim_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_dim_screen', 6, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION build_dim_gene(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
DECLARE
    v_inserted INT;
BEGIN
    -- Build gene dimension
    WITH dim_data AS (
        INSERT INTO dim_gene (
            version_id, run_id, gene_id,
            identifier_id, gene_symbol, organism,
            total_screens, total_screens_hit, total_publications,
            avg_hit_percentage,
            is_current
        )
        SELECT
            p_version_id,
            p_run_id,
            g.gene_id,
            g.identifier_id,
            g.gene_symbol,
            g.organism,
            COUNT(DISTINCT sgr.screen_id)::INT,
            COUNT(DISTINCT CASE WHEN sgr.hit_flag = TRUE THEN sgr.screen_id END)::INT,
            0,
            AVG(CASE WHEN sgr.hit_flag = TRUE THEN 100.0 ELSE 0 END)::NUMERIC,
            TRUE
        FROM gene g
        LEFT JOIN screen_gene_raw sgr ON (
            g.gene_id = sgr.gene_id
            AND g.version_id = sgr.version_id
        )
        WHERE g.version_id = p_version_id
        GROUP BY g.gene_id
        ON CONFLICT (version_id, gene_id) DO UPDATE SET
            is_current = TRUE
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_inserted FROM dim_data;

    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_dim_gene', 7, 'completed', v_inserted
    );

END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION build_fact_screen_gene_publication(
    p_run_id INT,
    p_version_id INT
) RETURNS VOID AS $$
BEGIN
    -- Build publication facts (placeholder - populated by separate process)
    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_fact_screen_gene_publication', 8, 'completed', 0
    );
END;
$$ LANGUAGE plpgsql;
