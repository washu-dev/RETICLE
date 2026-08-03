"""
exp_score_column.py — does the co-essentiality estimator do better on RANKS or on MAGNITUDES?
=============================================================================================
The shipped network correlates PERCENTILE_SCORE, a within-screen rank rescaled to [-1,1]. Pearson
over ranks IS Spearman, so the network is a Spearman network whether or not it says so anywhere.

That is a defensible default — 2,157 screens from different pipelines have no common scale, the
distributions are heavy-tailed, and at least one pipeline saturates (MaGeCK's permutation p-floor
piles values on a |6.5898| cap, which Pearson on raw values would read as a real cluster).

But ranks throw away MAGNITUDE, and magnitude may be exactly what separates one essential machine
from another: if ribosomal subunits sit at -3 and spliceosomal at -2 in every screen, ranks put
both "at the bottom" and the difference is gone. ROBUST_Z_SCORE — median/MAD within each screen,
already computed by harmonize_scores.py — keeps the magnitude while still standardising per screen.

So this is one controlled comparison:

    PERCENTILE_SCORE  (rank      -> effectively Spearman)      vs
    ROBUST_Z_SCORE    (median/MAD -> Pearson on robust z)

EVERYTHING ELSE IS HELD FIXED, deliberately and by construction: the same screens, the same gene
set (computed once, from measurement and hit counts, which do not depend on which score column is
read), the same impute→centre→PC1-removal→normalise pipeline copied from compute_coessential.py,
and the same CORUM pairs. Changing two things at once would make the result uninterpretable.

METRIC — AUROC over CORUM gene pairs: a pair in the same complex is a positive, a pair in two
different complexes is a negative, scored by the estimator. Threshold-free on purpose, so this
measures the ESTIMATOR rather than the edge threshold sitting on top of it. Precision@k is reported
alongside because AUROC is a global average and can hide the top of the list, which is what a user
actually sees.

    /opt/anaconda3/bin/python3 script/exp_score_column.py

RESULT (2026-07-30, pooled context: 1,375 genome-wide FULL human screens, 5,299 hit-active nodes,
1,904,176 CORUM 3-30 pairs of which 11,631 are same-complex — a 0.611% chance baseline):

    PERCENTILE_SCORE (rank / Spearman)        AUROC = 0.6764
    ROBUST_Z_SCORE   (median-MAD / Pearson)   AUROC = 0.6413      dAUROC = -0.0351

RANK WINS. The precision@k numbers disagree with each other (-1.0pp, +0.8pp, -0.8pp at k=100/500/
2000) and should not be read as evidence either way: at P@100=9% a one-point move is one pair.
AUROC over 1.9M pairs is the number to trust.

The two estimators' scores correlate only 0.275, so this was not a marginal difference within one
signal — they substantively disagree about which pairs are related, and the rank version is closer
to CORUM. The hypothesis being tested was that magnitude separates one essential machine from
another (ribosome at -3 vs spliceosome at -2, which ranks flatten to "both at the bottom"). It does
not, and three things plausibly explain why: robust-z standardises location and scale but NOT
DISTRIBUTION SHAPE, which is the actual problem when screens come from different pipelines
(continuous log2FC vs bimodal hit-caller output vs p-values); heavy tails survive robust-z, so one
gene at -20 still dominates a pair; and MAD is unstable on the coarse screens QC already flags.
DepMap can use Pearson because it has ONE pipeline and therefore one distribution shape. RETICLE
does not have that luxury.

Do not re-run this expecting a different answer without changing something upstream first — the
pan-essentiality confound that motivated it is already handled by the PC1 removal in
compute_coessential.zscore(), which took CORUM same-complex precision 42.8% -> 59.1%.
"""

import argparse
import csv
import sqlite3
import time
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net.db"
CORUM = "processed_data/corum_human_v5.3.txt"


def load_corum(lo, hi):
    """complex_id -> {genes}, size-filtered. Dimers carry no within-complex structure and
    mega-aggregates are loose functional groupings rather than biochemistry."""
    comps = {}
    for r in csv.DictReader(open(CORUM, encoding="utf-8"), delimiter="\t"):
        gs = {g.strip() for g in (r.get("subunits_gene_name") or "").split(";") if g.strip()}
        if lo <= len(gs) <= hi:
            comps[r.get("complex_id") or len(comps)] = gs
    return comps


def context_screens(net, min_lib):
    """The same gate compute_coessential.py applies for the pooled context: FULL coverage AND a
    genome-wide library. FULL is only a data-availability flag — 368 of the FULL human screens run
    focused libraries, and a rank against a few hundred hand-picked genes is not comparable to a
    rank against ~19k."""
    # No organism predicate — reticle_net.db is the human network; mouse lives in its own file.
    # Matched to compute_coessential.context_screens() so both arms see the shipped screen set.
    rows = net.execute(
        "SELECT screen_id FROM net_screen WHERE coverage_type='FULL' AND n_genes >= ?",
        (min_lib,)).fetchall()
    return [r[0] for r in rows]


