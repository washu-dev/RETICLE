/**
 * 0017 — dim_gene_paralog (D5b prerequisite: buffering-candidate criterion (b))
 *
 * The novelty/mechanistic-divergence channel's buffering-candidate flag
 * (design/gene_relatedness_design.md §6.6) needs "paralogs/homologs per an
 * external homology source." That source already sits, unused, in the STRING
 * alias files this pipeline's prototype KB build already reads
 * (prototype/script/build_kb_string.py): the `Ensembl_EntrezGene_Paralog`
 * source row on a protein's alias maps it directly to its paralog's Entrez
 * GeneID. build_kb_string.py deliberately discards those rows (wrong join key
 * for its own STRING-edge purpose) — this table is the first consumer of them.
 *
 * Populated by scripts/populate_gene_paralogs.py, warehouse-native (no SQLite
 * kb.db dependency). Keyed by version_id like every other dim table here, even
 * though paralogy itself doesn't change per BioGRID load — this keeps the
 * refresh/cascade semantics identical to the rest of the subsystem.
 */

CREATE TABLE IF NOT EXISTS dim_gene_paralog (
    dim_gene_paralog_id SERIAL PRIMARY KEY,
    version_id      INT NOT NULL REFERENCES data_load_version(version_id) ON DELETE CASCADE,
    run_id          INT REFERENCES etl_pipeline_run(run_id) ON DELETE CASCADE,
    gene_id_a       INT NOT NULL,
    gene_id_b       INT NOT NULL,
    organism        VARCHAR(50) NOT NULL,
    source          VARCHAR(50) NOT NULL DEFAULT 'string_ensembl_paralog',
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_gene_paralog_order CHECK (gene_id_a < gene_id_b),
    UNIQUE (version_id, gene_id_a, gene_id_b)
);

CREATE INDEX IF NOT EXISTS idx_dim_gene_paralog_version ON dim_gene_paralog(version_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_gene_paralog_a ON dim_gene_paralog(version_id, gene_id_a);
CREATE INDEX IF NOT EXISTS idx_dim_gene_paralog_b ON dim_gene_paralog(version_id, gene_id_b);
