-- ============================================================
-- RETICLE BioGrid Database Schema
-- ============================================================
-- Generated: 2026-06-11 17:35 UTC
-- Source: PostgreSQL 18.3 on reticle-db.cn8saqya88cd.us-east-1.rds.amazonaws.com
-- Database: reticle_biogrid
-- 
-- This file contains a complete dump of the public schema including:
--   - Sequences
--   - Tables (with columns, types, defaults, constraints)
--   - Primary Keys
--   - Unique Constraints
--   - Foreign Keys
--   - Indexes
--   - Views
--   - Functions/Procedures
--
-- To recreate the schema on a fresh database:
--   psql -h <host> -U <user> -d <database> -f reticle_schema.sql
--
-- ============================================================

BEGIN;

-- ============================================================
-- SECTION 1: SEQUENCES
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS public.data_load_version_version_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.data_warehouse_summary_summary_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.dim_gene_dim_gene_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.dim_screen_dim_screen_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.etl_audit_log_audit_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.etl_job_log_job_log_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.etl_pipeline_run_run_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.fact_screen_gene_fact_screen_gene_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.fact_screen_gene_publication_fact_screen_gene_publication_i_seq;
CREATE SEQUENCE IF NOT EXISTS public.gene_gene_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.gene_ortholog_gene_ortholog_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.library_gene_library_gene_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.library_library_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.metadata_annotation_annotation_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.publication_publication_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.residual_analysis_residual_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.residual_gene_score_residual_score_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.screen_comparison_comparison_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.screen_condition_condition_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.screen_gene_raw_screen_gene_raw_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.screen_gene_score_score_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.screen_screen_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.staging_screen_gene_staging_id_seq;
CREATE SEQUENCE IF NOT EXISTS public.staging_screen_staging_id_seq;

