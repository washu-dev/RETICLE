/**
 * Add missing columns to staging tables (0009)
 *
 * The staging_screen_gene table was missing columns from the BIOGRID ORCS TSV format:
 * - official_symbol: Gene symbol from the TSV
 * - aliases: Gene aliases from the TSV
 * - organism_id: NCBI organism ID
 * - organism_official: Full organism name
 * - identifier_type: Type of identifier (ENTREZ_GENE, etc.)
 * - source: Data source (BioGRID ORCS, etc.)
 *
 * This migration adds these columns to match the actual TSV structure.
 */

DO $$
BEGIN
  -- Add columns to staging_screen_gene if they don't exist
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'official_symbol'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN official_symbol VARCHAR(100);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'aliases'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN aliases TEXT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'organism_id'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN organism_id INT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'organism_official'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN organism_official VARCHAR(100);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'identifier_type'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN identifier_type VARCHAR(50);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'source'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN source VARCHAR(100);
  END IF;

  -- Add columns for tracking source TSV file and row number
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'tsv_filename'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN tsv_filename VARCHAR(255);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'staging_screen_gene' AND column_name = 'tsv_row_number'
  ) THEN
    ALTER TABLE staging_screen_gene ADD COLUMN tsv_row_number INT;
  END IF;

END $$;
