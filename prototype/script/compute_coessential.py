"""
compute_coessential.py — co-essentiality edges WITHIN one context (hub-controlled).
==================================================================================
Channel 1 of the network. Two genes are related if their signed within-screen
percentile profiles correlate across the genome-wide screens of a context.

SCREENS — two independent gates, previously (wrongly) conflated:
  * coverage_type='FULL' — BioGRID published the whole scored list, not just the hit list.
    HIT_ONLY screens have no non-hit baseline and can't inform a correlation.
  * n_genes >= --min-lib (15,000) — the library is genome-wide. This is NOT implied by FULL:
    FULL is a DATA-AVAILABILITY flag, and 368 of the 1,745 FULL human screens run focused
    libraries (349 under 5,000 genes; the smallest scores 33). PERCENTILE_SCORE is a rank
    against whatever the library contained, so it is only comparable across screens that
    share a reference set. Measured cost of mixing them: POLA1 averages +0.03 across focused
    libraries vs -0.47 genome-wide (it ranks mid-pack among a few hundred hand-picked genes,
    bottom among all ~19k) — a 0.5 swing from library composition alone. The bias is
    systematic, not noise: it compresses exactly the essential genes (TP53, non-essential,
    shifts 0.02). Gating on n_genes costs 68 of 19,055 nodes (0.36%).

Design decisions, each validated on CORUM 5.3 recovery AND spot-checked against known
complexes genome-wide (RPL13→ribosome, FANCD2→Fanconi; see the design notes):
  1. NODES = signal-bearing genes only — a gene joins the network only if it is a hit in
     >= --hit-min screens. A gene never hit has a flat/noise profile: no evidence, and its
     unstable correlations otherwise pollute the graph. (The dropped genes are largely
     lincRNA/uncharacterized "loner" genes with no phenotype.)
  2. HUBS / promiscuity — RECIPROCAL-RANK: `reciprocal=1` only if each gene is in the
     OTHER's top-k. This drops one-directional hub attachments (a hub a gene points to but
     that doesn't point back) and is the clean/sparse default view — fully data-pure, no
     annotation.
     NB: a symmetric-CLR hub control was TESTED and REJECTED — genome-wide it inflates
     edges to low-background loner genes and demotes the true complex partners raw
     correlation already recovers. Restricting nodes (1) + reciprocal-rank is what works.
     KNOWN LIMITATION — reciprocal-rank does NOT sever the pan-essential confound: distinct
     essential machines co-drop across screens tightly enough to be mutual-best. SF3A2's
     top partners mix its real SF3A/snRNP mates with ribosome/proteasome/PolII subunits at
     indistinguishable r (0.65-0.68). Global AUROC hides this (such pairs are a tiny slice of
     ~7M); it bites precision@top-k for pan-essential hubs. Unsolved — a specificity/
     promiscuity score is the candidate fix, layered on top rather than folded into r.
  3. Support — a high correlation over few co-measured screens is noise. Each edge stores
     its support (# co-measured screens); pairs below --min-support are dropped.
     NB: support is ALSO leaking into the estimate itself via the imputation shrinkage —
     known, deliberate, and load-bearing against multi-mapping artifacts. See the long note
     above zscore() before touching it.
  3b. KNOWN ARTIFACT CLASS (unfixed) — multi-mapping sgRNA genes (tandem-repeat/paralog
     families: USP17L28, TBC1D3, GOLGA8R, OR51A2, DEFA1, HBA1 …) co-drop on cutting toxicity
     rather than biology, and form tight mutual cliques. They are currently suppressed only
     as a SIDE EFFECT of the imputation shrinkage (they sit at 38-60% coverage). They need an
     explicit gate; until then the estimator cannot be corrected. See the note above zscore().
  4. NOISE FLOOR / threshold — a fixed correlation cutoff is wrong: pure noise still yields
     |r| ~ 1/sqrt(#screens), so a cutoff clean for a 1,000-screen pool sits BELOW the noise
     floor of a small one. We build a within-screen-shuffle NULL (permute values among each
     screen's measured genes — preserves coverage/support and each screen's distribution,
     destroys only co-movement) and raise the threshold to the lowest corr where
     reciprocal-edge FDR (null/real above the cut) <= --fdr. Over the full pooled set the
     floor is tiny so the threshold lands just above --min-corr; a future per-context layer
     (few screens each) is where this earns its keep. FIXED seed → reproducible.

Edges = each gene's top-k partners by raw co-essentiality correlation (support + FDR-threshold gated).
`reciprocal=1` = mutual-best (the clean, sparse view the frontend defaults to);
`reciprocal=0` = looser union (a partner one-directionally). Strength = the correlation.

Production is POOLED (--all, context='all'): one network over every genome-wide human screen.
Context slicing (--domain/--mechanism) is retained for the planned per-context layer.
Reads observations from reticle_master.db; writes edges to reticle_net.db.

  /opt/anaconda3/bin/python3 script/compute_coessential.py --all --min-screens 100
"""
import argparse
import sqlite3
import numpy as np
import pandas as pd

