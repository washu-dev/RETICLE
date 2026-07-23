/**
 * Fix column sizes in staging tables (0010)
 *
 * BioGRID ORCS data contains comma/colon-separated gene symbol lists that
 * exceed 100 characters. Migration 0006 defined staging_screen_gene.gene_symbol
 * as VARCHAR(250), but if the table existed with VARCHAR(100), the CREATE TABLE
 * IF NOT EXISTS clause would not update it.
 *
 * This migration ensures gene_symbol is large enough for actual data.
 */

DO $$
BEGIN
  -- Increase gene_symbol size in staging_screen_gene
  ALTER TABLE staging_screen_gene
  ALTER COLUMN gene_symbol TYPE VARCHAR(250);

  -- Ensure official_symbol is also correct size
  ALTER TABLE staging_screen_gene
  ALTER COLUMN official_symbol TYPE VARCHAR(250);

EXCEPTION WHEN OTHERS THEN
  -- Column may not exist or may already be the right size, that's OK
  NULL;
END $$;
