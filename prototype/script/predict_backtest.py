"""
predict_backtest.py — does guilt-by-association actually recover known gene function?
=====================================================================================
v0 proof-of-signal for the PREDICTION feature. For each of several association layers
we build a gene's "neighbours", score every GO Biological-Process term by how strongly
the neighbours support it, and ask: are the gene's OWN (held-out) BP terms ranked above
its non-terms?  Metric = per-gene AUROC (positives = the gene's true eligible BP terms,
negatives = eligible BP terms it lacks), averaged over a random sample of genes.

A layer carries real function-prediction signal iff its mean AUROC is well above the
RANDOM-NEIGHBOUR null (~0.5). The null uses K random genes as neighbours, so it also
controls for GO term frequency — if a layer only beats null, the signal is real, not
just "common terms score high".

Layers (all guilt-by-association, none uses the gene's own annotations):
  coess       DepMap CRISPRGeneEffect correlation across cell lines (classic co-essentiality)
  screencorr  RETICLE harmonised fitness-screen matrix correlation (coess_9606.npz)
  string      STRING combined-score partners
  coscreen    BioGRID co-hit: genes hitting the same screens (normalised by hit frequency)

  /opt/anaconda3/bin/python3 script/predict_backtest.py \
      --db processed_data/kb.db \
      --depmap /Volumes/aorvedahl-RETICLE/Active/data/depmap/CRISPRGeneEffect.csv \
      --screenmat processed_data/coess_9606.npz \
      --k 25 --sample 400
"""
import argparse
import re
import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict
from sklearn.metrics import roc_auc_score

GENE_COL = re.compile(r"\((\d+)\)\s*$")
rng = np.random.default_rng(7)


def load_go_bp(db):
    con = sqlite3.connect(db)
    gene_terms = defaultdict(set)
    for gid, tid in con.execute(
        "SELECT gg.gene_id, gg.go_id FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
        "WHERE t.namespace='biological_process' AND t.is_obsolete=0"):
        gene_terms[gid].add(tid)
    sym2gid = {s.upper(): g for g, s in con.execute("SELECT gene_id, symbol FROM kb_gene WHERE taxid=9606")}
    term_name = {t: n for t, n in con.execute("SELECT go_id, name FROM kb_go_term")}
    con.close()
    return gene_terms, sym2gid, term_name


def zscore_rows(M):
    """z-score each row across columns; NaN-safe (impute row mean → 0 after centring)."""
    M = M.astype(np.float32, copy=True)
    rm = np.nanmean(M, axis=1, keepdims=True)
    bad = np.isnan(M)
    M[bad] = np.broadcast_to(rm, M.shape)[bad]
    mu = M.mean(1, keepdims=True)
    sd = M.std(1, keepdims=True); sd[sd == 0] = 1
    return (M - mu) / sd


def matrix_neighbours(Z, idx, k):
    """top-k rows by Pearson corr with row idx (Z rows are z-scored). returns (indices, weights)."""
    c = (Z @ Z[idx]) / Z.shape[1]
    c[idx] = -2
    top = np.argpartition(c, -k)[-k:]
    top = top[np.argsort(c[top])[::-1]]
    return top, np.clip(c[top], 0, None)


# ---- association layers: each returns dict gid -> {neighbour_gid: weight} for the test genes ----
def layer_matrix(gene_ids, Z, test_gids, k):
    idx = {g: i for i, g in enumerate(gene_ids)}
    out = {}
    for g in test_gids:
        if g not in idx:
            continue
        ni, nw = matrix_neighbours(Z, idx[g], k)
        out[g] = {int(gene_ids[j]): float(w) for j, w in zip(ni, nw) if w > 0}
    return out


def layer_string(db, test_gids, k):
    con = sqlite3.connect(db)
    out = {}
    for g in test_gids:
        rows = con.execute(
            "SELECT CASE WHEN gene_id_a=? THEN gene_id_b ELSE gene_id_a END nb, combined_score s "
            "FROM kb_string_edge WHERE gene_id_a=? OR gene_id_b=? ORDER BY s DESC LIMIT ?",
            (g, g, g, k)).fetchall()
        if rows:
            out[g] = {nb: s / 1000.0 for nb, s in rows}
    con.close()
    return out