SRC = "processed_data/reticle_master.db"
NET = "processed_data/reticle_net.db"


def context_screens(net, domain, mechanism, min_lib):
    # coverage_type='FULL' only means BioGRID published the whole scored list rather than
    # just the hits — it says NOTHING about library scope. n_genes >= min_lib is the actual
    # genome-wide gate (see the header note on why percentile demands a fixed reference set).
    q = "SELECT screen_id FROM net_screen WHERE coverage_type='FULL' AND n_genes >= ?"
    args = [min_lib]
    if domain:
        q += " AND assay_domain=?"; args.append(domain)
    if mechanism:
        q += " AND mechanism=?"; args.append(mechanism)
    return [r[0] for r in net.execute(q, args)]


def ensure_schema(net):
    want = ["gene_a", "gene_b", "context", "channel", "strength", "support", "reciprocal"]
    cols = [r[1] for r in net.execute("PRAGMA table_info(net_edge)")]
    if cols and cols != want:                        # any schema drift → rebuild
        net.execute("DROP TABLE net_edge"); cols = []
    if not cols:
        net.execute("""CREATE TABLE net_edge (
            gene_a TEXT, gene_b TEXT, context TEXT, channel TEXT,
            strength REAL,        -- raw co-essentiality correlation [-1,1]
            support INTEGER,      -- # co-measured FULL screens
            reciprocal INTEGER)   -- 1 = mutual-best top-k (clean view), 0 = union only
        """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain")
    ap.add_argument("--mechanism")
    ap.add_argument("--min-lib", type=int, default=15000, help="screen library must score >= this many genes (genome-wide gate; percentile is only comparable against a fixed reference set)")
    ap.add_argument("--min-screens", type=int, default=15, help="gene measured in >= this many context screens")
    ap.add_argument("--min-support", type=int, default=20, help="a pair must be co-measured in >= this many screens")
    ap.add_argument("--min-corr", type=float, default=0.15, help="hard correlation floor (never keep edges below this)")
    ap.add_argument("--topk", type=int, default=25)
    ap.add_argument("--hit-min", type=int, default=5, help="a gene joins the network if a hit in >= this many screens")
    ap.add_argument("--min-cov", type=float, default=0.50, help="gene must be MEASURED in >= this fraction of the screens (artifact gate: low-coverage genes formed the reciprocal cliques)")
    ap.add_argument("--min-hit-rate", type=float, default=0.02, help="gene must be a hit in >= this fraction of the screens it was measured in (background is ~6.6%%; below 2%% is less than random)")
    ap.add_argument("--keep-pc1", action="store_true", help="do NOT remove the first principal component (the pan-essentiality axis). Off by default: PC1 loading correlates 0.888 with per-gene hit rate, and removing it is what lets real complexes outrank pan-essential co-drop.")
    ap.add_argument("--fdr", type=float, default=0.05, help="target edge-level FDR vs a within-screen-shuffle null; sets the per-context correlation threshold")
    ap.add_argument("--all", action="store_true", help="POOLED mode: one network 'all' over every FULL human screen (no context split)")
    args = ap.parse_args()
    rng = np.random.default_rng(0)                       # FIXED seed → the permutation null (and thus the threshold and edges) is reproducible
    label = "all" if args.all else (args.mechanism or f"domain:{args.domain}")

    net = sqlite3.connect(NET)
    sids = (context_screens(net, None, None, args.min_lib) if args.all
            else context_screens(net, args.domain, args.mechanism, args.min_lib))
    if len(sids) < 5:
        raise SystemExit(f"context '{label}' has only {len(sids)} genome-wide screens — too few")
    print(f"context '{label}': {len(sids)} genome-wide FULL screens (library >= {args.min_lib:,} genes)", flush=True)

    src = sqlite3.connect(SRC)
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

    # NODES — three gates. The old gate (hit_counts >= 5 only) was measured to admit every one of
    # 14 audited artifact genes: an absolute hit COUNT is meaningless at 1,377 screens, and with no
    # coverage floor a gene measured in 8% of screens (MIR1273A: 113/1377, 6 hits) entered the graph
    # and then saturated the 25-partner reciprocal cap. Adding a coverage floor + a hit-RATE floor
    # removes 10 of those 14 (all MIR*, olfactory receptors, defensins, USP17L*, NPIPA*) while
    # keeping every conditional gene checked (TP53 3.8%, ATM 4.6%, PTEN 5.7%, FANCD2 7.7%).
    n_scr = P.shape[1]
    hit_rate = hit_counts / np.maximum(meas.reindex(P.index).to_numpy(), 1)
    node = ((hit_counts >= args.hit_min)
            & (meas.reindex(P.index).to_numpy() >= args.min_cov * n_scr)
            & (hit_rate >= args.min_hit_rate))
    P = P[node]
    genes = P.index.to_numpy()
    A = P.to_numpy(np.float32)
    Bm = (~np.isnan(A)).astype(np.float32)                          # measured mask (support)
    G = len(genes)
    print(f"  {G:,} hit-active nodes (of {len(node):,} measured) × {A.shape[1]} screens", flush=True)

    # ---------------------------------------------------------------------------------------
    # IMPUTE-then-correlate. This estimator is KNOWN TO BE STATISTICALLY WRONG, and is kept
    # deliberately. Do not "fix" it in isolation — read this first.
    #
    # What it does: impute gene-mean → centre → unit-normalise, so Z@Z.T is Pearson over the
    # imputed matrix. Imputing a gene's own mean leaves that mean unchanged, so imputed cells
    # centre to exactly 0 and contribute nothing to the NUMERATOR. But the partner's real value
    # at that screen still enters ITS norm, so the DENOMINATOR is inflated by screens that
    # cannot pay into the numerator: r is shrunk toward 0 in proportion to coverage MISMATCH.
    # Measured: ~2.4% of edge candidates off by >0.10 (max 0.67) vs pairwise-complete Pearson.
    #
    # Why it stays: that bogus shrinkage is load-bearing. It is, by accident, a coverage-mismatch
    # penalty — and the genes it penalises hardest are multi-mapping sgRNA artifacts (USP17L28,
    # TBC1D3, GOLGA8R, OR51A2, DEFA1, HBA1, NPIPA1 …: tandem-repeat / paralog families whose
    # guides cut many loci, so they co-drop on cutting toxicity, not biology). Libraries disagree
    # about including such guides, so these genes sit at 38-60% coverage while real genes sit at
    # 95-99% — exactly the mismatch the shrinkage punishes.
    #
    # Switching to (correct) pairwise-complete Pearson was TESTED and REVERTED: it lifts artifact
    # pairs by +0.15..+0.20 (MED1-NPIPA1 0.32→0.53, USP17L28-TBC1D3 0.58→0.79) while real pairs
    # move +0.01..+0.03 (PSMB5-PSMB4 0.66→0.67). The artifacts then take over the graph —
    # reciprocal-rank SELECTS for them (they share one technical signal, so they are each other's
    # mutual-best): USP17L28/TBC1D3/LIMS3/GOLGA8R hit the 25-partner cap while RPL13 gets 17 and
    # PSMB5 gets 2, and MED1's neighbourhood degrades from MED9/GINS4/MED7 to C2orf27A/NPIPA1/
    # FOXD4L6/GOLGA8K. CORUM AUROC cannot see this (CORUM genes are all well-covered real genes)
    # — the same blind spot that let CLR look good before it broke genome-wide. Spot-check, don't
    # trust the aggregate.
    #
    # The correct sequence: gate the artifact class explicitly (coverage floor is the candidate,
    # but it is not clean — POLA1 is real at 71% while LIMS3 is artifact at 81% and GOLGA8R
    # reports 102%, i.e. duplicate rows), THEN switch to pairwise-complete and put overlap
    # confidence back where it belongs (`support`).
    # ---------------------------------------------------------------------------------------
    def zscore(mat):
        rm = np.nanmean(mat, 1, keepdims=True)
        Ai = np.where(np.isnan(mat), rm, mat)
        Ai = Ai - Ai.mean(1, keepdims=True)
        if not args.keep_pc1:
            # PAN-ESSENTIALITY AXIS REMOVAL. Distinct essential machines (ribosome / proteasome /
            # spliceosome) co-drop across screens simply because all are essential, which put
            # unrelated pan-essential partners AHEAD of real complex-mates: SF3A2's top partners
            # were PRPF19 and RPL4, with its actual SF3A-complex mate SF3A3 only 5th. That shared
            # variance is concentrated in the top singular component — measured: |PC1 loading|
            # correlates 0.888 with each gene's hit rate, i.e. PC1 IS "how essential is this gene".
            # Projecting it out: SF3A2 -> SF3A3 becomes #1, PSMB5 recovers PSMB3/PSMB4 (the
            # proteasome was previously not recovered at all), and CORUM same-complex precision in
            # the dominant correlation bin goes 42.8% -> 59.1%. NB all correlations shrink in
            # absolute value afterwards (RPL13-RPL3 0.73 -> 0.35); the shuffle-null threshold below
            # is recomputed from the same transformed matrix, so the FDR target still holds.
            U, S, Vt = np.linalg.svd(Ai, full_matrices=False)
            Ai = Ai - np.outer(U[:, 0] * S[0], Vt[0])
        nrm = np.linalg.norm(Ai, axis=1, keepdims=True); nrm[nrm == 0] = 1
        return (Ai / nrm).astype(np.float32)

    def topk_edges(Z):
        """each gene's top-k partners (raw corr >= min_corr floor, support >= min_support)."""
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

    def reciprocal_corrs(tk):                                       # correlations of the mutual-best edges
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

    # Real edges, plus a within-screen-shuffle NULL to calibrate the threshold. The shuffle
    # permutes values among the measured genes of each screen — it preserves every gene's
    # coverage/support and each screen's distribution, and destroys only cross-screen
    # co-movement, so it is the correlation you'd see from noise alone in THIS context.
    tk_real = topk_edges(zscore(A)); print("    real top-k done", flush=True)
    An = A.copy()                                                   # A still holds NaNs (not imputed in place)
    for cidx in range(An.shape[1]):
        col = An[:, cidx]; m = ~np.isnan(col)
        v = col[m].copy(); rng.shuffle(v); col[m] = v; An[:, cidx] = col
    tk_null = topk_edges(zscore(An)); print("    null (shuffled) top-k done", flush=True)

    # per-context threshold = lowest corr (>= min_corr) at which reciprocal-edge FDR
    # (# null edges / # real edges above the cut) drops to <= --fdr. Small contexts (few
    # screens = high noise floor) get a much higher threshold than large ones automatically.
    rr, rn = reciprocal_corrs(tk_real), reciprocal_corrs(tk_null)
    thr = 0.90
    for t in np.arange(args.min_corr, 0.90, 0.005):
        nreal = int((rr >= t).sum()); nnull = int((rn >= t).sum())
        if nreal >= 1 and nnull / nreal <= args.fdr:
            thr = round(float(t), 3); break
    nrf, nnf = int((rr >= thr).sum()), int((rn >= thr).sum())
    print(f"    threshold: r >= {thr:.3f}  (reciprocal-edge FDR {100*nnf/max(nrf,1):.1f}% vs shuffle null; "
          f"noise floor lifted the min_corr={args.min_corr} floor)" if thr > args.min_corr else
          f"    threshold: r >= {thr:.3f}  (min_corr floor; null barely reaches it — context well-sampled)", flush=True)

    # emit real edges with corr >= threshold (union of top-k), flag reciprocity
    ensure_schema(net)
    if args.all:
        net.execute("DELETE FROM net_edge")             # pooled-only rebuild: drop every prior per-context edge
    else:
        net.execute("DELETE FROM net_edge WHERE context=? AND channel='coessential'", (label,))
    out = {}
    for gi, d in tk_real.items():
        for gj, (corr, sup) in d.items():
            if corr < thr:
                continue
            a, b = (gi, gj) if gi < gj else (gj, gi)
            if (a, b) in out:
                continue
            recip = 1 if gi in tk_real.get(gj, ()) else 0
            out[(a, b)] = (str(genes[a]), str(genes[b]), label, "coessential",
                           round(corr, 4), sup, recip)
    rows = list(out.values())
    net.executemany("INSERT INTO net_edge VALUES (?,?,?,?,?,?,?)", rows)
    net.commit()
    nrecip = sum(r[6] for r in rows)
    print(f"DONE — {len(rows):,} edges in '{label}' ({nrecip:,} reciprocal / {len(rows)-nrecip:,} union-only) "
          f"at r>={thr:.3f}", flush=True)

    # spot check against known complexes (reciprocal = mutual-best, marked *)
    for probe in ("PSMB5", "RPL13", "POLR2A", "MED1", "FANCD2"):
        r = net.execute(
            "SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength, reciprocal "
            "FROM net_edge WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) "
            "ORDER BY strength DESC LIMIT 6", (probe, label, probe, probe)).fetchall()
        if r:
            print(f"  {probe}: " + ", ".join(f"{x[0]}({x[1]}{'*' if x[2] else ''})" for x in r), flush=True)
    net.close()


if __name__ == "__main__":
    main()
