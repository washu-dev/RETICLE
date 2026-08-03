"""
explore_mouse_hit_only.py — EXPLORATORY mouse co-hit network (Fisher channel).
==============================================================================
Mouse twin of compute_hit_only.py. Same Fisher/hypergeometric co-hit test, byte-for-byte
the same algorithm — only the data intake and the output DB change, so the mouse and human
Fisher tables are directly comparable:
  * selects MOUSE genome-wide FULL screens straight from reticle_master.db (they are not in
    net_screen, which is human-only), and
  * writes to the SEPARATE reticle_net_mouse.db, table hit_only_connection — mirroring the
    human layout (species → database, method → table). 1,656 gene symbols collide between
    the two species, so the physical DB split is what guarantees no cross-contamination.

Mouse-specific parameter: --min-screens 40, not the human 100 — only 87 screens exist.
KNOWN ISSUES INHERITED DELIBERATELY (documented in hit_only_algorithm.html §7, kept
identical so the two species stay comparable): p-value is the top-k sort key (should be
fold), IS_HIT is un-harmonized across screens, and the BH denominator counts ordered pairs
(~2x loose). This is a probe, not a validated deliverable.

  /opt/anaconda3/bin/python3 script/explore_mouse_hit_only.py
"""
import argparse
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import hypergeom

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net_mouse.db"      # SEPARATE db — never touches human reticle_net.db


def ensure_schema(net):
    net.execute("DROP TABLE IF EXISTS hit_only_connection")
    net.execute("""CREATE TABLE hit_only_connection (
        gene_a TEXT, gene_b TEXT,
        co_hit INTEGER, expected REAL, fold REAL,
        p_value REAL, q_value REAL, support INTEGER,
        concordance REAL, reciprocal INTEGER)""")
    net.execute("CREATE INDEX ix_hoc_a ON hit_only_connection(gene_a)")
    net.execute("CREATE INDEX ix_hoc_b ON hit_only_connection(gene_b)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lib", type=int, default=15000)
    ap.add_argument("--min-screens", type=int, default=40, help="mouse-specific: 87 screens total, so the human 100 is impossible")
    ap.add_argument("--min-cohit", type=int, default=3, help="computational prefilter: a pair with <3 co-hits can't clear BH")
    ap.add_argument("--topk", type=int, default=25)
    ap.add_argument("--fdr", type=float, default=0.05)
    args = ap.parse_args()

    # --- mouse genome-wide FULL screens, straight from the observation source ---
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
    Hd = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="IS_HIT", fill_value=0)
    Hd = Hd.reindex(index=P.index, columns=P.columns, fill_value=0)

    # NODES: measured-floor only. No hit floor — Fisher self-limits low-hit genes (a gene with
    # <3 total hits can never reach min_cohit with anyone), so the test decides, not a hand cut.
    meas = P.notna().sum(axis=1)
    P, Hd = P[meas >= args.min_screens], Hd[meas >= args.min_screens]
    genes = P.index.to_numpy()
    G = len(genes)

    Pv = P.to_numpy(np.float64)
    M = (~np.isnan(Pv)).astype(np.float64)
    H = (Hd.to_numpy(np.float64) > 0).astype(np.float64) * M
    Hneg = H * (np.nan_to_num(Pv) < 0)
    Hpos = H * (np.nan_to_num(Pv) > 0)
    print(f"  {G:,} nodes (measured >= {args.min_screens}) × {Pv.shape[1]} screens; "
          f"{int(H.sum()):,} hit cells ({100*H.sum()/M.sum():.1f}% of measured)", flush=True)

    rows, all_p, m_tested = [], [], 0
    for s in range(0, G, 1000):
        e = min(s + 1000, G)
        n = np.rint(M[s:e] @ M.T)
        a = np.rint(H[s:e] @ H.T)
        ri = np.rint(H[s:e] @ M.T)
        rj = np.rint(M[s:e] @ H.T)

        test = (a >= args.min_cohit) & (n > 0)
        for bi in range(e - s):
            test[bi, s + bi] = False
        m_tested += int(((a >= 0) & (n > 0)).sum())

        p = np.ones_like(a)
        if test.any():
            p[test] = hypergeom.sf(a[test] - 1, n[test], ri[test], rj[test])
        with np.errstate(divide="ignore", invalid="ignore"):
            exp = np.where(n > 0, ri * rj / n, 0.0)

        conc = np.rint(Hneg[s:e] @ Hneg.T + Hpos[s:e] @ Hpos.T)
        with np.errstate(divide="ignore", invalid="ignore"):
            conc_frac = np.where(a > 0, conc / a, 0.0)

        for bi in range(e - s):
            gi = s + bi
            cand = np.where(test[bi])[0]
            if len(cand) == 0:
                continue
            order = cand[np.lexsort((-a[bi, cand], p[bi, cand]))][:args.topk]
            for gj in order:
                rows.append([gi, int(gj), int(a[bi, gj]), float(exp[bi, gj]),
                             float(a[bi, gj] / exp[bi, gj]) if exp[bi, gj] > 0 else float("inf"),
                             float(p[bi, gj]), int(n[bi, gj]), float(conc_frac[bi, gj])])
            all_p.append(p[bi, cand])
        print(f"    block {e:,}/{G:,}", flush=True)

    print(f"  {m_tested:,} pairs tested; {len(rows):,} top-k candidates", flush=True)

    cand_p = np.sort(np.concatenate(all_p)) if all_p else np.array([])
    thr = 0.0
    k = np.arange(1, len(cand_p) + 1)
    ok = cand_p <= k / m_tested * args.fdr
    if ok.any():
        thr = float(cand_p[np.where(ok)[0][-1]])
    print(f"  BH threshold at FDR {args.fdr}: p <= {thr:.3e}", flush=True)

    tk = {}
    for r in rows:
        if r[5] <= thr:
            tk.setdefault(r[0], set()).add(r[1])

    net = sqlite3.connect(NET)
    ensure_schema(net)
    out = {}
    for gi, gj, a_, exp_, fold_, p_, n_, conc_ in rows:
        if p_ > thr:
            continue
        lo, hi = (gi, gj) if gi < gj else (gj, gi)
        if (lo, hi) in out:
            continue
        recip = 1 if (gj in tk.get(gi, ()) and gi in tk.get(gj, ())) else 0
        out[(lo, hi)] = (str(genes[lo]), str(genes[hi]), a_, round(exp_, 3), round(fold_, 3),
                         p_, min(1.0, p_ * m_tested / max(len(cand_p), 1)), n_, round(conc_, 3), recip)
    net.executemany("INSERT INTO hit_only_connection VALUES (?,?,?,?,?,?,?,?,?,?)", list(out.values()))
    net.commit()
    nrec = sum(v[9] for v in out.values())
    print(f"DONE — {len(out):,} co-hit edges ({nrec:,} reciprocal) in reticle_net_mouse.db at BH-FDR {args.fdr}", flush=True)

    print("\nspot-check (mouse complexes):", flush=True)
    for probe in ("Fancd2", "Fanca", "Rpl13", "Psmb5", "Sf3a2", "Pola1"):
        r = net.execute(
            "SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, co_hit, fold, concordance, reciprocal "
            "FROM hit_only_connection WHERE gene_a=? OR gene_b=? ORDER BY p_value LIMIT 6",
            (probe, probe, probe)).fetchall()
        print(f"  {probe}: " + (", ".join(f"{x[0]}({x[1]}co,{x[2]:.1f}x{'*' if x[4] else ''})" for x in r)
                                if r else "— no significant co-hit partners"), flush=True)
    net.close()


if __name__ == "__main__":
    main()
