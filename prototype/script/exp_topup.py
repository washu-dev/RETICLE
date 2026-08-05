"""
exp_topup.py — what does it cost to stop showing near-empty graphs?
====================================================================
screen_net asks for mutual-best partners and only widens when there are ZERO of them
(`if not rows and reciprocal_only`). A gene with exactly one therefore renders a two-node
graph and stops. That is the state of the genes a biologist types first: TP53 ships 1
mutual-best partner, MYC 2, BRCA1 2, POLA1 1 — against 118, 38, 71 and 141 available in the
union view.

The naive fix, defaulting to the union, is measurably bad: union-only edges score 0.094
same-complex precision against mutual-best's 0.354.

The proposal measured here is TOP-UP: keep every mutual-best edge, then fill up to a floor of
N partners with the strongest union edges available, and only for genes that fall below the
floor. Genes that already have a full graph are untouched, so it cannot regress them.

The question this answers is narrow and decision-relevant: OF THE EDGES TOP-UP WOULD ADD, what
fraction are real? Not the union's global precision — the strongest few edges of a sparse gene
are a different population from all union edges everywhere.

  /opt/anaconda3/bin/python3 script/exp_topup.py
"""
import csv
import sqlite3
from collections import defaultdict

import numpy as np

import paths

NET = paths.PROCESSED_DATA / "reticle_net.db"
CORUM = paths.PROCESSED_DATA / "corum_human_v5.3.txt"
FLOORS = [4, 6, 8, 12, 18]


def load_corum(lo=3, hi=60):
    gene_cplx = defaultdict(set)
    with open(CORUM, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            gs = {g.strip().upper() for g in (r.get("subunits_gene_name") or "").split(";") if g.strip()}
            if lo <= len(gs) <= hi:
                for g in gs:
                    gene_cplx[g].add(r["complex_id"])
    return gene_cplx


def main():
    gc = load_corum()
    con = sqlite3.connect(NET)
    edges = con.execute(
        "SELECT gene_a, gene_b, strength, reciprocal FROM net_edge "
        "WHERE context='all' AND channel='coessential'").fetchall()
    con.close()

    # per gene: its edges, split by view
    rec_of, uni_of = defaultdict(list), defaultdict(list)
    for a, b, s, r in edges:
        (rec_of if r else uni_of)[a].append((b, s))
        (rec_of if r else uni_of)[b].append((a, s))
    genes = set(rec_of) | set(uni_of)

    def prec(pairs):
        sc = [(a, b) for a, b in pairs if a.upper() in gc and b.upper() in gc]
        if not sc:
            return float("nan"), 0
        return sum(bool(gc[a.upper()] & gc[b.upper()]) for a, b in sc) / len(sc), len(sc)

    def chance(pool, n=400_000):
        pool = sorted(g for g in pool if g.upper() in gc)
        if len(pool) < 2:
            return float("nan")
        rng = np.random.default_rng(0)
        idx = rng.integers(0, len(pool), size=(n, 2))
        idx = idx[idx[:, 0] != idx[:, 1]]
        return float(np.mean([bool(gc[pool[i].upper()] & gc[pool[j].upper()]) for i, j in idx]))

    print("=" * 92)
    print("how many genes are below each floor, and what would top-up ADD to them?")
    print("=" * 92)
    print("  %-6s %10s %12s   %10s %10s %9s   %10s" %
          ("floor", "genes below", "edges added", "added prec", "vs chance", "scorable", "recip prec"))

    base_rec, _ = prec([(a, b) for a, b, _, r in edges if r for a, b in [(a, b)]])
    for floor in FLOORS:
        added, below = [], 0
        for g in genes:
            have = rec_of.get(g, [])
            if len(have) >= floor:
                continue
            below += 1
            need = floor - len(have)
            # strongest union partners this gene has, excluding ones already shown
            shown = {nb for nb, _ in have}
            pool = sorted((s, nb) for nb, s in uni_of.get(g, []) if nb not in shown)
            for s, nb in sorted(pool, reverse=True)[:need]:
                added.append((g, nb))
        # dedupe: an added edge can be reached from both endpoints
        added = {(a, b) if a < b else (b, a) for a, b in added}
        p, nsc = prec(added)
        pool_genes = {x for pair in added for x in pair}
        base = chance(pool_genes)
        print("  %-6d %10s %12s   %10.4f %9.1fx %9s   %10.4f" % (
            floor, f"{below:,}", f"{len(added):,}", p, (p / base if base else float("nan")),
            f"{nsc:,}", base_rec))
    print()
    print("  recip prec = the mutual-best baseline the top-up edges are diluting (%.4f)." % base_rec)
    print("  A top-up edge is worth showing if its precision clears chance by a wide margin AND the")
    print("  blended graph still reads as evidence rather than as noise -- the tier badge already")
    print("  tells the user which kind each edge is, so they are not silently mixed.")

    # what the demo genes would actually get
    print()
    print("=" * 92)
    print("the genes a demo will actually type")
    print("=" * 92)
    print("  %-9s %8s %8s   %s" % ("gene", "recip", "union", "top-up would add (strongest first)"))
    for g in ("TP53", "BRCA1", "MYC", "KRAS", "POLA1", "EGFR", "PTEN", "FANCD2"):
        have = sorted(rec_of.get(g, []), key=lambda x: -x[1])
        shown = {nb for nb, _ in have}
        pool = sorted(((s, nb) for nb, s in uni_of.get(g, []) if nb not in shown), reverse=True)
        add = [nb for _, nb in pool[:max(0, 8 - len(have))]]
        print("  %-9s %8d %8d   %s" % (g, len(have), len(uni_of.get(g, [])), ", ".join(add) or "—"))


if __name__ == "__main__":
    main()
