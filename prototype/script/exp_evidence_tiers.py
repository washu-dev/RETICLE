"""
exp_evidence_tiers.py — which evidence dimensions actually separate a real edge from a coincidence?
===================================================================================================
The Network page draws every `net_edge` the same way: one line, thickness from |r|. That is the
whole visual vocabulary. But the database already holds THREE near-orthogonal statements about any
given pair, and the UI reads one of them:

  1. `strength`      channel-1 co-essentiality correlation (PC1-removed, ranks -> Spearman)
  2. `reciprocal`    channel-1 mutual-best (each gene is in the other's top-k by strength)
  3. co-hit          channel-2 Fisher significance overlap — 417,924 rows in the SAME sqlite file
                     that no request path has ever read (compute_hit_only.py). Orthogonal by
                     construction: channel 1 uses every screen, channel 2 uses ONLY the cells where
                     both genes were CALLED HITS, which is the data channel 1 dilutes away.

And one more that is free to compute from the edge list itself:

  4. neighbourhood Jaccard — |N(a) & N(b)| / |N(a) | N(b)| over channel-1 partners. Two genes in one
     complex should not merely correlate with each other, they should correlate with the SAME third
     parties. This is the cheapest "is the edge embedded in a module" test there is.

The question this settles, before any UI is drawn: do these dimensions actually stratify, by how
much, and does each one carry signal the others do not?

METRIC — CORUM same-complex precision over EVALUABLE edges. An edge is evaluable when BOTH
endpoints appear in at least one CORUM complex of size 3-30; otherwise "not in the same complex"
cannot be distinguished from "not annotated yet", and unannotated genes are exactly the population
this product exists to serve. Precision is then P(share a complex | drawn edge, both endpoints
annotated), against the baseline P(share a complex | random pair of annotated genes).

AUROC is reported alongside for the CONTINUOUS dimensions (strength, Jaccard, -log10 q), scored
over the same evaluable-edge population, because a threshold-free number cannot be gamed by where
a cut happens to fall.

    /opt/anaconda3/bin/python3 script/exp_evidence_tiers.py

RESULT (2026-08-03, human, context 'all': 109,412 drawn edges, of which 11,954 are evaluable —
both endpoints among the 1,938 CORUM-annotated genes that carry an edge. 1,353 of those 11,954
are same-complex; the baseline over annotated pairs is 0.615%):

    combination                n edges   share   precision   vs chance
    reciprocal AND co-hit          862    7.2%       46.4%         75x
    reciprocal only              1,578   13.2%       22.4%         36x
    co-hit only                  1,062    8.9%       17.7%         29x
    neither                      8,452   70.7%        4.9%          8x

A 9.5x spread, and SEVEN OUT OF TEN DRAWN EDGES sit in the bottom cell — which the UI currently
renders identically to the top cell. That is the finding: the tiering is not a refinement, it is
the difference between a 46% edge and a 5% edge being the same line.

Four decisions come out of this run:

 1. THE TIER IS THE 2x2, ordered by measured precision: T1 reciprocal+co-hit, T2 reciprocal,
    T3 co-hit, T4 neither. (Note T2 > T3: mutual-best is worth more than co-hit ALONE, though
    either alone is worth ~4x the bottom cell.)

 2. JACCARD EARNS A PLACE — it is not re-describing the 2x2. It still splits every cell on a
    median cut (T1 40.0->52.9%, T2 16.6->28.3%, T3 12.8->22.8%, T4 4.4->5.3%) and has the best
    single-dimension AUROC of the three continuous ones (0.6532 vs 0.6490 co-hit q, 0.6361 |r|).
    Used as a within-tier refinement, not as a tier boundary — a 2x2 is what a legend can carry.

 3. CONCORDANCE IS NOT A FILTER. compute_hit_only.py stored it and explicitly deferred the call
    ("decide from the data"). The data: AUROC 0.5347 among co-hit edges, and the [0.90,0.99) vs
    [0.99,1.01] bins differ by 28.5% vs 31.2% with only 23 edges below 0.90. Show it on the edge
    panel as a descriptive statistic; never gate on it.

 4. STOP KEYING EDGE THICKNESS ON |r|. It is the weakest of the four dimensions (AUROC 0.6361)
    and it is NON-MONOTONE exactly where a user looks first: decile 1 (|r| 0.322-0.720) scores
    17.3% while decile 2 (0.267-0.321) scores 20.9%. The thickest lines on the current graph are
    not the truest ones. Thickness moves to the tier; r stays on the edge panel as a number.

Do not tune thresholds against this script and then quote it as validation: it is one held-out
standard (CORUM), and CORUM is biased toward stable complexes — the conditional biology that
channel 2 exists to catch is under-represented in it, so T3's 17.7% is if anything a floor.
"""

