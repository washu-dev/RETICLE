"""
screen_sim.py — SCREEN-vs-SCREEN similarity for the query corpus feature.

Faithful port of prototype/web/app.py::screen_similar + build_screen_matrix.py.

Pool: Homo sapiens · assay_domain='fitness' · COVERAGE_TYPE='FULL' — the clean
apples-to-apples genome-wide fitness screens. We keep the RAW percentile per
gene per screen (NaN where unmeasured, NO imputation / normalisation) so that a
WEIGHTED Pearson (weight = both screens' extremeness) can be computed on demand
for one query screen vs all others.

The pool matrix is built lazily on first use and cached in a module-level
singleton. When USE_PG is False (tests / CI / local, no database) every public
entry point returns a small deterministic mock payload instead of touching the
database.
"""

from typing import Any

import numpy as np

# Coverage thresholds (mirror build_screen_matrix.py).
MIN_GENES_PER_SCREEN = 500       # a genome-wide screen worth comparing
MIN_SCREENS_PER_GENE = 50        # a gene must appear widely enough to matter
MIN_OVERLAP = 200                # shared measured genes required to compare a pair

# Module-level lazy singleton for the pool matrix.
#   None  -> not yet built
#   False -> built but empty (no pool available)
#   dict  -> {"M", "genes", "screens", "sidx", "meta"}
_POOL: Any = None


# ---------------------------------------------------------------------------
# Pure, DB-free math (unit-testable)
# ---------------------------------------------------------------------------

