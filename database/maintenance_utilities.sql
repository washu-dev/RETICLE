/**
 * RETICLE DATA WAREHOUSE MAINTENANCE UTILITIES
 *
 * Provides:
 * - Purge specific version
 * - Purge all versions
 * - Storage usage analysis
 * - Data quality reports
 * - Rollback capabilities
 */

-- ============================================================================
-- PURGE UTILITIES
-- ============================================================================

/**
 * Purge a specific version and all its dependent data
 *
 * Usage: SELECT purge_version(version_id := 5);
 */
CREATE OR REPLACE FUNCTION purge_version(
    p_version_id INT
)
RETURNS TABLE(
    status VARCHAR,
    versions_deleted INT,
    staging_rows_deleted INT,
    processed_rows_deleted INT,
    storage_freed_mb NUMERIC,
    message TEXT
) AS $$
DECLARE
    v_organism VARCHAR(50);
    v_staging_rows INT := 0;
    v_processed_rows INT := 0;
    v_storage_before BIGINT;
    v_storage_after BIGINT;
BEGIN
    -- Validate version exists
    SELECT organism INTO v_organism
    FROM data_load_version
    WHERE version_id = p_version_id;

    IF v_organism IS NULL THEN
        RETURN QUERY SELECT
            'error'::VARCHAR,
            0,
            0,
            0,
            0::NUMERIC,
            'Version not found'::TEXT;
        RETURN;
    END IF;

    -- Get storage before
    SELECT pg_database_size(current_database()) INTO v_storage_before;

    -- Count rows to be deleted
    SELECT COUNT(*) INTO v_staging_rows
    FROM staging_screen
    WHERE version_id = p_version_id;

    SELECT COUNT(*) INTO v_processed_rows
    FROM screen_gene_raw
    WHERE version_id = p_version_id;

    -- Delete from dependent tables first (cascade will handle some)
    DELETE FROM etl_pipeline_run
    WHERE data_load_version_id = p_version_id;

    DELETE FROM fact_screen_gene_publication
    WHERE version_id = p_version_id;

    DELETE FROM fact_screen_gene
    WHERE version_id = p_version_id;

    DELETE FROM dim_screen
    WHERE version_id = p_version_id;

    DELETE FROM dim_gene
    WHERE version_id = p_version_id;

    DELETE FROM screen_gene_raw
    WHERE version_id = p_version_id;

    DELETE FROM screen
    WHERE version_id = p_version_id;

    DELETE FROM gene
    WHERE version_id = p_version_id;

    DELETE FROM staging_screen
    WHERE version_id = p_version_id;

    DELETE FROM staging_screen_gene
    WHERE version_id = p_version_id;

    -- Delete version record itself
    DELETE FROM data_load_version
    WHERE version_id = p_version_id;

    -- Get storage after
    SELECT pg_database_size(current_database()) INTO v_storage_after;

    RETURN QUERY SELECT
        'success'::VARCHAR,
        1::INT,
        v_staging_rows,
        v_processed_rows,
        ROUND((v_storage_before - v_storage_after) / 1024 / 1024::NUMERIC, 2),
        'Version ' || p_version_id || ' purged successfully'::TEXT;

END;
$$ LANGUAGE plpgsql;

/**
 * Purge all versions except current ones
 *
 * Usage: SELECT purge_old_versions();
 */
CREATE OR REPLACE FUNCTION purge_old_versions()
RETURNS TABLE(
    status VARCHAR,
    versions_deleted INT,
    total_rows_deleted INT,
    storage_freed_mb NUMERIC,
    message TEXT
) AS $$
DECLARE
    v_version_ids INT[];
    v_total_versions INT := 0;
    v_total_rows INT := 0;
    v_storage_before BIGINT;
    v_storage_after BIGINT;
    v_version_id INT;
BEGIN
    -- Get all non-current versions
    SELECT ARRAY_AGG(version_id), COUNT(*)
    INTO v_version_ids, v_total_versions
    FROM data_load_version
    WHERE is_current = FALSE;

    IF v_total_versions = 0 THEN
        RETURN QUERY SELECT
            'success'::VARCHAR,
            0,
            0,
            0::NUMERIC,
            'No old versions to purge'::TEXT;
        RETURN;
    END IF;

    v_storage_before := pg_database_size(current_database());

    -- Purge each old version
    FOREACH v_version_id IN ARRAY v_version_ids LOOP
        DELETE FROM etl_pipeline_run
        WHERE data_load_version_id = v_version_id;

        DELETE FROM fact_screen_gene_publication
        WHERE version_id = v_version_id;

        DELETE FROM fact_screen_gene
        WHERE version_id = v_version_id;

        DELETE FROM dim_screen
        WHERE version_id = v_version_id;

        DELETE FROM dim_gene
        WHERE version_id = v_version_id;

        DELETE FROM screen_gene_raw
        WHERE version_id = v_version_id;

        SELECT COUNT(*) INTO v_total_rows
        FROM staging_screen
        WHERE version_id = v_version_id;

        v_total_rows := v_total_rows +
            (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = v_version_id);

        DELETE FROM staging_screen
        WHERE version_id = v_version_id;

        DELETE FROM staging_screen_gene
        WHERE version_id = v_version_id;

        DELETE FROM screen
        WHERE version_id = v_version_id;

        DELETE FROM gene
        WHERE version_id = v_version_id;

        DELETE FROM data_load_version
        WHERE version_id = v_version_id;
    END LOOP;

    v_storage_after := pg_database_size(current_database());

    RETURN QUERY SELECT
        'success'::VARCHAR,
        v_total_versions,
        v_total_rows,
        ROUND((v_storage_before - v_storage_after) / 1024 / 1024::NUMERIC, 2),
        'Purged ' || v_total_versions || ' old versions'::TEXT;

