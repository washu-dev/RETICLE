/**
 * RETICLE Drop Versioned Data Warehouse Schema
 *
 * Completely removes all versioned data warehouse tables, functions, and sequences.
 * Idempotent - safe to run multiple times.
 *
 * WARNING: This is destructive and will delete all data!
 *
 * Usage:
 *   psql -h localhost -U reticle -d wcs_survey < database/migrations/0010_drop_versioned_data_warehouse.sql
 */

-- ============================================================================
-- DROP VIEWS
-- ============================================================================

DROP VIEW IF EXISTS v_validation_issues CASCADE;
DROP VIEW IF EXISTS v_etl_run_summary CASCADE;

-- ============================================================================
-- DROP FUNCTIONS
-- ============================================================================

DROP FUNCTION IF EXISTS purge_version(integer) CASCADE;
DROP FUNCTION IF EXISTS purge_old_versions() CASCADE;
DROP FUNCTION IF EXISTS purge_all_data() CASCADE;
DROP FUNCTION IF EXISTS get_version_storage_details(integer) CASCADE;
DROP FUNCTION IF EXISTS estimate_purge_space(integer) CASCADE;
DROP FUNCTION IF EXISTS promote_version_to_current(integer) CASCADE;

-- ============================================================================
-- DROP FACT/DIMENSION TABLES
-- ============================================================================

DROP TABLE IF EXISTS fact_screen_gene_publication CASCADE;
DROP TABLE IF EXISTS fact_screen_gene CASCADE;
DROP TABLE IF EXISTS dim_screen CASCADE;
DROP TABLE IF EXISTS dim_gene CASCADE;

-- ============================================================================
-- DROP PROCESSING TABLES
-- ============================================================================

DROP TABLE IF EXISTS screen_gene_raw CASCADE;

-- ============================================================================
-- DROP INTEGRATION TABLES
-- ============================================================================

DROP TABLE IF EXISTS screen CASCADE;
DROP TABLE IF EXISTS gene CASCADE;

-- ============================================================================
-- DROP STAGING TABLES
-- ============================================================================

DROP TABLE IF EXISTS staging_screen_gene CASCADE;
DROP TABLE IF EXISTS staging_screen CASCADE;

-- ============================================================================
-- DROP AUDIT/PIPELINE TABLES
-- ============================================================================

DROP TABLE IF EXISTS etl_audit_log CASCADE;
DROP TABLE IF EXISTS etl_pipeline_run CASCADE;

-- ============================================================================
-- DROP VERSION CONTROL TABLES
-- ============================================================================

DROP TABLE IF EXISTS data_load_version CASCADE;

-- ============================================================================
-- DROP SEQUENCES
-- ============================================================================

DROP SEQUENCE IF EXISTS data_load_version_version_id_seq;
DROP SEQUENCE IF EXISTS etl_pipeline_run_run_id_seq;
DROP SEQUENCE IF EXISTS etl_audit_log_audit_id_seq;
DROP SEQUENCE IF EXISTS staging_screen_staging_id_seq;
DROP SEQUENCE IF EXISTS staging_screen_gene_staging_id_seq;
DROP SEQUENCE IF EXISTS screen_screen_id_seq;
DROP SEQUENCE IF EXISTS gene_gene_id_seq;
DROP SEQUENCE IF EXISTS screen_gene_raw_screen_gene_raw_id_seq;
DROP SEQUENCE IF EXISTS fact_screen_gene_fact_id_seq;
DROP SEQUENCE IF EXISTS fact_screen_gene_publication_publication_id_seq;
DROP SEQUENCE IF EXISTS dim_screen_dim_screen_id_seq;
DROP SEQUENCE IF EXISTS dim_gene_dim_gene_id_seq;

-- ============================================================================
-- COMPLETE
-- ============================================================================

-- This script has successfully dropped all versioned data warehouse objects.
-- The database is now clean and ready for migration 0009 to be re-applied.
