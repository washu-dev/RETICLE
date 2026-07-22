"""
RETICLE — Cross-Screen Correlation Engine (Phase 3)
===================================================

Builds the `correlation_analysis` table: for every comparable pair of screens,
how similar are their gene-level results?  This is the connective tissue that
turns 2,157 isolated screens into a queryable similarity network (drives the
dark-matter and hypothesis phases downstream).

WHAT IT COMPARES
----------------
Two genes only inform a comparison if both screens measured them, so every pair
is computed on the INTERSECTION of their genes, and the intersection size is
recorded so downstream code knows how much to trust the number.

Pairs are only ever formed WITHIN one organism (human vs mouse share almost no
gene symbols — `POLR2A` vs `Polr2a` — and the biology differs).

TWO MODES (routed by COVERAGE_TYPE from the harmonization step)
---------------------------------------------------------------
  CONTINUOUS  (both screens FULL):
      Spearman-style rank correlation on the harmonized PERCENTILE_SCORE.
      Because PERCENTILE_SCORE is itself a within-screen rank mapped to
      [-1, 1], a Pearson correlation of two screens' percentile vectors over
      their shared genes IS a rank correlation (== Spearman when gene sets
      match; a principled global-rank similarity when they only partly overlap).
      Computed for ALL pairs at once via masked matrix algebra (pairwise-complete
      observations), then a tail-restricted correlation is added for survivors
      (Anthony's point: the ~80% mid-distribution genes are noise; the signal is
      in the tails).

  BINARY  (at least one screen is HIT_ONLY — only its hits were deposited, so it
           has no genome-wide ranking):
      Jaccard similarity + Fisher's exact (hypergeometric) p-value on the
      author-defined hit sets (IS_HIT).

Only pairs that clear minimum thresholds are stored (a near-zero correlation or
a 2-gene overlap is not worth a row).

Run after harmonize_scores.py:  python3 compute_correlations.py
"""

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

DB = str(paths.DB)

# ---- thresholds (tunable) -------------------------------------------------
MIN_OVERLAP_GENES = 500    # continuous: reject pairs with a tiny shared-gene set
RHO_MIN = 0.30             # continuous: only store |rho| at/above this
TAIL_CUTOFF = 0.50         # |percentile| above this counts as "tail" (a real hit)
MIN_TAIL_GENES = 20        # need at least this many tail genes to report tail-rho
MIN_SHARED_HITS = 3        # binary: only store pairs sharing at least this many hits
GENE_UNIVERSE_MIN_SCREENS = 2  # a symbol in <2 screens can't affect any overlap


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def create_schema(db):
    db.execute("DROP TABLE IF EXISTS correlation_analysis")
    db.execute(
        """CREATE TABLE correlation_analysis (
               screen_id_1            TEXT,
               screen_id_2            TEXT,
               organism               TEXT,
               correlation_type       TEXT,     -- CONTINUOUS | BINARY
               gene_overlap_count     INTEGER,  -- genes measured in BOTH screens
               gene_overlap_fraction  REAL,     -- overlap / smaller screen's measured genes
               spearman_rho           REAL,     -- CONTINUOUS only
               spearman_pvalue        REAL,     -- CONTINUOUS only
               spearman_rho_tails     REAL,     -- CONTINUOUS only: corr on tail genes (|pct|>cutoff in either)
               jaccard_similarity     REAL,     -- BINARY only
               fisher_pvalue          REAL,     -- BINARY only
               shared_hits_count      INTEGER,  -- BINARY only
               computed_at            TEXT
           )"""
    )


def create_indexes(db):
    db.execute("CREATE INDEX idx_corr_s1 ON correlation_analysis(screen_id_1, spearman_rho)")
    db.execute("CREATE INDEX idx_corr_s2 ON correlation_analysis(screen_id_2, spearman_rho)")
    db.execute("CREATE INDEX idx_corr_jac ON correlation_analysis(screen_id_1, jaccard_similarity)")


# ---------------------------------------------------------------------------
# CONTINUOUS mode — FULL x FULL within one organism
# ---------------------------------------------------------------------------