END;
$$ LANGUAGE plpgsql;

/**
 * Purge ALL versions and data
 * WARNING: This is destructive - use with extreme caution!
 *
 * Usage: SELECT purge_all_data();
 */
CREATE OR REPLACE FUNCTION purge_all_data()
RETURNS TABLE(
    status VARCHAR,
    tables_truncated INT,
    rows_deleted BIGINT,
    message TEXT
) AS $$
DECLARE
    v_row_count BIGINT := 0;
BEGIN
    RAISE NOTICE 'DANGER: Purging all RETICLE data warehouse versions and history';

    -- Delete all dependent data in order
    DELETE FROM etl_audit_log;
    DELETE FROM etl_pipeline_run;
    DELETE FROM fact_screen_gene_publication;
    DELETE FROM fact_screen_gene;
    DELETE FROM dim_screen;
    DELETE FROM dim_gene;
    DELETE FROM screen_gene_raw;
    DELETE FROM staging_screen;
    DELETE FROM staging_screen_gene;
    DELETE FROM screen;
    DELETE FROM gene;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;

    DELETE FROM data_load_version;

    -- Reset version sequence to restart at 1
    ALTER SEQUENCE data_load_version_version_id_seq RESTART WITH 1;

    RETURN QUERY SELECT
        'success'::VARCHAR,
        11::INT,
        v_row_count,
        'All data warehouse versions purged and sequence reset to 1'::TEXT;

END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STORAGE & USAGE ANALYSIS
-- ============================================================================

/**
 * Detailed storage breakdown by version
 */
DROP FUNCTION IF EXISTS get_version_storage_details(integer) CASCADE;

CREATE OR REPLACE FUNCTION get_version_storage_details(
    p_version_id INT DEFAULT NULL
)
RETURNS TABLE(
    version_id INT,
    organism VARCHAR,
    load_date TIMESTAMP,
    is_current BOOLEAN,
    staging_screen_mb NUMERIC,
    staging_screen_gene_mb NUMERIC,
    screen_rows INT,
    gene_rows INT,
    screen_gene_raw_rows INT,
    fact_screen_gene_rows INT,
    dim_screen_rows INT,
    dim_gene_rows INT,
    total_size_mb NUMERIC
) AS $$
SELECT
    v.version_id,
    v.organism,
    v.load_date,
    v.is_current,
    ROUND(pg_total_relation_size('staging_screen'::regclass) *
        (SELECT COUNT(*) FROM staging_screen WHERE version_id = v.version_id) /
        NULLIF((SELECT COUNT(*) FROM staging_screen), 0) / 1024 / 1024::NUMERIC, 2),
    ROUND(pg_total_relation_size('staging_screen_gene'::regclass) *
        (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = v.version_id) /
        NULLIF((SELECT COUNT(*) FROM staging_screen_gene), 0) / 1024 / 1024::NUMERIC, 2),
    (SELECT COUNT(*) FROM screen WHERE version_id = v.version_id)::INT,
    (SELECT COUNT(*) FROM gene WHERE version_id = v.version_id)::INT,
    (SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = v.version_id)::INT,
    (SELECT COUNT(*) FROM fact_screen_gene WHERE version_id = v.version_id)::INT,
    (SELECT COUNT(*) FROM dim_screen WHERE version_id = v.version_id)::INT,
    (SELECT COUNT(*) FROM dim_gene WHERE version_id = v.version_id)::INT,
    ROUND(
        (pg_total_relation_size('staging_screen'::regclass) +
         pg_total_relation_size('staging_screen_gene'::regclass) +
         pg_total_relation_size('screen'::regclass) +
         pg_total_relation_size('gene'::regclass) +
         pg_total_relation_size('screen_gene_raw'::regclass) +
         pg_total_relation_size('fact_screen_gene'::regclass) +
         pg_total_relation_size('dim_screen'::regclass) +
         pg_total_relation_size('dim_gene'::regclass)) / 1024 / 1024::NUMERIC, 2)
FROM data_load_version v
WHERE p_version_id IS NULL OR version_id = p_version_id
ORDER BY v.load_date DESC;
$$ LANGUAGE SQL;