def transform(A, keep_pc1=False):
    """impute gene-mean -> centre -> project out PC1 -> unit-normalise, so Z @ Z.T is the
    correlation. Copied from compute_coessential.zscore() so the comparison runs through the
    estimator that actually ships, quirks included."""
    rm = np.nanmean(A, 1, keepdims=True)
    Ai = np.where(np.isnan(A), rm, A)
    Ai = Ai - Ai.mean(1, keepdims=True)
    if not keep_pc1:
        # The pan-essentiality axis. |PC1 loading| correlates 0.888 with per-gene hit rate — PC1 IS
        # "how essential is this gene" — and removing it is what lets a real complex outrank generic
        # essential co-drop. On by default in the shipped build, so on here.
        U, S, Vt = np.linalg.svd(Ai, full_matrices=False)
        Ai = Ai - np.outer(U[:, 0] * S[0], Vt[0])
    nrm = np.linalg.norm(Ai, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    return (Ai / nrm).astype(np.float32)


def evaluate(Z, idx_of, pairs, labels, k_list=(100, 500, 2000)):
    """AUROC + precision@k over the SAME CORUM pair list for whichever estimator produced Z."""
    ii = np.fromiter((idx_of[a] for a, _ in pairs), dtype=np.int64, count=len(pairs))
    jj = np.fromiter((idx_of[b] for _, b in pairs), dtype=np.int64, count=len(pairs))
    scores = np.einsum("ij,ij->i", Z[ii], Z[jj]).astype(np.float64)
    auroc = roc_auc_score(labels, scores)
    order = np.argsort(-scores)
    prec = {k: float(labels[order[:k]].mean()) for k in k_list if k <= len(scores)}
    return auroc, prec, scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-lib", type=int, default=15000)
    ap.add_argument("--min-screens", type=int, default=15)
    ap.add_argument("--hit-min", type=int, default=5)
    ap.add_argument("--min-cov", type=float, default=0.50)
    ap.add_argument("--min-hit-rate", type=float, default=0.02)
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=30)
    ap.add_argument("--keep-pc1", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    net = sqlite3.connect(NET)
    sids = context_screens(net, args.min_lib)
    net.close()
    print(f"pooled context: {len(sids)} genome-wide FULL human screens", flush=True)

    src = sqlite3.connect(SRC)
    ph = ",".join("?" * len(sids))
    df = pd.read_sql_query(
        f"SELECT GENE_SYMBOL, SCREEN_ID, PERCENTILE_SCORE, ROBUST_Z_SCORE, IS_HIT "
        f"FROM harmonized_scores WHERE SCREEN_ID IN ({ph}) "
        f"AND PERCENTILE_SCORE IS NOT NULL AND ROBUST_Z_SCORE IS NOT NULL",
        src, params=sids)
    src.close()
    print(f"  loaded {len(df):,} observations ({time.time()-t0:.0f}s)", flush=True)

    P = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="PERCENTILE_SCORE")
    R = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="ROBUST_Z_SCORE")
    H = df.pivot_table(index="GENE_SYMBOL", columns="SCREEN_ID", values="IS_HIT", fill_value=0)
    R = R.reindex(index=P.index, columns=P.columns)
    H = H.reindex(index=P.index, columns=P.columns, fill_value=0)
    del df

    # The node gates depend on MEASUREMENT and HIT counts, never on which score column is read, so
    # both arms are scored on an identical gene set by construction rather than by coincidence.
    meas = P.notna().sum(axis=1)
    keep = meas >= args.min_screens
    P, R, H = P[keep], R[keep], H[keep]
    n_scr = P.shape[1]
    hit_counts = H.to_numpy(np.float32).sum(1)
    m = meas[keep].to_numpy()
    node = ((hit_counts >= args.hit_min) & (m >= args.min_cov * n_scr)
            & (hit_counts / np.maximum(m, 1) >= args.min_hit_rate))
    P, R = P[node], R[node]
    genes = P.index.to_numpy()
    assert (genes == R.index.to_numpy()).all(), "gene sets diverged — comparison would be invalid"
    print(f"  {len(genes):,} hit-active nodes × {n_scr} screens", flush=True)

    comps = load_corum(args.min_size, args.max_size)
    idx_of = {g: i for i, g in enumerate(genes)}
    gene_cplx = defaultdict(set)
    for cid, gs in comps.items():
        for g in gs & idx_of.keys():
            gene_cplx[g].add(cid)
    cg = sorted(gene_cplx)
    print(f"  CORUM {args.min_size}-{args.max_size}: {len(comps):,} complexes, "
          f"{len(cg):,} of their genes are nodes here", flush=True)

    pairs, labels = [], []
    for a in range(len(cg)):
        for b in range(a + 1, len(cg)):
            ga, gb = cg[a], cg[b]
            same = bool(gene_cplx[ga] & gene_cplx[gb])
            pairs.append((ga, gb))
            labels.append(same)
    labels = np.array(labels, dtype=bool)
    print(f"  {len(pairs):,} CORUM pairs — {labels.sum():,} same-complex "
          f"({labels.mean()*100:.3f}% chance baseline)\n", flush=True)

    results = {}
    for name, M in (("PERCENTILE_SCORE (rank / Spearman)", P),
                    ("ROBUST_Z_SCORE  (median-MAD / Pearson)", R)):
        t = time.time()
        Z = transform(M.to_numpy(np.float32), keep_pc1=args.keep_pc1)
        auroc, prec, scores = evaluate(Z, idx_of, pairs, labels)
        results[name] = (auroc, prec, scores)
        pstr = "  ".join(f"P@{k}={v*100:5.1f}%" for k, v in prec.items())
        print(f"  {name:42s} AUROC={auroc:.4f}   {pstr}   ({time.time()-t:.0f}s)", flush=True)
        del Z

    (n1, (a1, p1, s1)), (n2, (a2, p2, s2)) = results.items()
    print()
    print(f"  ΔAUROC (robust-z − percentile) = {a2-a1:+.4f}")
    for k in p1:
        print(f"  ΔP@{k:<5d} = {(p2[k]-p1[k])*100:+.1f} pp   "
              f"({p1[k]*100:.1f}% -> {p2[k]*100:.1f}%, chance {labels.mean()*100:.3f}%)")
    print(f"\n  score correlation between the two estimators: "
          f"{np.corrcoef(s1, s2)[0,1]:.3f}")
    print(f"  total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
