"""
build_screen_matrix.py — gene x screen RAW percentile matrix for the
SCREEN-vs-SCREEN comparison feature.
====================================================================
Scope (per the PI + the coverage discussion): Homo sapiens, assay_domain=fitness
(proliferation/viability), COVERAGE_TYPE=FULL (genome-wide, not hit-only) only —
the clean apples-to-apples pool.

Unlike coess_*.npz (which stores a normalised matrix for gene-gene cosine and
mixes in hit-only screens), this keeps the RAW percentile per gene per screen so
we can compute a WEIGHTED screen-screen correlation on demand (weight = both
screens' extremeness) and draw the gene scatter.

Saved as processed_data/screens_9606_fitness_full.npz:
  M       float32 [genes x screens]  RAW percentile, NaN where a gene is unmeasured
  genes   str[genes]
  screens str[screens]                 (BioGRID screen ids)
  meta    str[screens x 4]             (author, cell_line, pmid, n_genes) for labels

    python3 script/build_screen_matrix.py
"""
import sys
import sqlite3
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

TAXID = 9606
ORG = "Homo sapiens"
MIN_GENES_PER_SCREEN = 500       # a genome-wide screen worth comparing
MIN_SCREENS_PER_GENE = 50        # a gene must appear widely enough to matter


def main():
    con = sqlite3.connect(str(paths.DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS _cmp_screens")
    cur.execute("""
        CREATE TABLE _cmp_screens AS
        SELECT m.SCREEN_ID AS sid, m.AUTHOR AS author, m.CELL_LINE AS cell_line,
               c.pmid AS pmid
        FROM screen_metadata m
        JOIN screen_metadata_curated c ON m.SCREEN_ID = c.screen_id
        WHERE m.ORGANISM_OFFICIAL = ? AND c.assay_domain = 'fitness'
          AND m.COVERAGE_TYPE = 'FULL'""", (ORG,))
    cur.execute("CREATE UNIQUE INDEX ix_cmp ON _cmp_screens(sid)")
    meta_rows = {r[0]: r for r in cur.execute(
        "SELECT sid, author, cell_line, pmid FROM _cmp_screens")}
    print(f"{ORG} fitness FULL screens: {len(meta_rows)}", flush=True)

    # stream percentile cells for those screens (indexed join)
    gidx, genes, sidx, screens = {}, [], {}, []
    gi_l, si_l, val_l = [], [], []
    for gene, sid, pct in cur.execute(
            """SELECT h.GENE_SYMBOL, h.SCREEN_ID, h.PERCENTILE_SCORE
               FROM harmonized_scores h JOIN _cmp_screens s ON h.SCREEN_ID = s.sid
               WHERE h.PERCENTILE_SCORE IS NOT NULL"""):
        gi = gidx.get(gene)
        if gi is None:
            gi = len(genes); gidx[gene] = gi; genes.append(gene)
        sj = sidx.get(sid)
        if sj is None:
            sj = len(screens); sidx[sid] = sj; screens.append(sid)
        gi_l.append(gi); si_l.append(sj); val_l.append(pct)
    cur.execute("DROP TABLE _cmp_screens"); con.commit(); con.close()
    print(f"cells={len(val_l):,}  genes={len(genes):,}  screens={len(screens):,}", flush=True)

    G, S = len(genes), len(screens)
    M = np.full((G, S), np.nan, dtype=np.float32)
    M[np.asarray(gi_l), np.asarray(si_l)] = np.asarray(val_l, dtype=np.float32)

    # drop under-covered screens (columns) and rare genes (rows)
    scr_obs = (~np.isnan(M)).sum(0)
    keep_s = scr_obs >= MIN_GENES_PER_SCREEN
    M = M[:, keep_s]; screens = [s for s, k in zip(screens, keep_s) if k]
    gene_obs = (~np.isnan(M)).sum(1)
    keep_g = gene_obs >= MIN_SCREENS_PER_GENE
    M = M[keep_g]; genes = np.array(genes)[keep_g]
    print(f"after coverage filter: {M.shape[0]:,} genes x {M.shape[1]:,} screens", flush=True)

    meta = np.array([[str(meta_rows[s][1] or ""), str(meta_rows[s][2] or ""),
                      str(meta_rows[s][3] or ""), str(int((~np.isnan(M[:, j])).sum()))]
                     for j, s in enumerate(screens)], dtype=object)

    out = paths.PROCESSED_DATA / f"screens_{TAXID}_fitness_full.npz"
    np.savez_compressed(out, M=M, genes=genes,
                        screens=np.array([str(s) for s in screens]),
                        meta=meta, taxid=np.int64(TAXID))
    print(f"saved {out.name}  ({out.stat().st_size/1e6:.0f} MB)", flush=True)


if __name__ == "__main__":
    main()