/**
 * Estimate space that would be freed by purging a version
 */
CREATE OR REPLACE FUNCTION estimate_purge_space(
    p_version_id INT
)
RETURNS TABLE(
    version_id INT,
    organism VARCHAR,
    estimated_space_mb NUMERIC,
    estimated_rows_deleted BIGINT
) AS $$
SELECT
    p_version_id,
    (SELECT organism FROM data_load_version WHERE version_id = p_version_id),
    ROUND(
        COALESCE(
            (SELECT COUNT(*) FROM staging_screen WHERE version_id = p_version_id) * 2000 +
            (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = p_version_id) * 800 +
            (SELECT COUNT(*) FROM screen WHERE version_id = p_version_id) * 100 +
            (SELECT COUNT(*) FROM gene WHERE version_id = p_version_id) * 100 +
            (SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = p_version_id) * 500 +
            (SELECT COUNT(*) FROM fact_screen_gene WHERE version_id = p_version_id) * 300,
            0
        ) / 1024 / 1024::NUMERIC, 2),
    COALESCE(
        (SELECT COUNT(*) FROM staging_screen WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM staging_screen_gene WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM screen WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM gene WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM screen_gene_raw WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM fact_screen_gene WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM dim_screen WHERE version_id = p_version_id) +
        (SELECT COUNT(*) FROM dim_gene WHERE version_id = p_version_id),
        0);
$$ LANGUAGE SQL;

-- ============================================================================
-- DATA QUALITY REPORTS
-- ============================================================================

/**
 * Validation issues by version
 */
CREATE OR REPLACE VIEW v_validation_issues AS
SELECT
    'screen_json' as table_name,
    version_id,
    COUNT(*) as issue_count,
    STRING_AGG(DISTINCT validation_errors, '; ') as error_types
FROM staging_screen
WHERE validation_errors IS NOT NULL
GROUP BY version_id

UNION ALL

SELECT
    'screen_gene_tsv',
    version_id,
    COUNT(*),
    STRING_AGG(DISTINCT validation_errors, '; ')
FROM staging_screen_gene
WHERE validation_errors IS NOT NULL
GROUP BY version_id

ORDER BY version_id DESC;

/**
 * ETL run summary
 */
CREATE OR REPLACE VIEW v_etl_run_summary AS
SELECT
    r.run_id,
    v.version_id,
    v.organism,
    r.run_date,
    r.status,
    r.total_duration_seconds,
    (SELECT COUNT(*) FROM etl_audit_log WHERE run_id = r.run_id) as steps_executed,
    (SELECT SUM(rows_inserted) FROM etl_audit_log WHERE run_id = r.run_id) as total_rows_inserted,
    (SELECT SUM(rows_skipped) FROM etl_audit_log WHERE run_id = r.run_id) as total_rows_skipped
FROM etl_pipeline_run r
JOIN data_load_version v ON r.data_load_version_id = v.version_id
ORDER BY r.run_date DESC;

-- ============================================================================
-- ROLLBACK CAPABILITIES
-- ============================================================================

/**
 * Promote a specific version back to current
 * (Useful if you need to roll back to an older version)
 */
CREATE OR REPLACE FUNCTION promote_version_to_current(
    p_version_id INT
)
RETURNS TABLE(
    status VARCHAR,
    message TEXT
) AS $$
DECLARE
    v_organism VARCHAR(50);
    v_run_id INT;
BEGIN
    -- Validate version exists
    SELECT organism INTO v_organism
    FROM data_load_version
    WHERE version_id = p_version_id;

    IF v_organism IS NULL THEN
        RETURN QUERY SELECT
            'error'::VARCHAR,
            'Version not found'::TEXT;
        RETURN;
    END IF;

    -- Get the latest run for this version
    SELECT run_id INTO v_run_id
    FROM etl_pipeline_run
    WHERE data_load_version_id = p_version_id
    AND status = 'completed'
    ORDER BY run_date DESC
    LIMIT 1;

    IF v_run_id IS NULL THEN
        RETURN QUERY SELECT
            'error'::VARCHAR,
            'No completed ETL run found for this version'::TEXT;
        RETURN;
    END IF;

    -- Unmark all current versions for this organism
    UPDATE data_load_version
    SET is_current = FALSE
    WHERE organism = v_organism
    AND is_current = TRUE;

    UPDATE etl_pipeline_run
    SET is_current = FALSE
    WHERE data_load_version_id IN (
        SELECT version_id FROM data_load_version WHERE organism = v_organism
    )
    AND is_current = TRUE;

    -- Mark this version as current
    UPDATE data_load_version
    SET is_current = TRUE
    WHERE version_id = p_version_id;

    UPDATE etl_pipeline_run
    SET is_current = TRUE
    WHERE run_id = v_run_id;

    RETURN QUERY SELECT
        'success'::VARCHAR,
        'Version ' || p_version_id || ' promoted to current'::TEXT;

END;
$$ LANGUAGE plpgsql;