def layer_string_clean(db, test_gids, k):
    """STRING partners using ONLY annotation-independent channels — experimental,
    coexpression, and genomic-context (neighborhood/fusion/cooccurence). Excludes the
    circular `database` (curated pathways) and `textmining` (co-mention) channels.
    Recombines the kept channels as STRING does: p = 1 - Π(1 - c_i/1000)."""
    con = sqlite3.connect(db)
    out = {}
    for g in test_gids:
        rows = con.execute(
            "SELECT CASE WHEN gene_id_a=? THEN gene_id_b ELSE gene_id_a END nb, "
            "neighborhood, fusion, cooccurence, coexpression, experimental "
            "FROM kb_string_edge WHERE gene_id_a=? OR gene_id_b=?", (g, g, g)).fetchall()
        scored = {}
        for r in rows:
            p = 1.0
            for c in r[1:]:
                p *= 1.0 - (c or 0) / 1000.0
            clean = 1.0 - p
            if clean > 0:
                scored[r[0]] = clean
        if scored:
            out[g] = dict(sorted(scored.items(), key=lambda x: -x[1])[:k])
    con.close()
    return out


def layer_coscreen(db, test_gids, k):
    con = sqlite3.connect(db)
    hits = dict(con.execute("SELECT gene_id, COUNT(*) FROM kb_screen_hit GROUP BY gene_id"))
    out = {}
    for g in test_gids:
        co = con.execute(
            "SELECT h2.gene_id nb, COUNT(*) c FROM kb_screen_hit h1 "
            "JOIN kb_screen_hit h2 ON h2.screen_id=h1.screen_id AND h2.gene_id!=h1.gene_id "
            "WHERE h1.gene_id=? GROUP BY h2.gene_id", (g,)).fetchall()
        if not co:
            continue
        hg = hits.get(g, 1)
        scored = {nb: c / np.sqrt(hg * hits.get(nb, 1)) for nb, c in co}   # lift, downweight promiscuous
        top = sorted(scored.items(), key=lambda x: -x[1])[:k]
        out[g] = dict(top)
    con.close()
    return out


def evaluate(neigh, gene_terms, eligible, all_terms_arr):
    """Per-gene AUROC + hit@k (a held-out true term appears in the top-k predictions)."""
    aurocs, h5, h10, h20 = [], [], [], []
    for g, nb in neigh.items():
        pos = gene_terms.get(g, set()) & eligible
        if not pos or len(pos) == len(eligible) or not nb:
            continue
        score = defaultdict(float)
        for n, w in nb.items():
            for t in (gene_terms.get(n, set()) & eligible):
                score[t] += w
        if not score:
            continue
        y_true = np.array([1 if t in pos else 0 for t in all_terms_arr])
        y_score = np.array([score.get(t, 0.0) for t in all_terms_arr])
        if y_true.sum() == 0 or y_true.sum() == len(y_true):
            continue
        aurocs.append(roc_auc_score(y_true, y_score))
        ranked = [t for t, _ in sorted(score.items(), key=lambda x: -x[1])]
        h5.append(1 if pos & set(ranked[:5]) else 0)
        h10.append(1 if pos & set(ranked[:10]) else 0)
        h20.append(1 if pos & set(ranked[:20]) else 0)
    return (np.array(aurocs), np.array(h5), np.array(h10), np.array(h20))


