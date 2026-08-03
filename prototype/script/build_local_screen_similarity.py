"""
build_local_screen_similarity.py — the LOCAL twin of migrate_screen_similarity.py.
================================================================================
The screen-comparison feature (/api/screen_similar) reads a precomputed screen x screen
correlation table. migrate_screen_similarity.py writes that table to RDS; this writes the identical
table into the local sqlite mirror so the feature also works with AWS_DB_HOST unset (local mode).

The definition MUST stay identical to the RDS version or the same query returns different numbers
depending on which backend is serving:
  * PC1 (the pan-essentiality axis) is projected out first. It carries ~44.5% of the variance and its
    gene loading correlates ~0.998 with each gene's mean percentile, so leaving it in makes ANY two
    human fitness screens correlate ~0.35 before any biology.
  * PAIRWISE-COMPLETE Pearson (each pair uses only the genes both screens measured), computed for all
    pairs at once by mask algebra rather than a per-request Python loop.
  * pairs below --min-overlap co-measured genes are dropped as noise-dominated.

Run after build_screen_matrix.py (it reads that script's .npz):

  /opt/anaconda3/bin/python3 script/build_local_screen_similarity.py
"""
import argparse
import sqlite3
import time
from pathlib import Path

import numpy as np

import paths

NPZ = paths.PROCESSED_DATA / "screens_9606_fitness_full.npz"
DB = str(paths.DB)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-overlap", type=int, default=2000)
    args = ap.parse_args()

    z = np.load(NPZ, allow_pickle=True)
    M = z["M"].astype(np.float64)
    screens = [str(s) for s in z["screens"]]
    meta = z["meta"]
    n_genes, n_scr = M.shape
    print(f"matrix: {n_genes:,} genes x {n_scr} screens", flush=True)

    # --- project out PC1 (pan-essentiality) -------------------------------------------------
    t0 = time.time()
    mask = (~np.isnan(M)).astype(np.float64)
    mu = np.nanmean(M, axis=1, keepdims=True)
    X = np.where(np.isnan(M), mu, M)
    Xc = X - X.mean(axis=0, keepdims=True)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    var1 = S[0] ** 2 / (S ** 2).sum()
    load_corr = np.corrcoef(U[:, 0], np.nanmean(M, axis=1))[0, 1]
    Z = Xc - np.outer(U[:, 0] * S[0], Vt[0])
    print(f"  PC1 removed: {var1:.1%} of variance, gene-loading vs mean-percentile r={load_corr:.3f}"
          f"  ({time.time()-t0:.1f}s)", flush=True)

    # --- all-pairs pairwise-complete Pearson by mask algebra --------------------------------
    t0 = time.time()
    Zm = Z * mask                       # holes contribute 0 to every masked sum
    n = mask.T @ mask                   # co-measured gene count per pair
    Sx = Zm.T @ mask                    # sum of a over the pair's overlap
    Sy = Sx.T
    Sxy = Zm.T @ Zm
    Sxx = (Zm ** 2).T @ mask
    Syy = Sxx.T
    num = n * Sxy - Sx * Sy
    den = np.sqrt(np.maximum(n * Sxx - Sx ** 2, 0) * np.maximum(n * Syy - Sy ** 2, 0))
    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.where(den > 0, num / den, np.nan)
    print(f"  {n_scr}x{n_scr} correlations in {time.time()-t0:.1f}s", flush=True)

    keep = (n >= args.min_overlap) & np.isfinite(R)
    np.fill_diagonal(keep, False)
    print(f"  pairs kept (overlap >= {args.min_overlap:,}): {int(keep.sum()):,} directed", flush=True)

    # --- write to the local sqlite mirror ----------------------------------------------------
    t0 = time.time()
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS screen_similarity")
    cur.execute("DROP TABLE IF EXISTS screen_sim_meta")
    cur.execute("CREATE TABLE screen_similarity (screen_a TEXT, screen_b TEXT, r REAL, overlap INTEGER)")
    cur.execute("CREATE TABLE screen_sim_meta (screen_id TEXT PRIMARY KEY, author TEXT, "
                "cell_line TEXT, pmid TEXT, n_genes INTEGER)")

    rows, total = [], 0
    for i in range(n_scr):
        for j in np.where(keep[i])[0]:
            rows.append((screens[i], screens[j], round(float(R[i, j]), 6), int(n[i, j])))
        if len(rows) >= 200_000:
            cur.executemany("INSERT INTO screen_similarity VALUES (?,?,?,?)", rows)
            total += len(rows); rows = []
    if rows:
        cur.executemany("INSERT INTO screen_similarity VALUES (?,?,?,?)", rows)
        total += len(rows)

    mrows = []
    for i, sid in enumerate(screens):
        a, c, p, g = meta[i]
        mrows.append((sid, str(a), str(c), str(p), int(g) if str(g).isdigit() else None))
    cur.executemany("INSERT OR REPLACE INTO screen_sim_meta VALUES (?,?,?,?,?)", mrows)

    cur.execute("CREATE INDEX ix_scrsim_a ON screen_similarity (screen_a)")
    cur.execute("CREATE INDEX ix_scrsim_a_r ON screen_similarity (screen_a, r DESC)")
    con.commit()
    con.close()
    print(f"DONE — screen_similarity {total:,} rows, screen_sim_meta {len(mrows)} rows "
          f"({time.time()-t0:.1f}s incl. indexes)", flush=True)


if __name__ == "__main__":
    main()
