"""
validate_complexes.py — does co-essentiality recover CORUM complexes, and does
hit-anchoring beat naive full-profile correlation?
================================================================================
Ground truth = CORUM 5.3 human protein complexes (processed_data/corum_human_v5.3.txt),
size-filtered to [MIN_SIZE, MAX_SIZE] subunits (drop dimers = no within-complex
structure, and mega-aggregates that are loose functional groupings, not biochemistry).
Metric = AUROC over all gene pairs among CORUM genes measured in the context:
same-complex pair = positive, different-complex = negative, scored by co-essentiality.

Two estimators compared head-to-head on the SAME pairs:
  OLD  — impute gene-mean, z-score, Pearson over ALL context screens (current method;
         the professor's worry: the noisy middle — genes at 49th vs 50th percentile,
         neither significant — dilutes real edges and manufactures fake ones).
  NEW  — HIT-ANCHORED Pearson: for a pair (i,j), correlate ONLY over screens where
         gene i OR gene j is a called hit (IS_HIT), then require >= MIN_ANCHOR such
         screens (support). Screens where both genes sit in the middle never vote.

Hit-anchoring is pair-specific masking, which naively is a 7.6M-pair loop. It is
computed here in one shot: a pair's anchor set is (i is hit) ∪ (j is hit), so every
masked sum expands by inclusion-exclusion into a few (genes×genes) matrix products
of the hit-masked and measured-masked score matrices. See anchored_corr().

  /opt/anaconda3/bin/python3 script/validate_complexes.py
"""
import sqlite3
import csv
import argparse
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net.db"
CORUM = "processed_data/corum_human_v5.3.txt"
rng = np.random.default_rng(0)


def load_corum(lo, hi):
    comps, names = {}, {}
    for r in csv.DictReader(open(CORUM, encoding="utf-8"), delimiter="\t"):
        gs = {g.strip() for g in (r["subunits_gene_name"] or "").split(";") if g.strip()}
        if lo <= len(gs) <= hi:
            comps[r["complex_id"]] = gs
            names[r["complex_id"]] = r["complex_name"]
    return comps, names


def context_screens(net, domain=None, mechanism=None):
    q = "SELECT screen_id FROM net_screen WHERE coverage_type='FULL'"
    a = []
    if domain: q += " AND assay_domain=?"; a.append(domain)
    if mechanism: q += " AND mechanism=?"; a.append(mechanism)
    return [r[0] for r in net.execute(q, a)]


def load_matrices(src, sids, genes):
    """Return (gene_list, P, H): P = signed percentile (genes×screens, NaN unmeasured),
    H = IS_HIT (1/0, 0 where unmeasured)."""
    ph = ",".join("?" * len(sids))
    gh = ",".join("?" * len(genes))
    df = pd.read_sql_query(
        f"SELECT GENE_SYMBOL, SCREEN_ID, PERCENTILE_SCORE, IS_HIT FROM harmonized_scores "
        f"WHERE SCREEN_ID IN ({ph}) AND GENE_SYMBOL IN ({gh}) AND PERCENTILE_SCORE IS NOT NULL",
        src, params=list(sids) + list(genes))
    P = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="PERCENTILE_SCORE")
    H = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="IS_HIT", fill_value=0)
    H = H.reindex(index=P.index, columns=P.columns, fill_value=0)
    return list(P.index), P.to_numpy(np.float32), H.to_numpy(np.float32)


def old_corr(P):
    """Naive: impute each gene's mean over context screens, z-score, Pearson over all screens."""
    rm = np.nanmean(P, 1, keepdims=True)
    A = np.where(np.isnan(P), rm, P)
    sd = A.std(1, keepdims=True); sd[sd == 0] = 1
    Z = (A - A.mean(1, keepdims=True)) / sd
    return (Z @ Z.T) / Z.shape[1]


def anchored_corr(P, H, min_anchor):
    """Hit-anchored Pearson for every pair, via inclusion-exclusion into matrix products.
    Anchor set of pair (i,j) = screens where i OR j is a hit (both measured). Returns
    (R, N): R[i,j] = corr over that pair's anchor screens (NaN if < min_anchor), N = anchor count."""
    Pz = np.nan_to_num(P, nan=0.0).astype(np.float32)     # 0 where unmeasured
    M = (~np.isnan(P)).astype(np.float32)                  # measured mask
    Hm = H.astype(np.float32)                              # hit mask (hit ⇒ measured)
    HP, MP = Hm * Pz, M * Pz
    HP2, MP2 = Hm * Pz * Pz, M * Pz * Pz
    # masked sums over the union-of-hits anchor: |A∪B| = A + B − A∩B
    SXY = HP @ MP.T + MP @ HP.T - HP @ HP.T                # Σ mask·Pi·Pj
    SX = HP @ M.T + MP @ Hm.T - HP @ Hm.T                  # Σ mask·Pi
    SY = SX.T                                              # Σ mask·Pj
    SXX = HP2 @ M.T + MP2 @ Hm.T - HP2 @ Hm.T              # Σ mask·Pi²
    SYY = SXX.T
    N = Hm @ M.T + M @ Hm.T - Hm @ Hm.T                    # anchor screen count
    num = N * SXY - SX * SY
    den = np.sqrt(np.clip((N * SXX - SX * SX) * (N * SYY - SY * SY), 0, None))
    with np.errstate(invalid="ignore", divide="ignore"):
        R = num / den
    R[(N < min_anchor) | ~np.isfinite(R)] = np.nan
    return R, N