def null_neighbours(test_gids, universe, k):
    return {g: {int(x): 1.0 for x in rng.choice(universe, size=k, replace=False)} for g in test_gids}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--depmap")
    ap.add_argument("--screenmat")
    ap.add_argument("--k", type=int, default=25)
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--min-term", type=int, default=5)
    ap.add_argument("--max-term", type=int, default=300)
    args = ap.parse_args()

    print("loading GO BP annotations…", flush=True)
    gene_terms, sym2gid, term_name = load_go_bp(args.db)
    # eligible terms: size in [min,max] over all annotated genes (avoid generic + too-rare)
    term_size = defaultdict(int)
    for ts in gene_terms.values():
        for t in ts:
            term_size[t] += 1
    eligible = {t for t, s in term_size.items() if args.min_term <= s <= args.max_term}
    all_terms_arr = np.array(sorted(eligible))
    annotated = {g for g, ts in gene_terms.items() if ts & eligible}
    print(f"  eligible BP terms: {len(eligible):,} (size {args.min_term}-{args.max_term}) | "
          f"genes with an eligible term: {len(annotated):,}", flush=True)

    # ---- load matrices ----
    Z_dep = gids_dep = None
    if args.depmap:
        print("loading DepMap matrix…", flush=True)
        df = pd.read_csv(args.depmap, index_col=0)
        keep = [c for c in df.columns if GENE_COL.search(c)]
        gids_dep = np.array([int(GENE_COL.search(c).group(1)) for c in keep])
        Z_dep = zscore_rows(df[keep].to_numpy(dtype=np.float32).T)   # genes x lines
        print(f"  DepMap: {Z_dep.shape[0]:,} genes × {Z_dep.shape[1]:,} cell lines", flush=True)

    Z_scr = gids_scr = None
    if args.screenmat:
        print("loading RETICLE screen matrix…", flush=True)
        d = np.load(args.screenmat, allow_pickle=True)
        syms, R = d["genes"], d["R"]
        gids_scr = np.array([sym2gid.get(s.upper(), -1) for s in syms])
        keep = gids_scr > 0
        Z_scr = zscore_rows(R[keep])
        gids_scr = gids_scr[keep]
        print(f"  screen matrix: {Z_scr.shape[0]:,} genes × {Z_scr.shape[1]:,} screens", flush=True)

    # ---- test-gene sample: annotated genes present in DepMap (the anchor layer) ----
    pool = sorted(annotated & set(gids_dep.tolist())) if Z_dep is not None else sorted(annotated)
    test = [int(x) for x in rng.choice(pool, size=min(args.sample, len(pool)), replace=False)]
    print(f"  test genes: {len(test)} (sampled from {len(pool):,})\n", flush=True)

    layers = {}
    if Z_dep is not None:
        layers["coess (DepMap, orthogonal)"] = layer_matrix(gids_dep, Z_dep, test, args.k)
    layers["string (full)"] = layer_string(args.db, test, args.k)
    layers["string-clean (no db/textmine)"] = layer_string_clean(args.db, test, args.k)
    universe = np.array(sorted(annotated))
    layers["NULL (random)"] = null_neighbours(test, universe, args.k)

    print(f"{'LAYER':22} {'AUROC':>7} {'hit@5':>7} {'hit@10':>7} {'hit@20':>7} {'n':>6}")
    print("-" * 60)
    results = {}
    for name, neigh in layers.items():
        au, h5, h10, h20 = evaluate(neigh, gene_terms, eligible, all_terms_arr)
        results[name] = au
        if len(au):
            print(f"{name:22} {au.mean():>7.3f} {h5.mean():>7.2f} {h10.mean():>7.2f} {h20.mean():>7.2f} {len(au):>6}", flush=True)
        else:
            print(f"{name:22} {'— (no genes evaluated)':>7}", flush=True)

    # ---- qualitative: what does it PREDICT for a few genes (recovered ✓ vs novel) ----
    best_layer = max((n for n in layers if "NULL" not in n),
                     key=lambda n: results[n].mean() if len(results[n]) else 0)
    print(f"\n=== example predictions from '{best_layer}' (✓ = gene already has it → recovered; "
          f"else = NOVEL prediction) ===", flush=True)
    neigh = layers[best_layer]
    gid2sym = {gg: s for s, gg in sym2gid.items()}
    cands = []
    for g in test:
        if g not in neigh:
            continue
        pos = gene_terms.get(g, set()) & eligible
        if len(pos) < 3:
            continue
        score = defaultdict(float)
        for n, w in neigh[g].items():
            for t in (gene_terms.get(n, set()) & eligible):
                score[t] += w
        top = sorted(score.items(), key=lambda x: -x[1])[:6]
        n_rec = sum(1 for t, _ in top if t in pos)
        cands.append((n_rec, g, pos, top))
    cands.sort(key=lambda x: -x[0])                       # show the clearest recoveries first
    for n_rec, g, pos, top in cands[:6]:
        print(f"\n  {gid2sym.get(g, g)} (GeneID {g}) — {n_rec}/6 top predictions match a known function:", flush=True)
        for t, sc in top:
            mark = "✓ recovered" if t in pos else "· predicted (novel)"
            print(f"     {mark:20} {term_name.get(t, t)}", flush=True)


if __name__ == "__main__":
    main()