import argparse
import csv
import sqlite3
import time
from collections import defaultdict

import numpy as np
from sklearn.metrics import roc_auc_score

NET = "processed_data/reticle_net.db"
CORUM = "processed_data/corum_human_v5.3.txt"


def norm_pair(a, b):
    """hit_only_connection stores ONE direction only (FANCA->FANCD2 exists, the reverse does not),
    so every lookup has to agree on an ordering or it silently misses half the table."""
    return (a, b) if a <= b else (b, a)


def load_corum(lo, hi):
    comps = {}
    with open(CORUM, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            gs = {g.strip() for g in (r.get("subunits_gene_name") or "").split(";") if g.strip()}
            if lo <= len(gs) <= hi:
                comps[r.get("complex_id") or len(comps)] = gs
    return comps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", default="all")
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=30)
    ap.add_argument("--db", default=NET)
    args = ap.parse_args()

    t0 = time.time()
    net = sqlite3.connect(args.db)

    edges = net.execute(
        "SELECT gene_a, gene_b, strength, reciprocal FROM net_edge "
        "WHERE context=? AND channel='coessential'", (args.context,)).fetchall()
    print(f"net_edge[{args.context}]: {len(edges):,} edges", flush=True)

    # Channel 2, whole table into memory: 417,924 rows is ~40MB of python tuples and every edge
    # needs a lookup, so one scan beats 109,412 indexed queries.
    cohit = {}
    for a, b, q, fold, conc, crec in net.execute(
            "SELECT gene_a, gene_b, q_value, fold, concordance, reciprocal FROM hit_only_connection"):
        cohit[norm_pair(a, b)] = (q, fold, conc, crec)
    print(f"hit_only_connection: {len(cohit):,} co-hit pairs", flush=True)
    net.close()

    # Channel-1 adjacency, for Jaccard. Built from the SAME edge list the UI draws, so the number
    # the user would see is the number measured here.
    adj = defaultdict(set)
    for a, b, _s, _r in edges:
        adj[a].add(b)
        adj[b].add(a)

    comps = load_corum(args.min_size, args.max_size)
    gene_cplx = defaultdict(set)
    for cid, gs in comps.items():
        for g in gs:
            gene_cplx[g].add(cid)
    annotated = set(gene_cplx) & set(adj)
    print(f"CORUM {args.min_size}-{args.max_size}: {len(comps):,} complexes, "
          f"{len(annotated):,} of their genes carry at least one drawn edge", flush=True)

    # Baseline: P(same complex | random pair of annotated genes). This is the number every
    # precision below has to beat to mean anything.
    ann = sorted(annotated)
    tot = same = 0
    for i in range(len(ann)):
        ci = gene_cplx[ann[i]]
        for j in range(i + 1, len(ann)):
            tot += 1
            if ci & gene_cplx[ann[j]]:
                same += 1
    base = same / tot
    print(f"  baseline P(same complex) = {base*100:.3f}%  ({same:,}/{tot:,} annotated pairs)\n",
          flush=True)

    # ---- score every evaluable edge on all four dimensions ------------------------------------
    rec_f, str_f, jac_f, coh_f, q_f, conc_f, lab_f = [], [], [], [], [], [], []
    n_eval = 0
    for a, b, s, r in edges:
        if a not in annotated or b not in annotated:
            continue
        n_eval += 1
        na, nb = adj[a], adj[b]
        inter = len(na & nb)
        union = len(na | nb)
        c = cohit.get(norm_pair(a, b))
        rec_f.append(int(r))
        str_f.append(float(s))
        jac_f.append(inter / union if union else 0.0)
        coh_f.append(1 if c else 0)
        # q=0 underflows in the table (min 1.7e-310); clamp so -log10 stays finite.
        q_f.append(-np.log10(max(c[0], 1e-300)) if c else 0.0)
        conc_f.append(c[2] if c else float("nan"))
        lab_f.append(bool(gene_cplx[a] & gene_cplx[b]))

    rec = np.array(rec_f, bool)
    stre = np.array(str_f)
    jac = np.array(jac_f)
    coh = np.array(coh_f, bool)
    qv = np.array(q_f)
    conc = np.array(conc_f)
    lab = np.array(lab_f, bool)
    print(f"evaluable edges (both endpoints CORUM-annotated): {n_eval:,} of {len(edges):,} "
          f"— {lab.sum():,} same-complex ({lab.mean()*100:.2f}%)\n", flush=True)

    # ---- the 2x2 that the UI would encode ------------------------------------------------------
    print("EVIDENCE COMBINATIONS  (channel 1 mutual-best x channel 2 co-hit)")
    print(f"  {'combination':34s} {'n edges':>9s} {'share':>7s} {'precision':>10s} {'vs chance':>10s}")
    cells = [("reciprocal AND co-hit", rec & coh), ("co-hit only", ~rec & coh),
             ("reciprocal only", rec & ~coh), ("neither", ~rec & ~coh)]
    rows = []
    for name, mask in cells:
        n = int(mask.sum())
        p = float(lab[mask].mean()) if n else float("nan")
        rows.append((name, n, p))
        print(f"  {name:34s} {n:9,d} {n/len(lab)*100:6.1f}% {p*100:9.1f}% {p/base:9.0f}x")
    print()

    # ---- does each dimension carry signal ALONE? -----------------------------------------------
    print("SINGLE-DIMENSION AUROC over the same evaluable edges (0.5 = worthless)")
    for name, v in (("strength |r|", np.abs(stre)), ("neighbourhood Jaccard", jac),
                    ("co-hit -log10 q", qv), ("reciprocal (binary)", rec.astype(float))):
        print(f"  {name:26s} AUROC = {roc_auc_score(lab, v):.4f}")
    print()

    # ---- does Jaccard add anything ON TOP of the 2x2? ------------------------------------------
    # The 2x2 is what a legend can show. Jaccard only earns a place in the UI if it still splits
    # within a cell — otherwise it is re-describing what reciprocal+co-hit already said.
    print("JACCARD, WITHIN each combination (median split) — does it split a cell further?")
    print(f"  {'combination':34s} {'n':>8s} {'low J':>9s} {'high J':>9s} {'lift':>7s}")
    for name, mask in cells:
        n = int(mask.sum())
        if n < 200:
            print(f"  {name:34s} {n:8,d}   (too few to split)")
            continue
        jm = np.median(jac[mask])
        hi = mask & (jac > jm)
        lo = mask & (jac <= jm)
        if hi.sum() < 50 or lo.sum() < 50:
            print(f"  {name:34s} {n:8,d}   (degenerate split at J={jm:.3f})")
            continue
        plo, phi = float(lab[lo].mean()), float(lab[hi].mean())
        print(f"  {name:34s} {n:8,d} {plo*100:8.1f}% {phi*100:8.1f}% {phi/max(plo,1e-9):6.1f}x")
    print()

    # ---- concordance: the builder stored it and explicitly declined to filter on it -------------
    print("CONCORDANCE, among co-hit edges (compute_hit_only.py stored it unfiltered, "
          "'decide from the data')")
    ch = coh & ~np.isnan(conc)
    if ch.sum() >= 200:
        for lo_, hi_ in ((0.0, 0.90), (0.90, 0.99), (0.99, 1.01)):
            m = ch & (conc >= lo_) & (conc < hi_)
            n = int(m.sum())
            if n:
                print(f"  concordance [{lo_:.2f},{hi_:.2f})  {n:8,d} edges   "
                      f"precision {lab[m].mean()*100:5.1f}%   {lab[m].mean()/base:4.0f}x")
        print(f"  AUROC of concordance alone, among co-hit edges: "
              f"{roc_auc_score(lab[ch], conc[ch]):.4f}")
    print()

    # ---- strength is the ONE dimension the UI currently encodes; is it monotone? ----------------
    print("STRENGTH DECILES (the dimension the UI already draws) — is thicker actually truer?")
    order = np.argsort(-np.abs(stre))
    dec = np.array_split(order, 10)
    for i, d in enumerate(dec):
        print(f"  decile {i+1:2d}  |r| {np.abs(stre[d]).min():.3f}-{np.abs(stre[d]).max():.3f}  "
              f"precision {lab[d].mean()*100:5.1f}%")

    print(f"\n  total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
