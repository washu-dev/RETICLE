"""
compute_hit_only.py — CO-HIT edges (channel 2): significance overlap, not magnitude.
====================================================================================
Channel 1 (compute_coessential.py) correlates full percentile profiles across screens.
It is strong on constitutive machines (ribosome, proteasome, spliceosome) and weak on
CONDITIONAL genes: FANCA-FANCB scores only r=0.41 over 985 screens, because ~950 of
those screens are ones where neither gene does anything, and that agreement-on-nothing
dilutes the signal.

This channel asks a different question — Aaron's: if a gene is not a called hit in a
screen, that screen has nothing to say about it. Keep ONLY the (gene, screen) cells where
IS_HIT=1, and ask whether two genes are called significant TOGETHER more often than their
individual hit rates predict. Same genome-wide screens as channel 1; only the cells change.

WHY FISHER AND NOT PEARSON — the natural move is to correlate percentiles over the co-hit
screens. TESTED, and it fails three ways; Fisher fixes all three at once:
  1. RANGE RESTRICTION. Conditioning on "is a hit" selects that gene's extreme tail, so
     the variance Pearson needs is gone: PSMB5 keeps 8% of its spread inside its own hit
     set, and r(PSMB5,PSMB4) collapses 0.667 -> 0.046. Fisher needs no variance: same pair,
     p=8.8e-250. (Conditional genes keep their spread — FANCD2 95%, TP53 154%, because
     their hits run in BOTH directions — which is exactly why Pearson looked good on them.)
  2. n=2 IS ARITHMETIC, NOT EVIDENCE. Two points always fit a line, so every 2-co-hit pair
     scores |r|=1.000 — the mathematical ceiling. 12% of all pairs have exactly 2 co-hits
     (542k in a 3,000-gene sample), so top-k would fill with r=1.0 noise that outranks
     every real edge (FANCA-FANCB at 0.994). Fisher degrades gracefully instead:
     TP53-USP28, 2 co-hits, p=0.051 — correctly not significant.
  3. NO THRESHOLD TO HAND-TUNE. Evidence volume is already inside the p-value, so the
     support floor that channel 1 needs dissolves. Only a computational prefilter remains.

WHAT THIS FIXES, AND WHAT IT DOES NOT:
  * KILLS artifact class 1 — genes with no phenotype that channel 1's broken absolute
    `hit >= 5` gate lets in, and which then form tight mutual cliques on shared technical
    noise (olfactory receptors, defensins, SPRR). They are almost never hits, so they are
    almost never CO-hits: OR51A2-OR11L1 and DEFA1-HBA1 both have ZERO co-hits, p=1.0.
  * DOES NOT KILL artifact class 2 — multi-mapping sgRNA genes (USP17L28, TBC1D3, GOLGA8*,
    NPIPA1). Their guides cut many loci, and cutting toxicity is a REAL phenotype, so they
    are genuinely co-called: USP17L28-TBC1D3 is 20.3x enriched, p=5.2e-15 — by fold, the
    strongest edge in the spot-check set. No gene-level statistic can see this; it needs
    sgRNA-to-locus mapping, which BioGRID's gene-level scores do not carry. KNOWN, UNFIXED.
  * NB fold-enrichment is biased toward rare-hit genes (small expected -> huge ratio), which
    is why artifacts top that ranking. Rank by p-value; fold is stored as a diagnostic only.

`concordance` = share of co-hits where both genes moved the SAME way (both deleterious or
both advantageous). A hit is directionless in IS_HIT, but two genes in one complex should
fail together, not oppositely. Stored, not filtered on — decide from the data.

  /opt/anaconda3/bin/python3 script/compute_hit_only.py
"""
import argparse
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import hypergeom

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net.db"