def build_percentile_matrix(db, organism):
    """Return (screen_ids, X, M, n_measured) for FULL screens of one organism.

    X : genes x screens, percentile (0.0 placeholder where the gene is absent)
    M : genes x screens, 1.0 where the gene was measured, else 0.0
    Gene universe is restricted to symbols measured in >= 2 of these screens.

    Built by streaming one screen at a time (the DB does the gene-universe
    counting) so peak Python memory stays at one screen, not the full ~29M rows.
    """
    # gene universe: symbols measured in >= N FULL screens — computed in SQL
    genes = [r[0] for r in db.execute(
        """SELECT h.GENE_SYMBOL
           FROM harmonized_scores h
           JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
           WHERE m.ORGANISM_OFFICIAL = ? AND m.COVERAGE_TYPE = 'FULL'
             AND h.PERCENTILE_SCORE IS NOT NULL
           GROUP BY h.GENE_SYMBOL
           HAVING COUNT(DISTINCT h.SCREEN_ID) >= ?""",
        (organism, GENE_UNIVERSE_MIN_SCREENS),
    ).fetchall()]
    if not genes:
        return None
    gene_idx = {g: i for i, g in enumerate(genes)}

    screen_ids = [r[0] for r in db.execute(
        """SELECT SCREEN_ID FROM screen_metadata
           WHERE ORGANISM_OFFICIAL = ? AND COVERAGE_TYPE = 'FULL'
           ORDER BY CAST(SCREEN_ID AS INTEGER)""",
        (organism,),
    ).fetchall()]

    G, S = len(genes), len(screen_ids)
    X = np.zeros((G, S), dtype=np.float32)
    M = np.zeros((G, S), dtype=np.float32)
    for j, sid in enumerate(screen_ids):
        for g, p in db.execute(
            "SELECT GENE_SYMBOL, PERCENTILE_SCORE FROM harmonized_scores "
            "WHERE SCREEN_ID = ? AND PERCENTILE_SCORE IS NOT NULL", (sid,)
        ):
            gi = gene_idx.get(g)
            if gi is not None:
                X[gi, j] = p
                M[gi, j] = 1.0

    n_measured = M.sum(axis=0)  # genes measured per screen (within universe)
    return screen_ids, X, M, n_measured


def pairwise_rho(X, M):
    """All-pairs Pearson correlation of percentile columns over pairwise-complete
    genes (== Spearman, since percentile is a rank). Returns (R, N) S x S."""
    X2 = X * X
    n = M.T @ M                 # shared gene count per pair
    sx = X.T @ M                # sum of screen-i percentiles over genes shared with j
    sy = sx.T                   # symmetric counterpart
    sxy = X.T @ X
    sxx = X2.T @ M
    syy = sxx.T

    with np.errstate(divide="ignore", invalid="ignore"):
        cov = n * sxy - sx * sy
        vx = n * sxx - sx * sx
        vy = n * syy - sy * sy
        R = cov / np.sqrt(vx * vy)
    del X2, sxy, sxx, syy, cov, vx, vy
    return R, n


def continuous_for_organism(db, organism, out_rows, now):
    built = build_percentile_matrix(db, organism)
    if built is None:
        return 0
    screen_ids, X, M, n_measured = built
    S = len(screen_ids)
    log(f"  {organism}: {S} FULL screens, {X.shape[0]} genes in universe — computing {S*(S-1)//2:,} pairs")

    R, N = pairwise_rho(X, M)

    iu, ju = np.triu_indices(S, k=1)            # upper triangle = each pair once
    r = R[iu, ju]
    n = N[iu, ju]
    keep = (n >= MIN_OVERLAP_GENES) & np.isfinite(r) & (np.abs(r) >= RHO_MIN)
    iu, ju, r, n = iu[keep], ju[keep], r[keep], n[keep]
    log(f"  {organism}: {len(r):,} pairs pass (|rho|>={RHO_MIN}, overlap>={MIN_OVERLAP_GENES})")

    # analytic Spearman p-value from (r, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = r * np.sqrt((n - 2) / (1 - r * r))
    pval = 2 * stats.t.sf(np.abs(t), df=n - 2)

    smaller = np.minimum(n_measured[iu], n_measured[ju])
    frac = n / np.maximum(smaller, 1)

    # tail-restricted correlation, per surviving pair (signal lives in the tails)
    tail_present = np.abs(X) > TAIL_CUTOFF        # genes that are a hit in that screen
    for k in range(len(r)):
        i, j = iu[k], ju[k]
        both = (M[:, i] > 0) & (M[:, j] > 0)
        tail = both & (tail_present[:, i] | tail_present[:, j])
        rho_tail = None
        if tail.sum() >= MIN_TAIL_GENES:
            a, b = X[tail, i], X[tail, j]
            if a.std() > 0 and b.std() > 0:
                rho_tail = float(np.corrcoef(a, b)[0, 1])
        out_rows.append((
            screen_ids[i], screen_ids[j], organism, "CONTINUOUS",
            int(n[k]), round(float(frac[k]), 4),
            round(float(r[k]), 4), float(f"{pval[k]:.3e}"),
            round(rho_tail, 4) if rho_tail is not None else None,
            None, None, None, now,
        ))
    return len(r)


