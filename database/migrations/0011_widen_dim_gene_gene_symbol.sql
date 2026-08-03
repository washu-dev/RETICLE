/**
 * 0011 — Widen dim_gene.gene_symbol to VARCHAR(250)
 *
 * dim_gene.gene_symbol was created as VARCHAR(100) in 0006, but its source column
 * gene.gene_symbol is VARCHAR(250) (widened for staging in 0010). Human BioGRID
 * ORCS gene symbols are long comma/colon-separated lists, so build_dim_gene() —
 * which copies gene.gene_symbol into dim_gene.gene_symbol — failed on the human
 * load (version 7) with:
 *     ERROR: value too long for type character varying(100)
 *
 * Fix: widen dim_gene.gene_symbol to 250 to match gene.gene_symbol.
 *
 * The column is referenced by the view v_current_dim_gene (SELECT * ...), which
 * blocks ALTER COLUMN TYPE, so the view is dropped and recreated around the change.
 * Idempotent: safe to re-run (ALTER to the same type is a no-op; the view is
 * recreated each time).
 */

DROP VIEW IF EXISTS v_current_dim_gene;

ALTER TABLE dim_gene ALTER COLUMN gene_symbol TYPE VARCHAR(250);

CREATE OR REPLACE VIEW v_current_dim_gene AS
 SELECT dim_gene_id, version_id, run_id, gene_id, identifier_id, gene_symbol,
        organism, total_screens, total_screens_hit, total_publications,
        avg_hit_percentage, is_current, created_at
   FROM dim_gene
  WHERE is_current = true;