def ensure_schema(net):
    net.execute("DROP TABLE IF EXISTS hit_only_connection")
    net.execute("""CREATE TABLE hit_only_connection (
        gene_a TEXT, gene_b TEXT,
        co_hit INTEGER,       -- screens where BOTH were called hits
        expected REAL,        -- co-hits expected from the two hit rates alone
        fold REAL,            -- co_hit / expected (diagnostic; biased toward rare-hit genes)
        p_value REAL,         -- one-sided Fisher exact (hypergeometric) for enrichment
        q_value REAL,         -- Benjamini-Hochberg FDR over every pair tested
        support INTEGER,      -- screens where both were MEASURED (the Fisher population)
        concordance REAL,     -- share of co-hits with the same sign (both down / both up)
        reciprocal INTEGER)   -- 1 = each gene is in the other's top-k by p-value
    """)
    net.execute("CREATE INDEX ix_hoc_a ON hit_only_connection(gene_a)")
    net.execute("CREATE INDEX ix_hoc_b ON hit_only_connection(gene_b)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lib", type=int, default=15000, help="genome-wide gate: library scores >= this many genes")
    ap.add_argument("--min-screens", type=int, default=100, help="gene measured in >= this many screens (marginals need a stable base)")
    ap.add_argument("--min-cohit", type=int, default=3, help="COMPUTATIONAL prefilter only: with ~10^8 tests a pair with <3 co-hits cannot reach the BH cutoff (a=2 tops out near p~1e-7), so testing them only costs time")
    ap.add_argument("--topk", type=int, default=25)
    ap.add_argument("--fdr", type=float, default=0.05)
    args = ap.parse_args()

    net = sqlite3.connect(NET)
    sids = [r[0] for r in net.execute(
        "SELECT screen_id FROM net_screen WHERE coverage_type='FULL' AND n_genes >= ?", (args.min_lib,))]
    print(f"{len(sids)} genome-wide FULL screens (library >= {args.min_lib:,} genes)", flush=True)

    src = sqlite3.connect(SRC)
    ph = ",".join("?" * len(sids))
    df = pd.read_sql_query(
        f"SELECT GENE_SYMBOL, SCREEN_ID, PERCENTILE_SCORE, IS_HIT FROM harmonized_scores "
        f"WHERE SCREEN_ID IN ({ph}) AND PERCENTILE_SCORE IS NOT NULL", src, params=sids)
    src.close()
    print(f"  loaded {len(df):,} observations", flush=True)

    P = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="PERCENTILE_SCORE")
    Hd = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="IS_HIT", fill_value=0)
    Hd = Hd.reindex(index=P.index, columns=P.columns, fill_value=0)

    # NODES: measured-floor only. No hit floor — per the channel's own logic a gene with few
    # hits is self-limiting (it can't accumulate co-hits), so Fisher decides, not a hand cut.
    meas = P.notna().sum(axis=1)
    P, Hd = P[meas >= args.min_screens], Hd[meas >= args.min_screens]
    genes = P.index.to_numpy()
    G = len(genes)

    Pv = P.to_numpy(np.float64)
    M = (~np.isnan(Pv)).astype(np.float64)                 # measured mask
    H = (Hd.to_numpy(np.float64) > 0).astype(np.float64) * M   # hit AND measured
    Hneg = H * (np.nan_to_num(Pv) < 0)                     # deleterious hit
    Hpos = H * (np.nan_to_num(Pv) > 0)                     # advantageous hit
    print(f"  {G:,} nodes (measured >= {args.min_screens}) × {Pv.shape[1]} screens; "
          f"{int(H.sum()):,} hit cells ({100*H.sum()/M.sum():.1f}% of measured)", flush=True)

    rows, all_p, m_tested = [], [], 0
    for s in range(0, G, 1000):
        e = min(s + 1000, G)
        # 2x2 marginals by mask algebra; rint because float matmul drifts off integers and
        # hypergeom silently returns NaN on non-integer args (cost me two NaNs in validation)
        n = np.rint(M[s:e] @ M.T)                          # co-measured  (Fisher population)
        a = np.rint(H[s:e] @ H.T)                          # co-hit       (observed overlap)
        ri = np.rint(H[s:e] @ M.T)                         # i's hits among j's measured screens
        rj = np.rint(M[s:e] @ H.T)                         # j's hits among i's measured screens

        test = (a >= args.min_cohit) & (n > 0)
        for bi in range(e - s):
            test[bi, s + bi] = False                       # never test a gene against itself
        m_tested += int(((a >= 0) & (n > 0)).sum())

        p = np.ones_like(a)
        if test.any():
            p[test] = hypergeom.sf(a[test] - 1, n[test], ri[test], rj[test])
        with np.errstate(divide="ignore", invalid="ignore"):
            exp = np.where(n > 0, ri * rj / n, 0.0)

        conc = np.rint(Hneg[s:e] @ Hneg.T + Hpos[s:e] @ Hpos.T)
        with np.errstate(divide="ignore", invalid="ignore"):
            conc_frac = np.where(a > 0, conc / a, 0.0)

        # each gene keeps its top-k partners by p-value (ties broken by more co-hits)
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

    # Benjamini-Hochberg over EVERY pair tested (not just the top-k we kept), so the
    # threshold reflects the real search space.
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
    print(f"DONE — {len(out):,} co-hit edges ({nrec:,} reciprocal) at BH-FDR {args.fdr}", flush=True)

    for probe in ("FANCD2", "FANCA", "RPL13", "PSMB5", "TP53", "OR51A2", "USP17L28"):
        r = net.execute(
            "SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, co_hit, fold, p_value, concordance, reciprocal "
            "FROM hit_only_connection WHERE gene_a=? OR gene_b=? ORDER BY p_value LIMIT 6",
            (probe, probe, probe)).fetchall()
        print(f"  {probe}: " + (", ".join(f"{x[0]}({x[1]}co,{x[2]:.1f}x{'*' if x[5] else ''})" for x in r)
                                if r else "— no significant co-hit partners"), flush=True)
    net.close()


if __name__ == "__main__":
    main()
