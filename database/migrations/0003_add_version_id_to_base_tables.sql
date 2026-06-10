/**
 * Add version_id to base tables (0005)
 *
 * The versioning system requires all data tables to track which data_load_version
 * they belong to. This migration adds version_id columns to screen and gene tables
 * that were created in 0001 but missing this critical versioning column.
 */

DO $$
BEGIN
  -- Add version_id to screen table if not exists
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'screen' AND column_name = 'version_id'
  ) THEN
    ALTER TABLE screen ADD COLUMN version_id INT NOT NULL DEFAULT 1;
  END IF;

  -- Add version_id to gene table if not exists
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'gene' AND column_name = 'version_id'
  ) THEN
    ALTER TABLE gene ADD COLUMN version_id INT NOT NULL DEFAULT 1;
  END IF;
END $$;

-- Add foreign key constraints
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_name = 'screen' AND constraint_name = 'fk_screen_version'
  ) THEN
    ALTER TABLE screen
    ADD CONSTRAINT fk_screen_version
    FOREIGN KEY (version_id) REFERENCES data_load_version(version_id) ON DELETE CASCADE;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_name = 'gene' AND constraint_name = 'fk_gene_version'
  ) THEN
    ALTER TABLE gene
    ADD CONSTRAINT fk_gene_version
    FOREIGN KEY (version_id) REFERENCES data_load_version(version_id) ON DELETE CASCADE;
  END IF;
END $$;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_screen_version ON screen(version_id);
CREATE INDEX IF NOT EXISTS idx_gene_version ON gene(version_id);
