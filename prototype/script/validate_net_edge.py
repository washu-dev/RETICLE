"""
validate_net_edge.py — does the SHIPPED network recover CORUM complexes?
=======================================================================
validate_complexes.py compares two candidate ESTIMATORS (naive full-profile vs hit-anchored) over
raw matrices. It does NOT evaluate what the product actually serves: the `net_edge` table produced by
compute_coessential.py, i.e. after PC1 removal, the node gates, top-k selection and the shuffle-null
threshold. Every one of those steps changes which edges exist, so an estimator-level AUROC cannot tell
you whether the deployed graph is good.

This script measures the emitted edge set directly, against CORUM 5.3 as ground truth:

  precision   = of the shipped edges whose BOTH endpoints are CORUM-annotated, the fraction that are
                same-complex. This is the number a user experiences: "when the graph shows me a
                partner, how often is it a genuine complex-mate?"
  baseline    = the same fraction among random pairs drawn from the same CORUM gene pool, which is
                what precision would be with no signal. The ratio precision/baseline is the
                enrichment (how many times better than chance).
  reciprocal  = the same precision restricted to mutual-best edges, the sparse view the UI defaults
                to — it should be materially cleaner than the union view.

Only edges whose BOTH endpoints are CORUM genes are scored: an edge to a gene CORUM has never
annotated is neither right nor wrong, and counting it as wrong would just penalise coverage.

  /opt/anaconda3/bin/python3 script/validate_net_edge.py
  /opt/anaconda3/bin/python3 script/validate_net_edge.py --organism mouse
"""
import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

import paths

CORUM = paths.PROCESSED_DATA / "corum_human_v5.3.txt"


def load_corum(min_size=3, max_size=60):
    """gene symbol -> set of complex ids, size-filtered the same way validate_complexes.py does."""
    gene_cplx = defaultdict(set)
    members = defaultdict(set)
    with open(CORUM, encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        try:
            i_id = header.index("complex_id")
        except ValueError:
            i_id = 0
        i_sub = next((i for i, h in enumerate(header) if "subunits_gene_name" in h), None)
        if i_sub is None:
            raise SystemExit(f"cannot find a subunits_gene_name column in {CORUM.name}: {header[:12]}")
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) <= max(i_id, i_sub):
                continue
            cid = f[i_id]
            genes = {g.strip().upper() for g in f[i_sub].replace(",", ";").split(";") if g.strip()}
            if min_size <= len(genes) <= max_size:
                members[cid] = genes
    for cid, genes in members.items():
        for g in genes:
            gene_cplx[g].add(cid)
    return gene_cplx, members


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--organism", choices=["human", "mouse"], default="human")
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=60)
    ap.add_argument("--n-random", type=int, default=2_000_000, help="random pairs for the chance baseline")
    args = ap.parse_args()

    db = paths.PROCESSED_DATA / ("reticle_net_mouse.db" if args.organism == "mouse" else "reticle_net.db")
    context = "mouse" if args.organism == "mouse" else "all"

    gene_cplx, members = load_corum(args.min_size, args.max_size)
    print(f"CORUM {args.min_size}-{args.max_size} subunits: {len(members):,} complexes, "
          f"{len(gene_cplx):,} genes")

    con = sqlite3.connect(db)
    edges = con.execute(
        "SELECT gene_a, gene_b, strength, reciprocal FROM net_edge "
        "WHERE context=? AND channel='coessential'", (context,)).fetchall()
    con.close()
    print(f"shipped edges in '{context}': {len(edges):,}")

    # Only pairs where BOTH endpoints are CORUM-annotated are scorable.
    scored = [(a, b, s, r) for a, b, s, r in edges
              if a.upper() in gene_cplx and b.upper() in gene_cplx]
    if not scored:
        raise SystemExit("no shipped edge has both endpoints in CORUM — nothing to score")

    def same(a, b):
        return bool(gene_cplx[a.upper()] & gene_cplx[b.upper()])

    hits = [same(a, b) for a, b, _, _ in scored]
    prec = float(np.mean(hits))

    recip = [(a, b) for a, b, _, r in scored if r]
    prec_recip = float(np.mean([same(a, b) for a, b in recip])) if recip else float("nan")
    union_only = [(a, b) for a, b, _, r in scored if not r]
    prec_union = float(np.mean([same(a, b) for a, b in union_only])) if union_only else float("nan")

    # Chance baseline: random pairs from the CORUM genes that actually appear in the network, so the
    # comparison is against this graph's own gene pool rather than all of CORUM.
    pool = sorted({g for a, b, _, _ in scored for g in (a.upper(), b.upper())})
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(pool), size=(args.n_random, 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    base = float(np.mean([bool(gene_cplx[pool[i]] & gene_cplx[pool[j]]) for i, j in idx]))

    print(f"CORUM-scorable edges: {len(scored):,} of {len(edges):,} "
          f"({100*len(scored)/len(edges):.1f}%);  gene pool {len(pool):,}")
    print()
    print(f"  same-complex precision, ALL shipped edges   : {prec:.4f}  ({sum(hits):,}/{len(scored):,})")
    print(f"  same-complex precision, reciprocal only     : {prec_recip:.4f}  ({len(recip):,} edges)")
    print(f"  same-complex precision, union-only          : {prec_union:.4f}  ({len(union_only):,} edges)")
    print(f"  chance baseline (random pairs, same pool)   : {base:.4f}")
    if base > 0:
        print(f"  ENRICHMENT over chance                      : {prec/base:.1f}x"
              f"   (reciprocal {prec_recip/base:.1f}x)")

    # Does edge strength track truth? If the shipped strength is meaningful, precision should rise
    # monotonically with it.
    print()
    print("  precision by strength decile (does r rank truth?):")
    s = np.array([x[2] for x in scored], dtype=float)
    h = np.array(hits, dtype=bool)
    order = np.argsort(-s)
    for k in range(10):
        lo, hi = int(k * len(order) / 10), int((k + 1) * len(order) / 10)
        sl = order[lo:hi]
        if len(sl) == 0:
            continue
        print(f"      decile {k+1:2d}  r {s[sl].min():.3f}-{s[sl].max():.3f}   "
              f"precision {h[sl].mean():.4f}  (n={len(sl):,})")


if __name__ == "__main__":
    main()
