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
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

import paths

CORUM = paths.PROCESSED_DATA / "corum_human_v5.3.txt"


def load_corum(min_size=3, max_size=60):
    """gene symbol -> set of complex ids, size-filtered the same way validate_complexes.py does.

    Parsed with the csv module, not `line.split("\t")`. CORUM's TSV quotes fields that contain
    tabs and newlines, so splitting by hand tears rows apart mid-record and shifts the remainder
    into the wrong columns. The damage was quiet and one-directional: the naive parse admitted 210
    "gene symbols" that were actually numeric ids leaking from another column (101600, 10801849,
    ...), lost 134 real symbols, and collapsed 2,626 complexes to 2,445 — because a torn row can
    repeat a complex_id and `members[cid] = genes` overwrites instead of accumulating.

    Every precision figure this script has ever printed was therefore scored against a slightly
    corrupted ground truth. The direction of every comparison held up when re-scored, but a
    validator quietly grading against junk is exactly the failure that survives longest.
    """
    gene_cplx = defaultdict(set)
    members = defaultdict(set)
    with open(CORUM, encoding="utf-8", errors="replace", newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        sub_col = next((c for c in (rd.fieldnames or []) if "subunits_gene_name" in c), None)
        if sub_col is None:
            raise SystemExit(f"cannot find a subunits_gene_name column in {CORUM.name}: "
                             f"{(rd.fieldnames or [])[:12]}")
        id_col = "complex_id" if "complex_id" in (rd.fieldnames or []) else (rd.fieldnames or [""])[0]
        for r in rd:
            genes = {g.strip().upper()
                     for g in (r.get(sub_col) or "").replace(",", ";").split(";") if g.strip()}
            if min_size <= len(genes) <= max_size:
                members[r[id_col]] |= genes
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
    ap.add_argument("--context", help="net_edge context to score (default: the pooled production one). "
                                      "Use e.g. domain:fitness to score a per-domain layer — precision "
                                      "is only interpretable next to the coverage printed below it, "
                                      "since a smaller context buys precision by shipping fewer edges.")
    args = ap.parse_args()

    db = paths.PROCESSED_DATA / ("reticle_net_mouse.db" if args.organism == "mouse" else "reticle_net.db")
    context = args.context or ("mouse" if args.organism == "mouse" else "all")

    gene_cplx, members = load_corum(args.min_size, args.max_size)
    print(f"CORUM {args.min_size}-{args.max_size} subunits: {len(members):,} complexes, "
          f"{len(gene_cplx):,} genes")

    con = sqlite3.connect(db)
    edges = con.execute(
        "SELECT gene_a, gene_b, strength, reciprocal FROM net_edge "
        "WHERE context=? AND channel='coessential'", (context,)).fetchall()
    con.close()
    if not edges:
        raise SystemExit(f"no edges in context '{context}' — build it first")
    # Coverage, printed before precision on purpose. A context built from fewer screens can post a
    # better precision simply by emitting fewer, safer edges; the two numbers only mean something
    # together.
    nodes = {g for a, b, _, _ in edges for g in (a, b)}
    n_recip_all = sum(1 for *_, r in edges if r)
    print(f"shipped edges in '{context}': {len(edges):,}  "
          f"({n_recip_all:,} reciprocal)  over {len(nodes):,} genes")

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
