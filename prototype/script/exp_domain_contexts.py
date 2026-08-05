"""
exp_domain_contexts.py — is a per-assay-domain co-essentiality layer worth shipping?
====================================================================================
ANSWER: NO. Measured 2026-08-05, on 1,375 genome-wide FULL human screens. The layer is not
built, and the --domain flag in compute_coessential.py should be treated as an experiment
harness, not a pending feature.

  context           edges   recip   genes   prec(all)  prec(rec)  vs chance
  all (POOLED)    109,412   9,905   5,269      0.1468     0.3538      45.1x
  domain:fitness  114,605  11,685   5,085      0.0734     0.2113      26.8x
  domain:stress    26,952  23,088   8,604      0.2288     0.2361      41.0x
  domain:reporter     306     306     398      0.3398     0.3398      29.3x

Pooling wins on the number that matters -- mutual-best precision, the view the UI defaults to.
Splitting by fitness HALVES it (0.354 -> 0.211) while shipping MORE edges, which is the worst
possible trade.

And the argument that a domain layer is for the genes pooling fails does not survive contact
with the data either. Over the 2,894 genes the pooled network gives <= 2 mutual-best partners:

  all (POOLED)     1,657 rescue edges   precision 0.3580   52.9x chance
  domain:fitness   4,990 rescue edges   precision 0.1505   18.1x
  domain:stress    9,391 rescue edges   precision 0.1471   24.7x
  domain:reporter    126 rescue edges   precision 0.1471   15.7x

Even for the genes pooling "fails", pooling's few edges are 2.4x more precise than the domain
layers' many. Opening a domain context for a sparse gene would fill the page with edges that
are ~85% wrong. More to look at, and worse.

WHY -- the mechanism, since the original assumption was reasonable
Co-essentiality is discriminative because a pair must co-move across HETEROGENEOUS conditions.
Restricting to one assay domain removes exactly the variance that separates a real functional
partnership from generic pan-essential co-drop, and PC1 removal then strips proportionally more
real signal from what is left. Fitness screens are also the most redundant with one another, so
886 of them carry far less independent information than 886 mixed ones. Small domains lose a
second way: the shuffle-null threshold correctly rises as sqrt(1/n_screens) -- reporter's 80
screens push it from r>=0.15 to r>=0.45, leaving 306 edges over 398 genes.

WHAT THIS DOES NOT SHOW
CORUM is dominated by large constitutive machines (ribosome, proteasome, spliceosome) -- which
fitness screens measure well, and which flatter any fitness-heavy pool. The genes a biologist
actually types (TP53, MYC, BRCA1) are regulatory and mostly not in a CORUM complex at all, so
they contribute to neither number. domain:stress reaches 4,523 genes the pooled network never
sees; this experiment can only say those edges are 0.147-precise on the annotated subset, not
that they are worthless everywhere. A ground truth that covers regulatory genes (a curated
pathway set, or held-out GO co-annotation) would be needed to settle that, and is the honest
next experiment if the coverage gap is ever worth reopening.

Also settled here: POLA1 is NOT rescued by any split. Its pooled neighbourhood has 1 mutual-best
partner (UBA1, not a replication factor); fitness gives it WDR75/PRPF6/SF3B5 (ribosome
biogenesis and spliceosome, still not the pol-alpha primase complex) and stress gives it
UBA1/GOLGA8O/GLT8D2. The dilution story that motivated stratification is real at the SCORE level
(POLA1 averages +0.03 across focused libraries vs -0.47 genome-wide) and is already handled by
the n_genes >= 15,000 library gate. It is not an assay_domain problem.


The design note in build_net_context.py assumed edges should be stratified by assay_domain
("only pool/correlate within a domain"), and compute_coessential.py has carried an unused
--domain flag for that planned layer. This measures whether the layer actually earns its place,
against the same ground truth the shipped network is validated on (CORUM 5.3, complexes of
3-60 subunits, both endpoints annotated).

WHAT IS MEASURED, AND WHY THESE THREE THINGS

1. GLOBAL precision per context. The headline check. Reciprocal precision is the one that
   matters -- mutual-best is what the UI defaults to -- and it must be read next to coverage,
   because a context built from fewer screens buys precision by shipping fewer edges.

2. RESCUE precision. The global number answers "is a domain network better in general", which
   is NOT the product question. The product question is narrower: for a gene whose POOLED
   neighbourhood is near-empty (TP53 ships 1 mutual-best partner, POLA1 ships 1), does a domain
   context give that gene real partners, or just enough noise to fill the screen? So precision
   is recomputed over ONLY the edges belonging to genes the pooled network fails, which is the
   only population that would ever see the new layer.

3. What each context adds that the others do not -- genes present here and nowhere else.

A NOTE ON WHY THE GLOBAL NUMBER CAN MISLEAD IN BOTH DIRECTIONS
CORUM is dominated by large constitutive machines (ribosome, proteasome, spliceosome), which
are exactly what fitness screens measure well, so a fitness-heavy pool is flattered. The genes a
biologist actually types -- TP53, MYC, BRCA1 -- are regulatory and are mostly NOT in a CORUM
complex at all, so they contribute nothing to either number. That is a real limit of this
ground truth, stated here rather than worked around: a context can only be shown to be
non-harmful on CORUM, not shown to be useful for the genes CORUM does not cover.

  /opt/anaconda3/bin/python3 script/exp_domain_contexts.py
"""
import csv
import sqlite3
from collections import defaultdict