# ---------------------------------------------------------------------------
# BINARY mode — any pair involving a HIT_ONLY screen, within one organism
# ---------------------------------------------------------------------------

def binary_for_organism(db, organism, out_rows, now):
    # hit sets for every screen of this organism
    rows = db.execute(
        """SELECT h.SCREEN_ID, h.GENE_SYMBOL
           FROM harmonized_scores h
           JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
           WHERE m.ORGANISM_OFFICIAL = ? AND h.IS_HIT = 1""",
        (organism,),
    ).fetchall()
    hits = {}
    for sid, g in rows:
        hits.setdefault(sid, set()).add(g)

    cov = dict(db.execute(
        "SELECT SCREEN_ID, COVERAGE_TYPE FROM screen_metadata WHERE ORGANISM_OFFICIAL = ?",
        (organism,),
    ).fetchall())

    # genome universe size for Fisher's exact (distinct measured genes in organism)
    N_universe = db.execute(
        """SELECT COUNT(DISTINCT h.GENE_SYMBOL)
           FROM harmonized_scores h
           JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
           WHERE m.ORGANISM_OFFICIAL = ?""",
        (organism,),
    ).fetchone()[0]

    hit_only = sorted([s for s in hits if cov.get(s) == "HIT_ONLY"], key=lambda s: int(s))
    all_screens = sorted(hits.keys(), key=lambda s: int(s))
    log(f"  {organism}: {len(hit_only)} HIT_ONLY screens vs {len(all_screens)} hit-bearing screens")

    seen = set()
    count = 0
    for s1 in hit_only:
        h1 = hits[s1]
        if not h1:
            continue
        for s2 in all_screens:
            if s1 == s2:
                continue
            # both-FULL pairs belong to the continuous path, not here
            if cov.get(s1) == "FULL" and cov.get(s2) == "FULL":
                continue
            key = (s1, s2) if int(s1) < int(s2) else (s2, s1)
            if key in seen:
                continue
            seen.add(key)

            h2 = hits[s2]
            shared = len(h1 & h2)
            if shared < MIN_SHARED_HITS:
                continue
            union = len(h1) + len(h2) - shared
            jaccard = shared / union if union else 0.0
            # P(>= shared overlap by chance) given two hit sets drawn from N genes
            fisher_p = float(stats.hypergeom.sf(shared - 1, N_universe, len(h1), len(h2)))

            out_rows.append((
                key[0], key[1], organism, "BINARY",
                shared, round(shared / min(len(h1), len(h2)), 4),
                None, None, None,
                round(jaccard, 4), float(f"{fisher_p:.3e}"), shared, now,
            ))
            count += 1
    return count


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    db = sqlite3.connect(DB)
    create_schema(db)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    organisms = [r[0] for r in db.execute(
        "SELECT DISTINCT ORGANISM_OFFICIAL FROM screen_metadata WHERE ORGANISM_OFFICIAL != ''"
    ).fetchall()]

    out_rows = []
    n_cont = n_bin = 0
    for org in organisms:
        log(f"CONTINUOUS — {org}")
        n_cont += continuous_for_organism(db, org, out_rows, now)
        log(f"BINARY — {org}")
        n_bin += binary_for_organism(db, org, out_rows, now)

    log(f"Inserting {len(out_rows):,} correlation rows...")
    db.executemany(
        """INSERT INTO correlation_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        out_rows,
    )
    create_indexes(db)
    db.commit()

    print("\n=== Summary ===")
    print(f"  continuous (Spearman) pairs : {n_cont:,}")
    print(f"  binary (Jaccard/Fisher) pairs: {n_bin:,}")
    print(f"  total rows stored            : {len(out_rows):,}")
    print(f"  elapsed                      : {time.time()-t0:.1f}s")
    db.close()
    print("Done.")


if __name__ == "__main__":
    main()
