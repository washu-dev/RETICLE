"""
build_kb_coessential.py — precompute co-essentiality neighbours for the predictor.
=================================================================================
The live prediction endpoint can't read the 409MB DepMap matrix per request, so we
precompute, for every gene, its top-K co-essential partners (Pearson correlation of
CRISPR gene-effect profiles across cell lines) once, into kb_coessential. This is the
annotation-INDEPENDENT association layer validated in the backtest (orthogonal to GO).

  /opt/anaconda3/bin/python3 script/build_kb_coessential.py \
      --depmap /Volumes/aorvedahl-RETICLE/Active/data/depmap/CRISPRGeneEffect.csv \
      --db processed_data/kb.db --k 30 --min-corr 0.10
"""
import argparse
import re
import sqlite3
import numpy as np
import pandas as pd

GENE_COL = re.compile(r"\((\d+)\)\s*$")


def zscore_rows(M):
    M = M.astype(np.float32, copy=True)
    rm = np.nanmean(M, axis=1, keepdims=True)
    bad = np.isnan(M)
    M[bad] = np.broadcast_to(rm, M.shape)[bad]
    mu = M.mean(1, keepdims=True)
    sd = M.std(1, keepdims=True); sd[sd == 0] = 1
    return (M - mu) / sd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depmap", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--min-corr", type=float, default=0.10)
    args = ap.parse_args()

    print("loading DepMap matrix…", flush=True)
    df = pd.read_csv(args.depmap, index_col=0)
    keep = [c for c in df.columns if GENE_COL.search(c)]
    gids = np.array([int(GENE_COL.search(c).group(1)) for c in keep])
    Z = zscore_rows(df[keep].to_numpy(dtype=np.float32).T)          # genes × cell-lines
    n = Z.shape[1]
    print(f"  {Z.shape[0]:,} genes × {n:,} cell lines", flush=True)

    con = sqlite3.connect(args.db)
    known = {r[0] for r in con.execute("SELECT gene_id FROM kb_gene")}
    con.executescript("""
        DROP TABLE IF EXISTS kb_coessential;
        CREATE TABLE kb_coessential (
            gene_id          INTEGER NOT NULL,
            neighbor_gene_id INTEGER NOT NULL,
            corr             REAL NOT NULL,
            PRIMARY KEY (gene_id, neighbor_gene_id)
        );""")

    G = Z.shape[0]
    rows, done = [], 0
    for s in range(0, G, 1000):                                    # chunk to bound memory
        e = min(s + 1000, G)
        C = (Z[s:e] @ Z.T) / n                                     # block × all genes
        for bi in range(e - s):
            gi = s + bi
            g = int(gids[gi])
            if g not in known:
                continue
            c = C[bi].copy(); c[gi] = -2
            top = np.argpartition(c, -args.k)[-args.k:]
            for j in top:
                cv = float(c[j])
                if cv >= args.min_corr:
                    rows.append((g, int(gids[j]), round(cv, 4)))
        con.executemany("INSERT OR IGNORE INTO kb_coessential VALUES (?,?,?)", rows)
        con.commit(); done += (e - s); rows = []
        print(f"  {done:,}/{G:,} genes…", flush=True)

    con.execute("CREATE INDEX ix_coess_gene ON kb_coessential(gene_id)")
    con.commit()
    n_rows = con.execute("SELECT COUNT(*) FROM kb_coessential").fetchone()[0]
    print(f"DONE — kb_coessential: {n_rows:,} edges", flush=True)
    # spot check: RAN (5901) top co-essential partners
    r = con.execute(
        "SELECT g.symbol, e.corr FROM kb_coessential e JOIN kb_gene g ON g.gene_id=e.neighbor_gene_id "
        "WHERE e.gene_id=5901 ORDER BY e.corr DESC LIMIT 6").fetchall()
    print("  RAN top co-essential:", r, flush=True)
    con.close()


if __name__ == "__main__":
    main()