def membership_shared(genes, gene_cplx):
    """Boolean genes×genes: do i and j share ≥1 complex."""
    cids = sorted({c for g in genes for c in gene_cplx.get(g, ())})
    idx = {c: k for k, c in enumerate(cids)}
    B = np.zeros((len(genes), len(cids)), np.float32)
    for i, g in enumerate(genes):
        for c in gene_cplx.get(g, ()):
            B[i, idx[c]] = 1
    return (B @ B.T) > 0.5


def spotlight(genes, R, gene_cplx, want):
    """Median intra-complex correlation for complexes whose name matches `want`."""
    gi = {g: i for i, g in enumerate(genes)}
    members = [g for g in genes if any(want in gene_cplx_name.get(c, "").lower()
                                       for c in gene_cplx.get(g, ()))]
    idx = [gi[g] for g in members]
    if len(idx) < 2:
        return None, 0
    sub = R[np.ix_(idx, idx)]
    iu = np.triu_indices(len(idx), 1)
    v = sub[iu]; v = v[np.isfinite(v)]
    return (float(np.median(v)) if len(v) else None), len(members)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=60)
    ap.add_argument("--min-screens", type=int, default=15, help="gene must be measured in >= this many context screens")
    ap.add_argument("--min-anchor", type=int, default=10, help="hit-anchored pair needs >= this many anchor screens")
    args = ap.parse_args()

    comps, names = load_corum(args.min_size, args.max_size)
    global gene_cplx_name; gene_cplx_name = names
    gene_cplx = {}
    for c, gs in comps.items():
        for g in gs:
            gene_cplx.setdefault(g, set()).add(c)
    print(f"CORUM {args.min_size}-{args.max_size} subunits: {len(comps):,} complexes, {len(gene_cplx):,} genes")

    src = sqlite3.connect(SRC)
    net = sqlite3.connect(NET)
    for label, kw in [("fitness", dict(domain="fitness")),
                      ("DDR·genotoxic", dict(mechanism="DDR·genotoxic"))]:
        sids = context_screens(net, **kw)
        genes, P, H = load_matrices(src, sids, list(gene_cplx))
        meas = (~np.isnan(P)).sum(1)
        keep = meas >= args.min_screens
        genes = [g for g, k in zip(genes, keep) if k]
        P, H = P[keep], H[keep]
        G = len(genes)
        hit_per_gene = H.sum(1)
        print(f"\n=== context '{label}' — {len(sids)} FULL screens; "
              f"{G:,} CORUM genes measured in ≥{args.min_screens} ===")
        if G < 3:
            # A narrow context can have FEWER screens than --min-screens, leaving no qualifying gene;
            # np.median of the resulting empty array is NaN and int(NaN) raises. Skip cleanly instead
            # of aborting the whole run and losing the contexts after this one.
            print(f"  skipped: needs >= 3 CORUM genes measured in >= {args.min_screens} screens "
                  f"(this context only has {len(sids)} screens)")
            continue
        print(f"  hit sparsity: median gene is a hit in {int(np.median(hit_per_gene))}/{len(sids)} screens "
              f"(mean {hit_per_gene.mean():.1f}) — the noisy middle is most of every profile")

        old = old_corr(P)
        new, N = anchored_corr(P, H, args.min_anchor)
        shared = membership_shared(genes, gene_cplx)

        iu = np.triu_indices(G, 1)
        lab = shared[iu].astype(np.int8)
        old_s = np.nan_to_num(old[iu], nan=0.0)
        new_s = new[iu]
        nanc = N[iu]
        sup = (nanc >= args.min_anchor) & np.isfinite(new_s)

        npos = int(lab.sum())
        print(f"  {len(lab):,} gene pairs ({npos:,} same-complex / {len(lab)-npos:,} different)")
        auc_old_all = roc_auc_score(lab, old_s)
        print(f"  OLD (naive full-profile corr), ALL pairs         : AUROC {auc_old_all:.3f}")
        # fair head-to-head on the SAME hit-anchored-supported subset
        ls, os_, ns = lab[sup], old_s[sup], new_s[sup]
        cov_pos = int(ls.sum())
        if len(np.unique(ls)) == 2:
            auc_old_sub = roc_auc_score(ls, os_)
            auc_new_sub = roc_auc_score(ls, ns)
            print(f"  hit-anchored support ≥{args.min_anchor}: {sup.sum():,} pairs kept "
                  f"({cov_pos:,} same-complex) = {100*sup.mean():.1f}% of pairs")
            print(f"  OLD on that same subset                          : AUROC {auc_old_sub:.3f}")
            print(f"  NEW (hit-anchored corr) on that subset           : AUROC {auc_new_sub:.3f}")
            print(f"  ▶ hit-anchoring lift on matched pairs: {auc_new_sub-auc_old_sub:+.3f}")
        else:
            print("  (subset degenerate — adjust min-anchor)")

        for probe in ("fanconi", "proteasome", "ribosom"):
            mo, n0 = spotlight(genes, old, gene_cplx, probe)
            mn, _ = spotlight(genes, new, gene_cplx, probe)
            if n0 >= 2 and mo is not None:
                tag = " ◀ context-specific" if probe == "fanconi" and label != "fitness" else ""
                print(f"     {probe:11s} ({n0:2d} genes): median intra-corr  OLD {mo:.2f} → NEW {mn if mn is not None else float('nan'):.2f}{tag}")
    src.close(); net.close()


if __name__ == "__main__":
    main()
