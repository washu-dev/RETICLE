"""
Small DEMO of the correlation engine — runs the same logic as
compute_correlations.py but on a handful of hand-picked screens so the output is
instant. NOT for production; just to show example rows.

  python3 sample_correlations_demo.py
"""

import sqlite3
import numpy as np
from scipy import stats

import compute_correlations as cc  # reuse the real functions

DB = cc.DB


def pick_demo_screens(db, n_full=12, n_hitonly=4):
    """Pick a few human screens: some genome-wide viability (should correlate),
    a couple unrelated, plus a few HIT_ONLY (for the binary path)."""
    full = [r[0] for r in db.execute(
        """SELECT SCREEN_ID FROM screen_metadata
           WHERE ORGANISM_OFFICIAL='Homo sapiens' AND COVERAGE_TYPE='FULL'
             AND SCORES_SIZE > 15000
             AND (LOWER(PHENOTYPE) LIKE '%prolifer%' OR LOWER(SCREEN_RATIONALE) LIKE '%essential%')
           ORDER BY CAST(SCREEN_ID AS INTEGER) LIMIT ?""", (n_full,)).fetchall()]
    hitonly = [r[0] for r in db.execute(
        """SELECT SCREEN_ID FROM screen_metadata
           WHERE ORGANISM_OFFICIAL='Homo sapiens' AND COVERAGE_TYPE='HIT_ONLY'
           ORDER BY CAST(SCREEN_ID AS INTEGER) LIMIT ?""", (n_hitonly,)).fetchall()]
    return full, hitonly


def build_matrix_for(db, screen_ids):
    """Same matrix build as the real engine, but for an explicit screen list."""
    genes = [r[0] for r in db.execute(
        f"""SELECT GENE_SYMBOL FROM harmonized_scores
            WHERE SCREEN_ID IN ({','.join('?'*len(screen_ids))})
              AND PERCENTILE_SCORE IS NOT NULL
            GROUP BY GENE_SYMBOL HAVING COUNT(DISTINCT SCREEN_ID) >= 2""",
        screen_ids).fetchall()]
    gene_idx = {g: i for i, g in enumerate(genes)}
    G, S = len(genes), len(screen_ids)
    X = np.zeros((G, S), dtype=np.float32)
    M = np.zeros((G, S), dtype=np.float32)
    for j, sid in enumerate(screen_ids):
        for g, p in db.execute(
            "SELECT GENE_SYMBOL, PERCENTILE_SCORE FROM harmonized_scores "
            "WHERE SCREEN_ID=? AND PERCENTILE_SCORE IS NOT NULL", (sid,)):
            gi = gene_idx.get(g)
            if gi is not None:
                X[gi, j] = p; M[gi, j] = 1.0
    return X, M


def label(db, sid):
    r = db.execute("SELECT ANALYSIS, PHENOTYPE FROM screen_metadata WHERE SCREEN_ID=?", (sid,)).fetchone()
    return f"{r[0][:10]:10s} | {(r[1] or '')[:22]:22s}"


def main():
    db = sqlite3.connect(DB)
    full, hitonly = pick_demo_screens(db)
    print(f"Demo screens — {len(full)} FULL (genome-wide viability), {len(hitonly)} HIT_ONLY\n")

    # ---------- CONTINUOUS ----------
    X, M = build_matrix_for(db, full)
    R, N = cc.pairwise_rho(X, M)
    tail_present = np.abs(X) > cc.TAIL_CUTOFF

    print("=== CONTINUOUS (Spearman on PERCENTILE_SCORE, pairwise-complete) ===")
    print(f"{'screen 1':>9} {'screen 2':>9}  {'overlap':>7} {'rho':>7} {'rho_tail':>8} {'p-value':>10}")
    print("-" * 62)
    for i in range(len(full)):
        for j in range(i + 1, len(full)):
            n = int(N[i, j]); r = R[i, j]
            if n < cc.MIN_OVERLAP_GENES or not np.isfinite(r):
                continue
            t = r * np.sqrt((n - 2) / (1 - r * r))
            p = 2 * stats.t.sf(abs(t), df=n - 2)
            both = (M[:, i] > 0) & (M[:, j] > 0)
            tail = both & (tail_present[:, i] | tail_present[:, j])
            rt = float(np.corrcoef(X[tail, i], X[tail, j])[0, 1]) if tail.sum() >= cc.MIN_TAIL_GENES else float('nan')
            print(f"{full[i]:>9} {full[j]:>9}  {n:>7} {r:>7.3f} {rt:>8.3f} {p:>10.2e}")

    # ---------- BINARY ----------
    print("\n=== BINARY (Jaccard + Fisher on IS_HIT sets) ===")
    print("HIT_ONLY screen vs other screens that share >= 3 hits\n")
    hits = {}
    for sid in hitonly + full:
        hits[sid] = {r[0] for r in db.execute(
            "SELECT GENE_SYMBOL FROM harmonized_scores WHERE SCREEN_ID=? AND IS_HIT=1", (sid,))}
    N_uni = db.execute(
        "SELECT COUNT(DISTINCT GENE_SYMBOL) FROM harmonized_scores h "
        "JOIN screen_metadata m ON h.SCREEN_ID=m.SCREEN_ID WHERE m.ORGANISM_OFFICIAL='Homo sapiens'").fetchone()[0]

    print(f"{'HIT_ONLY':>9} {'other':>9}  {'|h1|':>5} {'|h2|':>6} {'shared':>6} {'jaccard':>8} {'fisher_p':>10}")
    print("-" * 64)
    shown = 0
    for s1 in hitonly:
        h1 = hits[s1]
        if not h1:
            continue
        for s2 in (full + hitonly):
            if s1 == s2:
                continue
            shared = len(h1 & hits[s2])
            if shared < cc.MIN_SHARED_HITS:
                continue
            union = len(h1) + len(hits[s2]) - shared
            jac = shared / union if union else 0
            fp = float(stats.hypergeom.sf(shared - 1, N_uni, len(h1), len(hits[s2])))
            print(f"{s1:>9} {s2:>9}  {len(h1):>5} {len(hits[s2]):>6} {shared:>6} {jac:>8.4f} {fp:>10.2e}")
            shown += 1
    if not shown:
        print("  (no demo pairs cleared the >=3 shared-hits threshold)")

    # ---------- one annotated example ----------
    print("\n=== What one row means ===")
    bi, bj, best = 0, 1, -1
    for i in range(len(full)):
        for j in range(i + 1, len(full)):
            if np.isfinite(R[i, j]) and R[i, j] > best and N[i, j] >= cc.MIN_OVERLAP_GENES:
                best, bi, bj = R[i, j], i, j
    print(f"screen {full[bi]} [{label(db, full[bi])}]")
    print(f"screen {full[bj]} [{label(db, full[bj])}]")
    print(f"  -> rho = {best:.3f} over {int(N[bi,bj])} shared genes")
    print(f"  -> these two screens rank their genes nearly identically = same biology")
    db.close()


if __name__ == "__main__":
    main()
