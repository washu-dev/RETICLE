"""
migrate_screen_similarity.py — move the screen-comparison feature off the local .npz onto RDS.
==============================================================================================
The web app used to load processed_data/screens_9606_fitness_full.npz (57 MB, 19,136 genes x
962 screens) into memory, run an SVD on first request, and then loop every candidate screen per
request. That made the whole feature local-file-only (it 404'd on a cloud deploy) and cost a
4.9 s cold start.

We do NOT migrate the matrix itself: it is derived from harmonized_scores, which is already on
RDS — storing it again in long form would be a third copy of ~17M rows. Instead we precompute
the thing the feature actually serves — the screen x screen correlations — which is only ~925k
rows, and serve it as an indexed lookup.

What is computed here matches the app's audited definition exactly:
  * PC1 (the pan-essentiality axis) is projected out first. Measured on this matrix it carries
    44.5% of the variance and its gene loading correlates 0.998 with each gene's mean percentile,
    so leaving it in makes ANY two human fitness screens correlate ~0.35 before biology.
  * PAIRWISE-COMPLETE Pearson (each pair uses only the genes both screens measured), computed for
    all pairs at once by mask algebra rather than a per-request Python loop.
  * pairs below --min-overlap co-measured genes are dropped as noise-dominated.

Writes two tables into the reticle schema:
  screen_similarity(screen_a, screen_b, r, overlap)   -- both directions, so one WHERE hits it
  screen_sim_meta(screen_id, author, cell_line, pmid, n_genes)

  /opt/anaconda3/bin/python3 script/migrate_screen_similarity.py
"""
import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
import app  # noqa: E402  — reuse the app's RDS credentials

NPZ = Path(__file__).resolve().parent.parent / "processed_data" / "screens_9606_fitness_full.npz"


def esc(v):
    if v is None:
        return r"\N"
    return str(v).replace("\\", r"\\").replace("\t", r"\t").replace("\n", r"\n").replace("\r", r"\r")


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

    # --- write to RDS ------------------------------------------------------------------------
    # Read credentials directly rather than via app._PG_PARAMS, which is None when AWS_DB_HOST is
    # commented out in .env (app in local-sqlite mode). This is a build script targeting RDS.
    from build_gene_fitness_lean import rds_params
    con = psycopg2.connect(**rds_params())
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS reticle.screen_similarity')
    cur.execute('DROP TABLE IF EXISTS reticle.screen_sim_meta')
    cur.execute("""CREATE TABLE reticle.screen_similarity (
        screen_a TEXT, screen_b TEXT, r DOUBLE PRECISION, overlap INTEGER)""")
    cur.execute("""CREATE TABLE reticle.screen_sim_meta (
        screen_id TEXT PRIMARY KEY, author TEXT, cell_line TEXT, pmid TEXT, n_genes INTEGER)""")
    con.commit()

    t0 = time.time()
    buf = io.StringIO(); total = 0
    for i in range(n_scr):
        js = np.where(keep[i])[0]
        for j in js:
            buf.write(f"{esc(screens[i])}\t{esc(screens[j])}\t{R[i, j]:.6f}\t{int(n[i, j])}\n")
        total += len(js)
        if buf.tell() > 40_000_000:
            buf.seek(0); cur.copy_expert(
                'COPY reticle.screen_similarity (screen_a,screen_b,r,overlap) FROM STDIN', buf)
            buf = io.StringIO()
    if buf.tell():
        buf.seek(0); cur.copy_expert(
            'COPY reticle.screen_similarity (screen_a,screen_b,r,overlap) FROM STDIN', buf)

    mb = io.StringIO()
    for i, sid in enumerate(screens):
        a, c, p, g = meta[i]
        mb.write(f"{esc(sid)}\t{esc(a)}\t{esc(c)}\t{esc(p)}\t{esc(g) if str(g).isdigit() else r'\N'}\n")
    mb.seek(0)
    cur.copy_expert('COPY reticle.screen_sim_meta (screen_id,author,cell_line,pmid,n_genes) FROM STDIN', mb)
    con.commit()

    cur.execute('CREATE INDEX ix_scrsim_a ON reticle.screen_similarity (screen_a)')
    cur.execute('CREATE INDEX ix_scrsim_a_r ON reticle.screen_similarity (screen_a, r DESC)')
    con.commit()
    cur.execute('SELECT COUNT(*) FROM reticle.screen_similarity'); n_rows = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM reticle.screen_sim_meta'); n_meta = cur.fetchone()[0]
    con.close()
    print(f"DONE — screen_similarity {n_rows:,} rows, screen_sim_meta {n_meta} rows "
          f"({time.time()-t0:.1f}s incl. indexes)", flush=True)


if __name__ == "__main__":
    main()
