"""
build_coessential_matrix.py — gene x screen percentile matrix for CO-ESSENTIALITY.
================================================================================
STRING's edges are curated literature associations; this builds the complementary
DATA-DRIVEN network: two genes are linked when their CRISPR percentile profiles
across screens are correlated (same pathway / complex).  We build one dense
gene x fitness-screen matrix per organism; the app computes a gene's top
co-essential partners on demand (pairwise-complete Pearson).

Only FITNESS screens are used (the calibrated axis) and profiles are kept per
organism (no cross-species symbol mixing).  Saved as processed_data/coess_<taxid>.npz.

    python3 script/build_coessential_matrix.py
"""
import sys
import sqlite3
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

ORGANISMS = {9606: "Homo sapiens", 10090: "Mus musculus"}
# a gene must appear in enough fitness screens for its cross-screen profile to be
# reliable — low-coverage genes (rare pseudogenes etc.) produce spurious high
# correlations over a tiny overlap, so we require ~11% of the screens (floor 30).


def main():
    con = sqlite3.connect(str(paths.DB), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    for taxid, org in ORGANISMS.items():
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS _fit_screens")
        cur.execute("""CREATE TABLE _fit_screens AS
            SELECT c.screen_id AS sid FROM screen_metadata_curated c
            JOIN screen_metadata m ON m.SCREEN_ID = c.screen_id
            WHERE c.assay_domain='fitness' AND m.ORGANISM_OFFICIAL = ?""", (org,))
        cur.execute("CREATE UNIQUE INDEX ix_fit ON _fit_screens(sid)")
        screens = [r[0] for r in cur.execute("SELECT sid FROM _fit_screens ORDER BY sid")]
        if not screens:
            print(f"{org}: no fitness screens"); cur.execute("DROP TABLE _fit_screens"); continue
        sidx = {s: i for i, s in enumerate(screens)}
        print(f"{org}: {len(screens)} fitness screens", flush=True)

        gidx, genes = {}, []
        gi_l, si_l, val_l = [], [], []
        for gene, sid, pct in cur.execute(
                """SELECT h.GENE_SYMBOL, h.SCREEN_ID, h.PERCENTILE_SCORE
                   FROM harmonized_scores h JOIN _fit_screens f ON h.SCREEN_ID = f.sid
                   WHERE h.PERCENTILE_SCORE IS NOT NULL"""):
            gi = gidx.get(gene)
            if gi is None:
                gi = len(genes); gidx[gene] = gi; genes.append(gene)
            gi_l.append(gi); si_l.append(sidx[sid]); val_l.append(pct)
        cur.execute("DROP TABLE _fit_screens"); con.commit()
        print(f"{org}: {len(val_l):,} cells, {len(genes):,} genes", flush=True)

        G, S = len(genes), len(screens)
        M = np.full((G, S), np.nan, dtype=np.float32)
        M[np.asarray(gi_l), np.asarray(si_l)] = np.asarray(val_l, dtype=np.float32)
        del gi_l, si_l, val_l

        obs = (~np.isnan(M)).sum(1)
        min_req = max(30, int(0.11 * S))
        keep = obs >= min_req
        print(f"{org}: keeping {int(keep.sum()):,}/{G:,} genes (>= {min_req} screens)", flush=True)
        M = M[keep]
        genes = np.array(genes)[keep]
        lean = np.nanmean(M, axis=1).astype(np.float32)
        # impute missing with the gene's mean, centre rows, then L2-normalise:
        # the cosine of two stored rows == Pearson correlation of their profiles,
        # so a query is one fast matrix-vector product. (Dense cosine is far more
        # stable than sparse pairwise Pearson, which was dominated by noise.)
        rm = lean.reshape(-1, 1)
        X = np.where(np.isnan(M), rm, M) - rm
        nrm = np.linalg.norm(X, axis=1, keepdims=True)
        nrm[nrm == 0] = 1.0
        R = (X / nrm).astype(np.float32)
        out = paths.PROCESSED_DATA / f"coess_{taxid}.npz"
        np.savez_compressed(out, R=R, genes=genes,
                            screens=np.array([str(s) for s in screens]),
                            lean=lean, taxid=np.int64(taxid))
        print(f"{org}: saved {out.name}  shape={R.shape}  "
              f"({out.stat().st_size/1e6:.0f} MB)", flush=True)
    con.close()


if __name__ == "__main__":
    main()