-- ============================================================
-- SECTION 2: TABLES (Base + Staging + Fact/Dimension tables)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.gene (
  gene_id INTEGER NOT NULL DEFAULT nextval('gene_gene_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  identifier_id VARCHAR(250) NOT NULL,
  gene_symbol VARCHAR(250),
  organism VARCHAR(50),
  is_current BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.screen (
  screen_id INTEGER NOT NULL DEFAULT nextval('screen_screen_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  biogrid_screen_id VARCHAR(100) NOT NULL,
  organism VARCHAR(50) NOT NULL,
  annotation_source VARCHAR(100),
  moi TEXT,
  notes TEXT,
  is_current BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.library (
  library_id INTEGER NOT NULL DEFAULT nextval('library_library_id_seq'::regclass),
  library_name VARCHAR(100) NOT NULL,
  library_version VARCHAR(50),
  organism VARCHAR(50) NOT NULL,
  total_genes INTEGER,
  sgrnas_per_gene INTEGER,
  total_sgrnas INTEGER,
  source VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.publication (
  publication_id INTEGER NOT NULL DEFAULT nextval('publication_publication_id_seq'::regclass),
  pmid VARCHAR(20),
  title TEXT,
  journal VARCHAR(255),
  year INTEGER,
  doi VARCHAR(100),
  methods_text TEXT,
  full_text_available BOOLEAN DEFAULT false,
  abstract_text TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  first_referenced_version_id INTEGER
);
CREATE TABLE IF NOT EXISTS public.dim_gene (
  dim_gene_id INTEGER NOT NULL DEFAULT nextval('dim_gene_dim_gene_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  identifier_id VARCHAR(250),
  gene_symbol VARCHAR(100),
  organism VARCHAR(50),
  total_screens INTEGER,
  total_screens_hit INTEGER,
  total_publications INTEGER,
  avg_hit_percentage NUMERIC,
  is_current BOOLEAN DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.dim_screen (
  dim_screen_id INTEGER NOT NULL DEFAULT nextval('dim_screen_dim_screen_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  biogrid_screen_id VARCHAR(100),
  organism VARCHAR(50),
  annotation_source VARCHAR(100),
  total_genes INTEGER,
  total_genes_hit INTEGER,
  total_publications INTEGER,
  avg_hit_percentage NUMERIC,
  is_current BOOLEAN DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.data_load_version (
  version_id INTEGER NOT NULL DEFAULT nextval('data_load_version_version_id_seq'::regclass),
  organism VARCHAR(50) NOT NULL,
  source_type VARCHAR(20) NOT NULL,
  load_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  loaded_by VARCHAR(100),
  load_description TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
  is_current BOOLEAN NOT NULL DEFAULT false,
  num_screens INTEGER,
  num_genes INTEGER,
  num_gene_hits INTEGER,
  file_count INTEGER,
  total_file_size_bytes BIGINT,
  json_filenames _text,
  tsv_filenames _text,
  metadata jsonb,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.data_warehouse_summary (
  summary_id INTEGER NOT NULL DEFAULT nextval('data_warehouse_summary_summary_id_seq'::regclass),
  organism VARCHAR(50) NOT NULL,
  total_publications INTEGER,
  total_screens INTEGER,
  total_genes INTEGER,
  total_libraries INTEGER,
  total_screen_genes INTEGER,
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.etl_audit_log (
  audit_id INTEGER NOT NULL DEFAULT nextval('etl_audit_log_audit_id_seq'::regclass),
  run_id INTEGER NOT NULL,
  step_name VARCHAR(100) NOT NULL,
  step_order INTEGER,
  status VARCHAR(20),
  rows_processed INTEGER,
  rows_inserted INTEGER,
  rows_updated INTEGER,
  rows_skipped INTEGER,
  duration_seconds NUMERIC,
  error_message TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.etl_job_log (
  job_log_id INTEGER NOT NULL DEFAULT nextval('etl_job_log_job_log_id_seq'::regclass),
  slurm_job_id VARCHAR(20) NOT NULL,
  version_id INTEGER NOT NULL,
  duration_seconds NUMERIC NOT NULL,
  status VARCHAR(20) NOT NULL,
  num_threads INTEGER,
  chunk_size INTEGER,
  batch_size INTEGER,
  error_message TEXT,
  submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.etl_pipeline_run (
  run_id INTEGER NOT NULL DEFAULT nextval('etl_pipeline_run_run_id_seq'::regclass),
  data_load_version_id INTEGER NOT NULL,
  pipeline_version VARCHAR(50),
  run_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
  is_current BOOLEAN NOT NULL DEFAULT false,
  total_duration_seconds NUMERIC,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS public.etl_progress (
  run_id INTEGER NOT NULL,
  stage VARCHAR(50) NOT NULL,
  rows_processed INTEGER DEFAULT 0,
  last_row_timestamp TIMESTAMP,
  error_message TEXT,
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.fact_screen_gene (
  fact_screen_gene_id INTEGER NOT NULL DEFAULT nextval('fact_screen_gene_fact_screen_gene_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  hit_count INTEGER,
  hit_percentage NUMERIC,
  avg_raw_score NUMERIC,
  total_publications INTEGER,
  condition_count INTEGER,
  is_current BOOLEAN DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.fact_screen_gene_publication (
  fact_screen_gene_publication_id INTEGER NOT NULL DEFAULT nextval('fact_screen_gene_publication_fact_screen_gene_publication_i_seq'::regclass),
  version_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  publication_id INTEGER NOT NULL,
  hit_flag BOOLEAN,
  score_1 NUMERIC,
  score_2 NUMERIC,
  score_3 NUMERIC,
  score_4 NUMERIC,
  score_5 NUMERIC,
  is_current BOOLEAN DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.gene_ortholog (
  gene_ortholog_id INTEGER NOT NULL DEFAULT nextval('gene_ortholog_gene_ortholog_id_seq'::regclass),
  gene_id_1 INTEGER NOT NULL,
  gene_id_2 INTEGER NOT NULL,
  confidence VARCHAR(20),
  source VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.library_gene (
  library_gene_id INTEGER NOT NULL DEFAULT nextval('library_gene_library_gene_id_seq'::regclass),
  library_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  n_sgrnas INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.metadata_annotation (
  annotation_id INTEGER NOT NULL DEFAULT nextval('metadata_annotation_annotation_id_seq'::regclass),
  screen_id INTEGER NOT NULL,
  annotated_by VARCHAR(100),
  annotation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  llm_confidence jsonb,
  review_status VARCHAR(50),
  reviewed_at TIMESTAMP,
  changes_made jsonb,
  review_notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.residual_analysis (
  residual_id INTEGER NOT NULL DEFAULT nextval('residual_analysis_residual_id_seq'::regclass),
  screen_id INTEGER NOT NULL,
  comparison_a_id INTEGER NOT NULL,
  comparison_b_id INTEGER NOT NULL,
  analysis_label VARCHAR(255),
  spline_knots jsonb,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.residual_gene_score (
  residual_score_id INTEGER NOT NULL DEFAULT nextval('residual_gene_score_residual_score_id_seq'::regclass),
  residual_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  score_a DOUBLE PRECISION,
  score_b DOUBLE PRECISION,
  residual_score DOUBLE PRECISION,
  sunbeam_zone VARCHAR(50),
  rank INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  version VARCHAR(50) NOT NULL,
  description TEXT,
  executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  execution_time_ms INTEGER
);
CREATE TABLE IF NOT EXISTS public.screen_comparison (
  comparison_id INTEGER NOT NULL DEFAULT nextval('screen_comparison_comparison_id_seq'::regclass),
  screen_id INTEGER NOT NULL,
  condition_a_id INTEGER NOT NULL,
  condition_b_id INTEGER NOT NULL,
  comparison_label VARCHAR(255),
  selection_method VARCHAR(100),
  selection_direction VARCHAR(50),
  comparison_direction VARCHAR(50),
  coverage_type VARCHAR(50),
  hit_threshold_type VARCHAR(50),
  hit_threshold_value DOUBLE PRECISION,
  n_replicates INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.screen_condition (
  condition_id INTEGER NOT NULL DEFAULT nextval('screen_condition_condition_id_seq'::regclass),
  screen_id INTEGER NOT NULL,
  condition_name VARCHAR(255) NOT NULL,
  condition_type VARCHAR(50),
  treatment_agent VARCHAR(255),
  concentration VARCHAR(255),
  timepoint_hours INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.screen_gene_raw (
  screen_gene_raw_id INTEGER NOT NULL DEFAULT nextval('screen_gene_raw_screen_gene_raw_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  run_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  biogrid_screen_id VARCHAR(100),
  identifier_id VARCHAR(250),
  hit_flag BOOLEAN,
  score_1 NUMERIC,
  score_2 NUMERIC,
  score_3 NUMERIC,
  score_4 NUMERIC,
  score_5 NUMERIC,
  raw_score NUMERIC,
  is_current BOOLEAN DEFAULT true,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.screen_gene_score (
  score_id INTEGER NOT NULL DEFAULT nextval('screen_gene_score_score_id_seq'::regclass),
  comparison_id INTEGER NOT NULL,
  gene_id INTEGER NOT NULL,
  raw_score DOUBLE PRECISION,
  normalized_percentile DOUBLE PRECISION,
  rank INTEGER,
  fdr DOUBLE PRECISION,
  mean_lfc DOUBLE PRECISION,
  n_sgrnas_scored INTEGER,
  hit_flag BOOLEAN DEFAULT false,
  direction_flag VARCHAR(50),
  adj_score DOUBLE PRECISION,
  data_state VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.staging_screen (
  staging_id INTEGER NOT NULL DEFAULT nextval('staging_screen_staging_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  biogrid_screen_id VARCHAR(100) NOT NULL,
  organism VARCHAR(50) NOT NULL,
  annotation_source VARCHAR(100),
  moi TEXT,
  notes TEXT,
  validated BOOLEAN DEFAULT false,
  validation_errors TEXT,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS public.staging_screen_gene (
  staging_id INTEGER NOT NULL DEFAULT nextval('staging_screen_gene_staging_id_seq'::regclass),
  version_id INTEGER NOT NULL,
  screen_id INTEGER NOT NULL,
  identifier_id VARCHAR(250) NOT NULL,
  gene_symbol VARCHAR(250),
  biogrid_screen_id VARCHAR(100),
  hit_flag BOOLEAN,
  score_1 NUMERIC,
  score_2 NUMERIC,
  score_3 NUMERIC,
  score_4 NUMERIC,
  score_5 NUMERIC,
  validated BOOLEAN DEFAULT false,
  validation_errors TEXT,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  official_symbol VARCHAR(250),
  aliases TEXT,
  organism_id INTEGER,
  organism_official VARCHAR(100),
  identifier_type VARCHAR(50),
  source VARCHAR(100),
  tsv_filename VARCHAR(255),
  tsv_row_number INTEGER
);

-- ============================================================
-- SECTION 3: PRIMARY KEY CONSTRAINTS
-- ============================================================

ALTER TABLE public.data_load_version ADD CONSTRAINT data_load_version_pkey PRIMARY KEY (version_id);
ALTER TABLE public.data_warehouse_summary ADD CONSTRAINT data_warehouse_summary_pkey PRIMARY KEY (summary_id);
ALTER TABLE public.dim_gene ADD CONSTRAINT dim_gene_pkey PRIMARY KEY (dim_gene_id);
ALTER TABLE public.dim_screen ADD CONSTRAINT dim_screen_pkey PRIMARY KEY (dim_screen_id);
ALTER TABLE public.etl_audit_log ADD CONSTRAINT etl_audit_log_pkey PRIMARY KEY (audit_id);
ALTER TABLE public.etl_job_log ADD CONSTRAINT etl_job_log_pkey PRIMARY KEY (job_log_id);
ALTER TABLE public.etl_pipeline_run ADD CONSTRAINT etl_pipeline_run_pkey PRIMARY KEY (run_id);
ALTER TABLE public.etl_progress ADD CONSTRAINT etl_progress_pkey PRIMARY KEY (run_id);
ALTER TABLE public.fact_screen_gene ADD CONSTRAINT fact_screen_gene_pkey PRIMARY KEY (fact_screen_gene_id);
ALTER TABLE public.fact_screen_gene_publication ADD CONSTRAINT fact_screen_gene_publication_pkey PRIMARY KEY (fact_screen_gene_publication_id);
ALTER TABLE public.gene ADD CONSTRAINT gene_pkey PRIMARY KEY (gene_id);
ALTER TABLE public.gene_ortholog ADD CONSTRAINT gene_ortholog_pkey PRIMARY KEY (gene_ortholog_id);
ALTER TABLE public.library ADD CONSTRAINT library_pkey PRIMARY KEY (library_id);
ALTER TABLE public.library_gene ADD CONSTRAINT library_gene_pkey PRIMARY KEY (library_gene_id);
ALTER TABLE public.metadata_annotation ADD CONSTRAINT metadata_annotation_pkey PRIMARY KEY (annotation_id);
ALTER TABLE public.publication ADD CONSTRAINT publication_pkey PRIMARY KEY (publication_id);
ALTER TABLE public.residual_analysis ADD CONSTRAINT residual_analysis_pkey PRIMARY KEY (residual_id);
ALTER TABLE public.residual_gene_score ADD CONSTRAINT residual_gene_score_pkey PRIMARY KEY (residual_score_id);
ALTER TABLE public.schema_migrations ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);
ALTER TABLE public.screen ADD CONSTRAINT screen_pkey PRIMARY KEY (screen_id);
ALTER TABLE public.screen_comparison ADD CONSTRAINT screen_comparison_pkey PRIMARY KEY (comparison_id);
ALTER TABLE public.screen_condition ADD CONSTRAINT screen_condition_pkey PRIMARY KEY (condition_id);
ALTER TABLE public.screen_gene_raw ADD CONSTRAINT screen_gene_raw_pkey PRIMARY KEY (screen_gene_raw_id);
ALTER TABLE public.screen_gene_score ADD CONSTRAINT screen_gene_score_pkey PRIMARY KEY (score_id);
ALTER TABLE public.staging_screen ADD CONSTRAINT staging_screen_pkey PRIMARY KEY (staging_id);
ALTER TABLE public.staging_screen_gene ADD CONSTRAINT staging_screen_gene_pkey PRIMARY KEY (staging_id);

-- ============================================================
-- SECTION 4: UNIQUE CONSTRAINTS
-- ============================================================

ALTER TABLE public.data_load_version ADD CONSTRAINT data_load_version_organism_source_type_load_date_key UNIQUE (organism, source_type, load_date);
ALTER TABLE public.data_warehouse_summary ADD CONSTRAINT data_warehouse_summary_organism_key UNIQUE (organism);
ALTER TABLE public.dim_gene ADD CONSTRAINT dim_gene_version_id_gene_id_key UNIQUE (version_id, gene_id);
ALTER TABLE public.dim_screen ADD CONSTRAINT dim_screen_version_id_screen_id_key UNIQUE (version_id, screen_id);
ALTER TABLE public.fact_screen_gene ADD CONSTRAINT fact_screen_gene_version_id_screen_id_gene_id_key UNIQUE (version_id, screen_id, gene_id);
ALTER TABLE public.fact_screen_gene_publication ADD CONSTRAINT fact_screen_gene_publication_version_id_screen_id_gene_id_p_key UNIQUE (version_id, screen_id, gene_id, publication_id);
ALTER TABLE public.gene ADD CONSTRAINT gene_version_id_identifier_id_key UNIQUE (version_id, identifier_id);
ALTER TABLE public.gene_ortholog ADD CONSTRAINT gene_ortholog_gene_id_1_gene_id_2_key UNIQUE (gene_id_1, gene_id_2);
ALTER TABLE public.library ADD CONSTRAINT library_library_name_library_version_organism_key UNIQUE (library_name, library_version, organism);
ALTER TABLE public.library_gene ADD CONSTRAINT library_gene_library_id_gene_id_key UNIQUE (library_id, gene_id);
ALTER TABLE public.publication ADD CONSTRAINT publication_pmid_key UNIQUE (pmid);
ALTER TABLE public.residual_analysis ADD CONSTRAINT residual_analysis_screen_id_comparison_a_id_comparison_b_id_key UNIQUE (screen_id, comparison_a_id, comparison_b_id);
ALTER TABLE public.residual_gene_score ADD CONSTRAINT residual_gene_score_residual_id_gene_id_key UNIQUE (residual_id, gene_id);
ALTER TABLE public.screen ADD CONSTRAINT screen_version_id_biogrid_screen_id_key UNIQUE (version_id, biogrid_screen_id);
ALTER TABLE public.screen_comparison ADD CONSTRAINT screen_comparison_screen_id_condition_a_id_condition_b_id_c_key UNIQUE (screen_id, condition_a_id, condition_b_id, comparison_direction);
ALTER TABLE public.screen_condition ADD CONSTRAINT screen_condition_screen_id_condition_name_key UNIQUE (screen_id, condition_name);
ALTER TABLE public.screen_gene_raw ADD CONSTRAINT screen_gene_raw_version_id_screen_id_gene_id_key UNIQUE (version_id, screen_id, gene_id);
ALTER TABLE public.screen_gene_score ADD CONSTRAINT screen_gene_score_comparison_id_gene_id_key UNIQUE (comparison_id, gene_id);
ALTER TABLE public.staging_screen ADD CONSTRAINT staging_screen_version_id_biogrid_screen_id_key UNIQUE (version_id, biogrid_screen_id);
ALTER TABLE public.staging_screen_gene ADD CONSTRAINT staging_screen_gene_version_id_biogrid_screen_id_identifier_key UNIQUE (version_id, biogrid_screen_id, identifier_id);

-- ============================================================
-- SECTION 5: FOREIGN KEY CONSTRAINTS
-- ============================================================

ALTER TABLE public.dim_gene ADD CONSTRAINT dim_gene_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.dim_gene ADD CONSTRAINT dim_gene_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.dim_screen ADD CONSTRAINT dim_screen_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.dim_screen ADD CONSTRAINT dim_screen_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.etl_audit_log ADD CONSTRAINT etl_audit_log_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.etl_job_log ADD CONSTRAINT etl_job_log_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.etl_pipeline_run ADD CONSTRAINT etl_pipeline_run_data_load_version_id_fkey FOREIGN KEY (data_load_version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.etl_progress ADD CONSTRAINT etl_progress_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.fact_screen_gene ADD CONSTRAINT fact_screen_gene_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.fact_screen_gene ADD CONSTRAINT fact_screen_gene_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.fact_screen_gene_publication ADD CONSTRAINT fact_screen_gene_publication_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publication(publication_id);
ALTER TABLE public.fact_screen_gene_publication ADD CONSTRAINT fact_screen_gene_publication_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.fact_screen_gene_publication ADD CONSTRAINT fact_screen_gene_publication_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.gene ADD CONSTRAINT gene_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.library_gene ADD CONSTRAINT library_gene_library_id_fkey FOREIGN KEY (library_id) REFERENCES public.library(library_id);
ALTER TABLE public.residual_analysis ADD CONSTRAINT residual_analysis_comparison_a_id_fkey FOREIGN KEY (comparison_a_id) REFERENCES public.screen_comparison(comparison_id);
ALTER TABLE public.residual_analysis ADD CONSTRAINT residual_analysis_comparison_b_id_fkey FOREIGN KEY (comparison_b_id) REFERENCES public.screen_comparison(comparison_id);
ALTER TABLE public.residual_gene_score ADD CONSTRAINT residual_gene_score_residual_id_fkey FOREIGN KEY (residual_id) REFERENCES public.residual_analysis(residual_id);
ALTER TABLE public.screen ADD CONSTRAINT screen_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.screen_comparison ADD CONSTRAINT screen_comparison_condition_a_id_fkey FOREIGN KEY (condition_a_id) REFERENCES public.screen_condition(condition_id);
ALTER TABLE public.screen_comparison ADD CONSTRAINT screen_comparison_condition_b_id_fkey FOREIGN KEY (condition_b_id) REFERENCES public.screen_condition(condition_id);
ALTER TABLE public.screen_gene_raw ADD CONSTRAINT screen_gene_raw_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.etl_pipeline_run(run_id);
ALTER TABLE public.screen_gene_raw ADD CONSTRAINT screen_gene_raw_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.screen_gene_score ADD CONSTRAINT screen_gene_score_comparison_id_fkey FOREIGN KEY (comparison_id) REFERENCES public.screen_comparison(comparison_id);
ALTER TABLE public.staging_screen ADD CONSTRAINT staging_screen_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);
ALTER TABLE public.staging_screen_gene ADD CONSTRAINT staging_screen_gene_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.data_load_version(version_id);

-- ============================================================
-- SECTION 6: INDEXES
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS data_load_version_organism_source_type_load_date_key ON public.data_load_version USING btree (organism, source_type, load_date);
CREATE INDEX IF NOT EXISTS idx_data_load_version_current ON public.data_load_version USING btree (organism, is_current) WHERE (is_current = true);
CREATE UNIQUE INDEX IF NOT EXISTS data_warehouse_summary_organism_key ON public.data_warehouse_summary USING btree (organism);
CREATE UNIQUE INDEX IF NOT EXISTS dim_gene_version_id_gene_id_key ON public.dim_gene USING btree (version_id, gene_id);
CREATE INDEX IF NOT EXISTS idx_dim_gene_version ON public.dim_gene USING btree (version_id, is_current);
CREATE UNIQUE INDEX IF NOT EXISTS dim_screen_version_id_screen_id_key ON public.dim_screen USING btree (version_id, screen_id);
CREATE INDEX IF NOT EXISTS idx_dim_screen_version ON public.dim_screen USING btree (version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_etl_job_log_completed_at ON public.etl_job_log USING btree (completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_etl_job_log_slurm_id ON public.etl_job_log USING btree (slurm_job_id);
CREATE INDEX IF NOT EXISTS idx_etl_job_log_version ON public.etl_job_log USING btree (version_id);
CREATE INDEX IF NOT EXISTS idx_etl_pipeline_run_current ON public.etl_pipeline_run USING btree (run_id, is_current) WHERE (is_current = true);
CREATE INDEX IF NOT EXISTS idx_etl_progress_stage ON public.etl_progress USING btree (stage);
CREATE INDEX IF NOT EXISTS idx_etl_progress_updated ON public.etl_progress USING btree (last_updated);
CREATE UNIQUE INDEX IF NOT EXISTS fact_screen_gene_version_id_screen_id_gene_id_key ON public.fact_screen_gene USING btree (version_id, screen_id, gene_id);
CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_version ON public.fact_screen_gene USING btree (version_id, is_current);
CREATE UNIQUE INDEX IF NOT EXISTS fact_screen_gene_publication_version_id_screen_id_gene_id_p_key ON public.fact_screen_gene_publication USING btree (version_id, screen_id, gene_id, publication_id);
CREATE INDEX IF NOT EXISTS idx_fact_screen_gene_publication_version ON public.fact_screen_gene_publication USING btree (version_id, is_current);
CREATE UNIQUE INDEX IF NOT EXISTS gene_version_id_identifier_id_key ON public.gene USING btree (version_id, identifier_id);
CREATE UNIQUE INDEX IF NOT EXISTS gene_ortholog_gene_id_1_gene_id_2_key ON public.gene_ortholog USING btree (gene_id_1, gene_id_2);
CREATE INDEX IF NOT EXISTS idx_gene_ortholog_gene1 ON public.gene_ortholog USING btree (gene_id_1);
CREATE INDEX IF NOT EXISTS idx_gene_ortholog_gene2 ON public.gene_ortholog USING btree (gene_id_2);
CREATE INDEX IF NOT EXISTS idx_library_organism ON public.library USING btree (organism);
CREATE UNIQUE INDEX IF NOT EXISTS library_library_name_library_version_organism_key ON public.library USING btree (library_name, library_version, organism);
CREATE INDEX IF NOT EXISTS idx_library_gene_gene ON public.library_gene USING btree (gene_id);
CREATE INDEX IF NOT EXISTS idx_library_gene_library ON public.library_gene USING btree (library_id);
CREATE UNIQUE INDEX IF NOT EXISTS library_gene_library_id_gene_id_key ON public.library_gene USING btree (library_id, gene_id);
CREATE INDEX IF NOT EXISTS idx_metadata_annotation_screen ON public.metadata_annotation USING btree (screen_id);
CREATE INDEX IF NOT EXISTS idx_metadata_annotation_status ON public.metadata_annotation USING btree (review_status);
CREATE INDEX IF NOT EXISTS idx_publication_pmid ON public.publication USING btree (pmid);
CREATE INDEX IF NOT EXISTS idx_publication_year ON public.publication USING btree (year);
CREATE UNIQUE INDEX IF NOT EXISTS publication_pmid_key ON public.publication USING btree (pmid);
CREATE INDEX IF NOT EXISTS idx_residual_analysis_screen ON public.residual_analysis USING btree (screen_id);
CREATE UNIQUE INDEX IF NOT EXISTS residual_analysis_screen_id_comparison_a_id_comparison_b_id_key ON public.residual_analysis USING btree (screen_id, comparison_a_id, comparison_b_id);
CREATE INDEX IF NOT EXISTS idx_residual_gene_score_residual ON public.residual_gene_score USING btree (residual_id);
CREATE INDEX IF NOT EXISTS idx_residual_gene_score_sunbeam ON public.residual_gene_score USING btree (sunbeam_zone);
CREATE UNIQUE INDEX IF NOT EXISTS residual_gene_score_residual_id_gene_id_key ON public.residual_gene_score USING btree (residual_id, gene_id);
CREATE UNIQUE INDEX IF NOT EXISTS screen_version_id_biogrid_screen_id_key ON public.screen USING btree (version_id, biogrid_screen_id);
CREATE INDEX IF NOT EXISTS idx_screen_comparison_conditions ON public.screen_comparison USING btree (condition_a_id, condition_b_id);
CREATE INDEX IF NOT EXISTS idx_screen_comparison_screen ON public.screen_comparison USING btree (screen_id);
CREATE UNIQUE INDEX IF NOT EXISTS screen_comparison_screen_id_condition_a_id_condition_b_id_c_key ON public.screen_comparison USING btree (screen_id, condition_a_id, condition_b_id, comparison_direction);
CREATE INDEX IF NOT EXISTS idx_screen_condition_screen ON public.screen_condition USING btree (screen_id);
CREATE UNIQUE INDEX IF NOT EXISTS screen_condition_screen_id_condition_name_key ON public.screen_condition USING btree (screen_id, condition_name);
CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_gene ON public.screen_gene_raw USING btree (gene_id, version_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_screen ON public.screen_gene_raw USING btree (screen_id, version_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_raw_version ON public.screen_gene_raw USING btree (version_id, is_current);
CREATE UNIQUE INDEX IF NOT EXISTS screen_gene_raw_version_id_screen_id_gene_id_key ON public.screen_gene_raw USING btree (version_id, screen_id, gene_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_score_comparison ON public.screen_gene_score USING btree (comparison_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_score_gene ON public.screen_gene_score USING btree (gene_id);
CREATE INDEX IF NOT EXISTS idx_screen_gene_score_hit ON public.screen_gene_score USING btree (hit_flag) WHERE (hit_flag = true);
CREATE UNIQUE INDEX IF NOT EXISTS screen_gene_score_comparison_id_gene_id_key ON public.screen_gene_score USING btree (comparison_id, gene_id);
CREATE INDEX IF NOT EXISTS idx_staging_screen_version ON public.staging_screen USING btree (version_id);
CREATE UNIQUE INDEX IF NOT EXISTS staging_screen_version_id_biogrid_screen_id_key ON public.staging_screen USING btree (version_id, biogrid_screen_id);
CREATE INDEX IF NOT EXISTS idx_staging_screen_gene_hit ON public.staging_screen_gene USING btree (version_id, hit_flag);
CREATE INDEX IF NOT EXISTS idx_staging_screen_gene_version ON public.staging_screen_gene USING btree (version_id);
CREATE UNIQUE INDEX IF NOT EXISTS staging_screen_gene_version_id_biogrid_screen_id_identifier_key ON public.staging_screen_gene USING btree (version_id, biogrid_screen_id, identifier_id);

-- ============================================================
-- SECTION 7: VIEWS
-- ============================================================

CREATE OR REPLACE VIEW public.etl_job_performance AS
 SELECT job_log_id,
    slurm_job_id,
    version_id,
    duration_seconds,
    num_threads,
    round(((duration_seconds * (num_threads)::numeric) / 100.0), 2) AS thread_efficiency,
    status,
    completed_at
   FROM etl_job_log
  WHERE ((status)::text = 'completed'::text)
  ORDER BY completed_at DESC;;
CREATE OR REPLACE VIEW public.etl_job_stats AS
 SELECT version_id,
    count(*) AS total_runs,
    avg(duration_seconds) AS avg_duration,
    min(duration_seconds) AS min_duration,
    max(duration_seconds) AS max_duration,
    sum(
        CASE
            WHEN ((status)::text = 'completed'::text) THEN 1
            ELSE 0
        END) AS successful_runs,
    sum(
        CASE
            WHEN ((status)::text = 'failed'::text) THEN 1
            ELSE 0
        END) AS failed_runs,
    max(completed_at) AS last_run
   FROM etl_job_log
  GROUP BY version_id
  ORDER BY version_id DESC;;
CREATE OR REPLACE VIEW public.v_current_dim_gene AS
 SELECT dim_gene_id,
    version_id,
    run_id,
    gene_id,
    identifier_id,
    gene_symbol,
    organism,
    total_screens,
    total_screens_hit,
    total_publications,
    avg_hit_percentage,
    is_current,
    created_at
   FROM dim_gene
  WHERE (is_current = true);;
CREATE OR REPLACE VIEW public.v_current_dim_screen AS
 SELECT dim_screen_id,
    version_id,
    run_id,
    screen_id,
    biogrid_screen_id,
    organism,
    annotation_source,
    total_genes,
    total_genes_hit,
    total_publications,
    avg_hit_percentage,
    is_current,
    created_at
   FROM dim_screen
  WHERE (is_current = true);;
CREATE OR REPLACE VIEW public.v_current_fact_screen_gene AS
 SELECT fact_screen_gene_id,
    version_id,
    run_id,
    screen_id,
    gene_id,
    hit_count,
    hit_percentage,
    avg_raw_score,
    total_publications,
    condition_count,
    is_current,
    created_at
   FROM fact_screen_gene
  WHERE (is_current = true);;
CREATE OR REPLACE VIEW public.v_current_fact_screen_gene_publication AS
 SELECT fact_screen_gene_publication_id,
    version_id,
    run_id,
    screen_id,
    gene_id,
    publication_id,
    hit_flag,
    score_1,
    score_2,
    score_3,
    score_4,
    score_5,
    is_current,
    created_at
   FROM fact_screen_gene_publication
  WHERE (is_current = true);;
CREATE OR REPLACE VIEW public.v_data_load_versions AS
 SELECT version_id,
    organism,
    load_date,
    status,
    is_current,
    num_screens,
    num_genes,
    num_gene_hits,
    file_count,
    round((((total_file_size_bytes / 1024) / 1024))::numeric, 2) AS total_file_size_mb,
    created_at
   FROM data_load_version
  ORDER BY load_date DESC;;
CREATE OR REPLACE VIEW public.v_etl_pipeline_history AS
 SELECT r.run_id,
    v.version_id,
    v.organism,
    v.load_date,
    r.run_date,
    r.status,
    r.is_current,
    r.total_duration_seconds,
    r.error_message,
    ( SELECT count(*) AS count
           FROM etl_audit_log
          WHERE (etl_audit_log.run_id = r.run_id)) AS audit_log_entries
   FROM (etl_pipeline_run r
     JOIN data_load_version v ON ((r.data_load_version_id = v.version_id)))
  ORDER BY r.run_date DESC;;
CREATE OR REPLACE VIEW public.v_etl_run_summary AS
 SELECT r.run_id,
    v.version_id,
    v.organism,
    r.run_date,
    r.status,
    r.total_duration_seconds,
    ( SELECT count(*) AS count
           FROM etl_audit_log
          WHERE (etl_audit_log.run_id = r.run_id)) AS steps_executed,
    ( SELECT sum(etl_audit_log.rows_inserted) AS sum
           FROM etl_audit_log
          WHERE (etl_audit_log.run_id = r.run_id)) AS total_rows_inserted,
    ( SELECT sum(etl_audit_log.rows_skipped) AS sum
           FROM etl_audit_log
          WHERE (etl_audit_log.run_id = r.run_id)) AS total_rows_skipped
   FROM (etl_pipeline_run r
     JOIN data_load_version v ON ((r.data_load_version_id = v.version_id)))
  ORDER BY r.run_date DESC;;
CREATE OR REPLACE VIEW public.v_validation_issues AS
 SELECT 'screen_json'::text AS table_name,
    staging_screen.version_id,
    count(*) AS issue_count,
    string_agg(DISTINCT staging_screen.validation_errors, '; '::text) AS error_types
   FROM staging_screen
  WHERE (staging_screen.validation_errors IS NOT NULL)
  GROUP BY staging_screen.version_id
UNION ALL
 SELECT 'screen_gene_tsv'::text AS table_name,
    staging_screen_gene.version_id,
    count(*) AS issue_count,
    string_agg(DISTINCT staging_screen_gene.validation_errors, '; '::text) AS error_types
   FROM staging_screen_gene
  WHERE (staging_screen_gene.validation_errors IS NOT NULL)
  GROUP BY staging_screen_gene.version_id
  ORDER BY 2 DESC;;
CREATE OR REPLACE VIEW public.v_version_storage_usage AS
 SELECT version_id,
    organism,
    load_date,
    is_current,
    pg_size_pretty(((pg_total_relation_size('staging_screen'::regclass) * ( SELECT count(*) AS count
           FROM staging_screen
          WHERE (staging_screen.version_id = v.version_id))) / NULLIF(( SELECT count(*) AS count
           FROM staging_screen), 0))) AS staging_screen_size,
    pg_size_pretty(((pg_total_relation_size('staging_screen_gene'::regclass) * ( SELECT count(*) AS count
           FROM staging_screen_gene
          WHERE (staging_screen_gene.version_id = v.version_id))) / NULLIF(( SELECT count(*) AS count
           FROM staging_screen_gene), 0))) AS staging_screen_gene_size,
    ( SELECT count(*) AS count
           FROM staging_screen
          WHERE (staging_screen.version_id = v.version_id)) AS screen_json_rows,
    ( SELECT count(*) AS count
           FROM staging_screen_gene
          WHERE (staging_screen_gene.version_id = v.version_id)) AS screen_gene_tsv_rows,
    ( SELECT count(*) AS count
           FROM screen_gene_raw
          WHERE (screen_gene_raw.version_id = v.version_id)) AS screen_gene_raw_rows,
    ( SELECT count(*) AS count
           FROM fact_screen_gene
          WHERE (fact_screen_gene.version_id = v.version_id)) AS fact_screen_gene_rows
   FROM data_load_version v
  ORDER BY load_date DESC;;

-- ============================================================
-- SECTION 8: FUNCTIONS AND PROCEDURES
-- ============================================================

CREATE OR REPLACE FUNCTION public.build_dim_gene(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.build_dim_screen(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.build_fact_screen_gene(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.build_fact_screen_gene_publication(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
BEGIN
    -- Build publication facts (placeholder - populated by separate process)
    INSERT INTO etl_audit_log (
        run_id, step_name, step_order, status, rows_inserted
    ) VALUES (
        p_run_id, 'build_fact_screen_gene_publication', 8, 'completed', 0
    );
END;
$function$
;
CREATE OR REPLACE FUNCTION public.build_screen_gene_raw(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.estimate_purge_space(p_version_id integer)
 RETURNS TABLE(version_id integer, organism character varying, estimated_space_mb numeric, estimated_rows_deleted bigint)
 LANGUAGE sql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.get_version_storage_details(p_version_id integer DEFAULT NULL::integer)
 RETURNS TABLE(version_id integer, organism character varying, load_date timestamp without time zone, is_current boolean, staging_screen_mb numeric, staging_screen_gene_mb numeric, screen_rows integer, gene_rows integer, screen_gene_raw_rows integer, fact_screen_gene_rows integer, dim_screen_rows integer, dim_gene_rows integer, total_size_mb numeric)
 LANGUAGE sql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.load_genes(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.load_screens(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.promote_version_to_current(p_version_id integer)
 RETURNS TABLE(status character varying, message text)
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.purge_all_data()
 RETURNS TABLE(status character varying, tables_truncated integer, rows_deleted bigint, message text)
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.purge_old_versions()
 RETURNS TABLE(status character varying, versions_deleted integer, total_rows_deleted integer, storage_freed_mb numeric, message text)
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.purge_version(p_version_id integer)
 RETURNS TABLE(status character varying, versions_deleted integer, staging_rows_deleted integer, processed_rows_deleted integer, storage_freed_mb numeric, message text)
 LANGUAGE plpgsql
AS $function$
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

    -- Delete from dependent tables first
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
$function$
;
CREATE OR REPLACE FUNCTION public.run_etl_pipeline(p_version_id integer, p_pipeline_version character varying DEFAULT '1.0'::character varying)
 RETURNS TABLE(run_id integer, status character varying, duration_seconds numeric, message text)
 LANGUAGE plpgsql
AS $function$
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
$function$
;
CREATE OR REPLACE FUNCTION public.validate_staging_data(p_run_id integer, p_version_id integer)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
$function$
;

-- ============================================================
-- END OF SCHEMA
-- ============================================================

COMMIT;