import numpy as np

import paths

NET = paths.PROCESSED_DATA / "reticle_net.db"
CORUM = paths.PROCESSED_DATA / "corum_human_v5.3.txt"

CONTEXTS = ["all", "domain:fitness", "domain:stress", "domain:reporter"]

# A gene is "failed by the pooled network" when the default view gives it almost nothing to look
# at. 2 is the cutoff because that is where the page stops being a graph and becomes a caption.
SPARSE_MAX_RECIP = 2


def load_corum(lo=3, hi=60):
    gene_cplx = defaultdict(set)
    with open(CORUM, encoding="utf-8", errors="replace") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        for r in rd:
            gs = {g.strip().upper() for g in (r.get("subunits_gene_name") or "").split(";") if g.strip()}
            if lo <= len(gs) <= hi:
                for g in gs:
                    gene_cplx[g].add(r["complex_id"])
    return gene_cplx


def edges_of(con, ctx):
    return con.execute(
        "SELECT gene_a, gene_b, strength, reciprocal FROM net_edge "
        "WHERE context=? AND channel='coessential'", (ctx,)).fetchall()


def precision(pairs, gene_cplx):
    """Fraction of pairs that are same-complex, over pairs where BOTH ends are annotated."""
    scor = [(a, b) for a, b in pairs if a.upper() in gene_cplx and b.upper() in gene_cplx]
    if not scor:
        return float("nan"), 0
    hits = sum(bool(gene_cplx[a.upper()] & gene_cplx[b.upper()]) for a, b in scor)
    return hits / len(scor), len(scor)


def chance(pool, gene_cplx, n=500_000, seed=0):
    pool = sorted(g for g in pool if g.upper() in gene_cplx)
    if len(pool) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pool), size=(n, 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    return float(np.mean([bool(gene_cplx[pool[i].upper()] & gene_cplx[pool[j].upper()])
                          for i, j in idx]))


def main():
    gene_cplx = load_corum()
    con = sqlite3.connect(NET)

    E = {c: edges_of(con, c) for c in CONTEXTS}
    E = {c: e for c, e in E.items() if e}

    print("=" * 96)
    print("1. GLOBAL — precision must be read next to coverage")
    print("=" * 96)
    print("  %-16s %9s %9s %8s   %9s %9s   %8s" %
          ("context", "edges", "recip", "genes", "prec(all)", "prec(rec)", "vs chance"))
    for c, e in E.items():
        genes = {g for a, b, _, _ in e for g in (a, b)}
        p_all, n_all = precision([(a, b) for a, b, _, _ in e], gene_cplx)
        p_rec, n_rec = precision([(a, b) for a, b, _, r in e if r], gene_cplx)
        base = chance(genes, gene_cplx)
        print("  %-16s %9s %9s %8s   %9.4f %9.4f   %6.1fx" % (
            c, f"{len(e):,}", f"{sum(r for *_, r in e):,}", f"{len(genes):,}",
            p_all, p_rec, (p_rec / base if base else float('nan'))))
    print("    prec(all)=every shipped edge, prec(rec)=mutual-best only (the UI default).")

    # ---------------------------------------------------------------- rescue
    pooled = E["all"]
    recip_deg = defaultdict(int)
    for a, b, _, r in pooled:
        if r:
            recip_deg[a] += 1
            recip_deg[b] += 1
    pooled_genes = {g for a, b, _, _ in pooled for g in (a, b)}
    sparse = {g for g in pooled_genes if recip_deg[g] <= SPARSE_MAX_RECIP}

    print()
    print("=" * 96)
    print(f"2. RESCUE — the {len(sparse):,} genes the POOLED network gives <= {SPARSE_MAX_RECIP} "
          f"mutual-best partners")
    print("=" * 96)
    print("   These are the only genes a new context would ever be opened for. A context earns its")
    print("   place here or nowhere: the question is not whether it beats pooled on average, it is")
    print("   whether the partners it offers THESE genes are real.")
    print()
    print("  %-16s %11s %11s   %9s %9s" % ("context", "rescue edges", "scorable", "precision", "vs chance"))
    for c, e in E.items():
        pr = [(a, b) for a, b, _, r in e if r and (a in sparse or b in sparse)]
        p, nsc = precision(pr, gene_cplx)
        genes = {g for a, b in pr for g in (a, b)}
        base = chance(genes, gene_cplx)
        print("  %-16s %11s %11s   %9.4f %8.1fx" % (
            c, f"{len(pr):,}", f"{nsc:,}", p, (p / base if base else float('nan'))))

    # ------------------------------------------------------------- new genes
    print()
    print("=" * 96)
    print("3. COVERAGE — genes each context reaches that the POOLED network does not")
    print("=" * 96)
    for c, e in E.items():
        if c == "all":
            continue
        genes = {g for a, b, _, r in e if r for g in (a, b)}
        new = genes - pooled_genes
        ann = sum(1 for g in new if g.upper() in gene_cplx)
        print("  %-16s %6s genes with a mutual-best edge, %6s NOT in the pooled network "
              "(%s CORUM-annotated)" % (c, f"{len(genes):,}", f"{len(new):,}", f"{ann:,}"))

    con.close()


if __name__ == "__main__":
    main()
