#!/usr/bin/env python3
"""
relatedness_core.py — pure helpers shared by the gene-relatedness stages
(profiler D2, co-essentiality D5). Kept dependency-light (numpy + optional
cupy/scipy) and side-effect free so the selective-gene definition and the
tail/rank transform can NEVER drift between the profiler's projections and the
actual build.
"""

import numpy as np


# ---------------------------------------------------------------------------
# array backend (GPU via cupy when available, else numpy)
# ---------------------------------------------------------------------------

def get_backend(prefer_gpu=True):
    """Return (xp, is_gpu). cupy if importable AND a device is present, else numpy."""
    if prefer_gpu:
        try:
            import cupy as cp
            cp.cuda.runtime.getDeviceCount()   # raises if no device
            return cp, True
        except Exception:
            pass
    return np, False


def to_cpu(a):
    """Move an array to host numpy regardless of backend."""
    return a.get() if hasattr(a, "get") else np.asarray(a)


# ---------------------------------------------------------------------------
# selective-gene classification (shared by D2 profiler and D5 compute)
# ---------------------------------------------------------------------------

def classify_selective(n_measured, n_hits, pan_essential_rate=0.90, min_measured_screens=2):
    """Split genes into selective / pan-essential / pan-inert / insufficient.

    Same rule the profiler projects against, so a config's projected pair counts
    match what D5 actually builds:
      * pan-inert     : never a hit (n_hits == 0)  -> "never moves"
      * pan-essential : hit_rate >= pan_essential_rate AND measured enough
      * insufficient  : measured in < min_measured_screens
      * selective     : everything else (the only genes that carry signal)

    n_measured, n_hits are int arrays aligned to a gene_id array. Returns a dict
    of boolean masks + a summary.
    """
    n_measured = np.asarray(n_measured, dtype=np.int64)
    n_hits = np.asarray(n_hits, dtype=np.int64)
    with np.errstate(divide="ignore", invalid="ignore"):
        hit_rate = np.where(n_measured > 0, n_hits / n_measured, 0.0)

    enough = n_measured >= min_measured_screens
    pan_inert = n_hits == 0
    pan_essential = (hit_rate >= pan_essential_rate) & enough
    selective = enough & ~pan_inert & ~pan_essential

    summary = {
        "total_genes": int(n_measured.size),
        "selective_gene_count": int(selective.sum()),
        "pan_essential_dropped": int(pan_essential.sum()),
        "pan_inert_dropped": int(pan_inert.sum()),
        "insufficient_coverage_dropped": int((~enough & ~pan_inert).sum()),
        "filter": {
            "pan_essential_rate": pan_essential_rate,
            "pan_inert_rule": "n_hit_screens == 0",
            "min_measured_screens": min_measured_screens,
        },
    }
    return {"selective": selective, "pan_essential": pan_essential,
            "pan_inert": pan_inert, "enough": enough, "summary": summary}


# ---------------------------------------------------------------------------
# per-gene rank + tail transform (host/numpy; feeds the GPU masked GEMMs)
# ---------------------------------------------------------------------------

def selective_binary_csr(gene_arr, col_arr, sel_gene_ids):
    """Build a binary CSR (selective_gene × col) matrix from (gene_id, col_id)
    pairs, keeping only selective genes and mapping them to compact row indices
    with vectorized searchsorted. `col_arr` is screen_id (co-hit) or
    publication_id (co-citation). Returns (csr int32, n_cols)."""
    from scipy import sparse
    n_sel = len(sel_gene_ids)
    gene_arr = np.asarray(gene_arr)
    if n_sel == 0 or gene_arr.size == 0:
        return sparse.csr_matrix((n_sel, 0), dtype=np.int32), 0
    order = np.argsort(sel_gene_ids)
    sel_sorted = np.asarray(sel_gene_ids)[order]
    pos = np.clip(np.searchsorted(sel_sorted, gene_arr), 0, n_sel - 1)
    keep = sel_sorted[pos] == gene_arr
    if not keep.any():
        return sparse.csr_matrix((n_sel, 0), dtype=np.int32), 0
    rows = order[pos[keep]]
    _, cols = np.unique(np.asarray(col_arr)[keep], return_inverse=True)
    n_cols = int(cols.max()) + 1 if cols.size else 0
    M = sparse.csr_matrix((np.ones(rows.size, dtype=np.int32), (rows, cols)),
                          shape=(n_sel, n_cols))
    M.data[:] = 1          # collapse any dupes to binary
    return M, n_cols


def prepare_rank_tail(mat, tail_percentile):
    """From a genes×screens percentile matrix (NaN where a gene is not measured
    in a FULL screen), produce the two arrays the tail-restricted Spearman GEMMs
    consume:

      R  : per-gene rank of the value across that gene's measured screens,
           0-filled where not measured (so 0 * mask == 0, no NaN in GEMMs).
      T  : {0,1} tail mask — 1 where the gene's value sits in its own top- or
           bottom-`tail_percentile` (the extremes that carry co-essentiality
           signal; the mid-distribution is noise).

    Spearman = Pearson on ranks; tail-restriction is applied pairwise later via
    T (a pair uses only screens where BOTH genes are in-tail). Rank ties get
    average ranks. NOTE: ranks are global (over the gene's measured screens),
    used over the pairwise co-tail subset — the tractable GEMM form of
    tail-restricted Spearman (documented approximation vs per-pair re-ranking).
    """
    try:
        from scipy.stats import rankdata
        _rank = lambda v: rankdata(v)                     # average ties
    except ImportError:                                    # pragma: no cover
        _rank = lambda v: np.argsort(np.argsort(v)).astype(float) + 1.0  # ordinal

    g, s = mat.shape
    R = np.zeros((g, s), dtype=np.float32)
    T = np.zeros((g, s), dtype=np.float32)
    for i in range(g):
        row = mat[i]
        m = ~np.isnan(row)
        if m.sum() < 2:
            continue
        v = row[m]
        R[i, m] = _rank(v).astype(np.float32)
        lo = np.quantile(v, tail_percentile)
        hi = np.quantile(v, 1.0 - tail_percentile)
        T[i, m] = ((v <= lo) | (v >= hi)).astype(np.float32)
    return R, T
