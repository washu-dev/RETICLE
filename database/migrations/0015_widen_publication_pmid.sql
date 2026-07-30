/**
 * 0015 — widen publication.pmid VARCHAR(20) -> VARCHAR(100)
 *
 * BioGRID ORCS screen metadata SOURCE_ID is usually a numeric PubMed ID, but
 * non-PubMed-sourced screens (bioRxiv / other) carry a DOI, which exceeds 20
 * chars. P2 (populate_publications.py) keys publication on that source id, so the
 * column must hold a DOI without truncation (truncation would collide distinct
 * publications and corrupt co-citation). Idempotent.
 */

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'publication' AND column_name = 'pmid'
          AND character_maximum_length IS NOT NULL
          AND character_maximum_length < 100
    ) THEN
        ALTER TABLE publication ALTER COLUMN pmid TYPE VARCHAR(100);
    END IF;
END $$;
