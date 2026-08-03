"""
explore_mouse_coessential.py — EXPLORATORY mouse co-essentiality network (channel 1).
=====================================================================================
Not production. A throwaway probe to answer one question: with only ~87 genome-wide
mouse screens (vs 1,377 human), what does the Pearson co-essentiality channel actually
recover? Reuses the exact, already-validated algorithm from compute_coessential.py
(impute-then-correlate + reciprocal-rank + within-screen-shuffle-null threshold), but:
  * selects MOUSE screens straight from reticle_master.db (they are not in net_screen,
    which is human-only by design), and
  * writes to a SEPARATE database, reticle_net_mouse.db, so there is ZERO chance of a
    human/mouse mix — the two namespaces share 1,656 identical gene symbols, so pooling
    them in one table would silently splice unrelated profiles.

Parameter that HAD to change for the small corpus: --min-screens is 40, not the human
100 — with only 87 screens total, no gene can be measured >100 times, so the human floor
would empty the graph. Everything else is inherited unchanged, deliberately, so any
weakness we see is the DATA (87 screens), not a re-tuned pipeline.

  /opt/anaconda3/bin/python3 script/explore_mouse_coessential.py
"""
import argparse
import sqlite3
import numpy as np
import pandas as pd

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net_mouse.db"     # SEPARATE db — never touches human reticle_net.db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lib", type=int, default=15000)
    ap.add_argument("--min-screens", type=int, default=40, help="mouse-specific: 87 screens total, so the human 100 is impossible")
    ap.add_argument("--min-support", type=int, default=20)
    ap.add_argument("--min-corr", type=float, default=0.15)
    ap.add_argument("--topk", type=int, default=25)
    ap.add_argument("--hit-min", type=int, default=5)
    ap.add_argument("--fdr", type=float, default=0.05)
    args = ap.parse_args()
    rng = np.random.default_rng(0)                       # fixed seed → reproducible null

    # --- select mouse genome-wide FULL screens directly from the observation source ---
    src = sqlite3.connect(SRC)
    sids = [r[0] for r in src.execute("""
        SELECT h.SCREEN_ID FROM harmonized_scores h
        JOIN screen_metadata m ON m.SCREEN_ID = h.SCREEN_ID
        WHERE m.ORGANISM_OFFICIAL='Mus musculus' AND m.COVERAGE_TYPE='FULL'
          AND h.PERCENTILE_SCORE IS NOT NULL
        GROUP BY h.SCREEN_ID HAVING COUNT(*) >= ?""", (args.min_lib,))]
    print(f"mouse genome-wide FULL screens (library >= {args.min_lib:,}): {len(sids)}", flush=True)
    if len(sids) < 5:
        raise SystemExit("too few mouse screens")

    ph = ",".join("?" * len(sids))
    df = pd.read_sql_query(
        f"SELECT GENE_SYMBOL, SCREEN_ID, PERCENTILE_SCORE, IS_HIT FROM harmonized_scores "
        f"WHERE SCREEN_ID IN ({ph}) AND PERCENTILE_SCORE IS NOT NULL", src, params=sids)
    src.close()
    print(f"  loaded {len(df):,} observations", flush=True)

    P = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="PERCENTILE_SCORE")
    H = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="IS_HIT", fill_value=0)
    meas = P.notna().sum(axis=1)
    P = P[meas >= args.min_screens]
    H = H.reindex(index=P.index, columns=P.columns, fill_value=0)
    hit_counts = H.to_numpy(np.float32).sum(1)

    # report known complex genes dropped by the hit floor — the small-corpus casualty
    probe_all = ["Rpl13", "Rps19", "Psmb5", "Psma5", "Sf3a2", "Sf3b3", "Fancd2", "Fanca", "Pola1", "Pole"]
    hc = dict(zip(P.index.to_numpy(), hit_counts))
    dropped = [(g, int(hc.get(g, -1))) for g in probe_all if hc.get(g, 0) < args.hit_min]
    if dropped:
        print(f"  known genes dropped by hit>={args.hit_min}: " +
              ", ".join(f"{g}(hit={h if h>=0 else 'unmeasured'})" for g, h in dropped), flush=True)

    node = hit_counts >= args.hit_min
    P = P[node]
    genes = P.index.to_numpy()
    A = P.to_numpy(np.float32)
    Bm = (~np.isnan(A)).astype(np.float32)
    G = len(genes)
    print(f"  {G:,} hit-active nodes (of {len(node):,} measured) × {A.shape[1]} screens", flush=True)

    def zscore(mat):
        rm = np.nanmean(mat, 1, keepdims=True)
        Ai = np.where(np.isnan(mat), rm, mat)
        Ai = Ai - Ai.mean(1, keepdims=True)
        nrm = np.linalg.norm(Ai, axis=1, keepdims=True); nrm[nrm == 0] = 1
        return (Ai / nrm).astype(np.float32)

    def topk_edges(Z):
        tk = {}
        for s in range(0, G, 2000):
            e = min(s + 2000, G)
            C = Z[s:e] @ Z.T
            supp = Bm[s:e] @ Bm.T
            for bi in range(e - s):
                gi = s + bi
                c = C[bi].copy(); c[gi] = -np.inf
                c[supp[bi] < args.min_support] = -np.inf
                top = np.argpartition(-c, args.topk)[:args.topk]
                tk[gi] = {int(j): (float(C[bi, j]), int(supp[bi, j]))
                          for j in top if C[bi, j] >= args.min_corr and np.isfinite(c[j])}
        return tk

    def reciprocal_corrs(tk):
        seen, out = set(), []
        for gi, d in tk.items():
            for gj, (corr, _) in d.items():
                a, b = (gi, gj) if gi < gj else (gj, gi)
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                if gi in tk.get(gj, ()):
                    out.append(corr)
        return np.array(out)

    tk_real = topk_edges(zscore(A)); print("    real top-k done", flush=True)
    An = A.copy()
    for cidx in range(An.shape[1]):
        col = An[:, cidx]; m = ~np.isnan(col)
        v = col[m].copy(); rng.shuffle(v); col[m] = v; An[:, cidx] = col
    tk_null = topk_edges(zscore(An)); print("    null top-k done", flush=True)

    rr, rn = reciprocal_corrs(tk_real), reciprocal_corrs(tk_null)
    thr = 0.90
    for t in np.arange(args.min_corr, 0.90, 0.005):
        nreal = int((rr >= t).sum()); nnull = int((rn >= t).sum())
        if nreal >= 1 and nnull / nreal <= args.fdr:
            thr = round(float(t), 3); break
    nrf, nnf = int((rr >= thr).sum()), int((rn >= thr).sum())
    print(f"    threshold: r >= {thr:.3f}  (reciprocal-edge FDR {100*nnf/max(nrf,1):.1f}% vs shuffle null; "
          f"noise floor lifted the {args.min_corr} floor by {thr-args.min_corr:+.3f})", flush=True)

    # --- write to the SEPARATE mouse db ---
    net = sqlite3.connect(NET)
    net.execute("DROP TABLE IF EXISTS net_edge")
    net.execute("""CREATE TABLE net_edge (
        gene_a TEXT, gene_b TEXT, context TEXT, channel TEXT,
        strength REAL, support INTEGER, reciprocal INTEGER)""")
    out = {}
    for gi, d in tk_real.items():
        for gj, (corr, sup) in d.items():
            if corr < thr:
                continue
            a, b = (gi, gj) if gi < gj else (gj, gi)
            if (a, b) in out:
                continue
            recip = 1 if gi in tk_real.get(gj, ()) else 0
            out[(a, b)] = (str(genes[a]), str(genes[b]), "mouse", "coessential",
                           round(corr, 4), sup, recip)
    rows = list(out.values())
    net.executemany("INSERT INTO net_edge VALUES (?,?,?,?,?,?,?)", rows)
    net.commit()
    nrec = sum(r[6] for r in rows)
    print(f"DONE — {len(rows):,} edges ({nrec:,} reciprocal) in reticle_net_mouse.db at r>={thr:.3f}", flush=True)

    # --- spot-check known mouse complexes (reciprocal marked *) ---
    print("\nspot-check (mouse complexes):", flush=True)
    for probe in ("Rpl13", "Psmb5", "Sf3a2", "Pola1", "Fancd2"):
        r = net.execute(
            "SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength, reciprocal "
            "FROM net_edge WHERE (gene_a=? OR gene_b=?) ORDER BY strength DESC LIMIT 6",
            (probe, probe, probe)).fetchall()
        if r:
            print(f"  {probe}: " + ", ".join(f"{x[0]}({x[1]}{'*' if x[2] else ''})" for x in r), flush=True)
        else:
            drop_h = int(hc.get(probe, -1))
            why = f"hit={drop_h}<{args.hit_min}" if 0 <= drop_h < args.hit_min else "no surviving edges"
            print(f"  {probe}: — not in graph ({why})", flush=True)
    net.close()


if __name__ == "__main__":
    main()