def weighted_pearson(a: np.ndarray, c: np.ndarray) -> float | None:
    """Weighted Pearson correlation with weight = |a| * |c|.

    Both screens being extreme on a gene drives the weight up, so the
    informative tail genes dominate and the ~random middle is down-weighted.

    Returns None if the total weight is zero or either weighted variance is
    zero (undefined correlation).
    """
    a = np.asarray(a, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    w = np.abs(a) * np.abs(c)
    sw = w.sum()
    if sw <= 0:
        return None
    aw = np.average(a, weights=w)
    cw = np.average(c, weights=w)
    cov = np.average((a - aw) * (c - cw), weights=w)
    vaw = np.average((a - aw) ** 2, weights=w)
    vcw = np.average((c - cw) ** 2, weights=w)
    if vaw > 0 and vcw > 0:
        return float(cov / np.sqrt(vaw * vcw))
    return None


def plain_pearson(a: np.ndarray, c: np.ndarray) -> float | None:
    """Unweighted Pearson correlation; None if either variance is zero."""
    a = np.asarray(a, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    am, cm = a.mean(), c.mean()
    va = ((a - am) ** 2).mean()
    vc = ((c - cm) ** 2).mean()
    if va > 0 and vc > 0:
        return float(((a - am) * (c - cm)).mean() / np.sqrt(va * vc))
    return None


# ---------------------------------------------------------------------------
# Lazy pool construction
# ---------------------------------------------------------------------------

def _build_pool() -> Any:
    """Build the gene x screen RAW-percentile matrix from the DB. Returns a
    dict on success, or False when there is nothing to compare."""
    from services.db_service import db_fetchall

    # Per-screen labels for the pool (author / cell_line / pmid).
    label_rows = db_fetchall("""
        SELECT m.SCREEN_ID AS s, m.AUTHOR AS author,
               m.CELL_LINE AS cell_line, c.pmid AS pmid
        FROM screen_metadata m
        JOIN screen_metadata_curated c ON m.SCREEN_ID = c.screen_id
        WHERE m.ORGANISM_OFFICIAL = 'Homo sapiens'
          AND c.assay_domain = 'fitness'
          AND m.COVERAGE_TYPE = 'FULL'
    """)
    labels = {
        str(r["s"]): {
            "author": str(r["author"] or ""),
            "cell_line": str(r["cell_line"] or ""),
            "pmid": str(r["pmid"] or ""),
        }
        for r in label_rows
    }

    # Percentile cells for the pool screens.
    cell_rows = db_fetchall("""
        SELECT h.GENE_SYMBOL AS g, h.SCREEN_ID AS s, h.PERCENTILE_SCORE AS p
        FROM harmonized_scores h
        JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
        JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
        WHERE m.ORGANISM_OFFICIAL = 'Homo sapiens'
          AND c.assay_domain = 'fitness'
          AND m.COVERAGE_TYPE = 'FULL'
          AND h.PERCENTILE_SCORE IS NOT NULL
    """)
    if not cell_rows:
        return False

    gidx: dict[str, int] = {}
    genes: list[str] = []
    sidx: dict[str, int] = {}
    screens: list[str] = []
    gi_l: list[int] = []
    si_l: list[int] = []
    val_l: list[float] = []
    for row in cell_rows:
        gene = str(row["g"])
        sid = str(row["s"])
        pct = row["p"]
        if pct is None:
            continue
        gi = gidx.get(gene)
        if gi is None:
            gi = len(genes)
            gidx[gene] = gi
            genes.append(gene)
        sj = sidx.get(sid)
        if sj is None:
            sj = len(screens)
            sidx[sid] = sj
            screens.append(sid)
        gi_l.append(gi)
        si_l.append(sj)
        val_l.append(float(pct))

    G, S = len(genes), len(screens)
    if G == 0 or S == 0:
        return False

    M = np.full((G, S), np.nan, dtype=np.float32)
    M[np.asarray(gi_l), np.asarray(si_l)] = np.asarray(val_l, dtype=np.float32)

    # Drop under-covered screens (columns) then rare genes (rows).
    scr_obs = (~np.isnan(M)).sum(0)
    keep_s = scr_obs >= MIN_GENES_PER_SCREEN
    M = M[:, keep_s]
    screens = [s for s, k in zip(screens, keep_s, strict=False) if k]
    gene_obs = (~np.isnan(M)).sum(1)
    keep_g = gene_obs >= MIN_SCREENS_PER_GENE
    M = M[keep_g]
    genes = [g for g, k in zip(genes, keep_g, strict=False) if k]

    if M.shape[1] == 0:
        return False

    # Per-screen meta aligned to the filtered columns.
    meta: list[dict] = []
    for j, sid in enumerate(screens):
        lab = labels.get(sid, {"author": "", "cell_line": "", "pmid": ""})
        n_genes = int((~np.isnan(M[:, j])).sum())
        meta.append({
            "author": lab["author"],
            "cell_line": lab["cell_line"],
            "pmid": lab["pmid"],
            "n_genes": n_genes,
        })

    return {
        "M": M,
        "genes": genes,
        "screens": screens,
        "sidx": {s: i for i, s in enumerate(screens)},
        "meta": meta,
    }


def _load_pool() -> Any:
    """Return the cached pool, building it on first call."""
    global _POOL
    if _POOL is None:
        _POOL = _build_pool()
    return _POOL


def _screen_label(meta_row: dict) -> dict:
    author = meta_row.get("author") or ""
    cell = meta_row.get("cell_line") or ""
    pmid = meta_row.get("pmid") or ""
    n_genes = meta_row.get("n_genes")
    return {
        "author": str(author) or "—",
        "cell_line": str(cell) or "—",
        "pmid": str(pmid) or "",
        "n_genes": int(n_genes) if isinstance(n_genes, int) else None,
    }


# ---------------------------------------------------------------------------
# Public query entry point
# ---------------------------------------------------------------------------

def _mock_payload(screen_id: str, limit: int, offset: int) -> dict:
    """Deterministic offline payload (query + 2 results)."""
    results = [
        {
            "screen_id": "MOCK-0002",
            "weighted": 0.842,
            "plain": 0.771,
            "overlap": 1820,
            "author": "Zhao",
            "cell_line": "THP-1",
            "pmid": "33782614",
            "n_genes": 1912,
        },
        {
            "screen_id": "MOCK-0003",
            "weighted": 0.615,
            "plain": 0.548,
            "overlap": 1204,
            "author": "Lin",
            "cell_line": "HEK293T",
            "pmid": "35124892",
            "n_genes": 1650,
        },
    ]
    n_total = len(results)
    return {
        "query": {
            "screen_id": screen_id,
            "author": "Orvedahl",
            "cell_line": "HeLa",
            "pmid": "31097699",
            "n_genes": 1847,
        },
        "n_pool": 3,
        "n_total": n_total,
        "offset": offset,
        "results": results[offset:offset + limit],
    }


def screen_similar(
    screen_id: str,
    limit: int = 50,
    offset: int = 0,
    min_overlap: int = MIN_OVERLAP,
) -> dict | None:
    """Screens most similar to `screen_id`, ranked by weighted Pearson.

    Returns None when the query screen is not in the pool (router -> 404).
    """
    from services.db_service import USE_PG

    limit = min(200, max(1, int(limit)))
    offset = max(0, int(offset))

    if not USE_PG:
        # No database offline: return a deterministic payload so the endpoint
        # test passes. The query id echoes the (validated) input screen id.
        return _mock_payload(str(screen_id).strip(), limit, offset)

    d = _load_pool()
    if not d:
        return None
    qi = d["sidx"].get(str(screen_id).strip())
    if qi is None:
        return None

    M, screens, meta = d["M"], d["screens"], d["meta"]
    q = M[:, qi]
    qmask = ~np.isnan(q)

    rows: list[dict] = []
    for j in range(M.shape[1]):
        if j == qi:
            continue
        b = M[:, j]
        m = qmask & ~np.isnan(b)
        n = int(m.sum())
        if n < min_overlap:
            continue
        a, c = q[m], b[m]
        weighted = weighted_pearson(a, c)
        if weighted is None:
            continue
        plain = plain_pearson(a, c)
        lab = _screen_label(meta[j])
        rows.append({
            "screen_id": screens[j],
            "weighted": round(weighted, 3),
            "plain": round(plain, 3) if plain is not None else None,
            "overlap": n,
            **lab,
        })

    rows.sort(key=lambda r: -r["weighted"])
    return {
        "query": {"screen_id": screens[qi], **_screen_label(meta[qi])},
        "n_pool": int(M.shape[1]),
        "n_total": len(rows),
        "offset": offset,
        "results": rows[offset:offset + limit],
    }
