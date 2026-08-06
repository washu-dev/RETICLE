"""Gene co-essentiality neighbours from CRISPR fitness screens.

Faithful port of prototype/web/app.py `coessential_network()` +
build_coessential_matrix.py. For each organism we build (lazily, once) a
co-essentiality matrix R from all fitness screens, then answer per-gene
neighbour queries by cosine similarity of the L2-normalized fitness profiles.

The heavy lifting is split into two pure, DB-free functions so they can be
unit-tested with tiny synthetic inputs:

  - build_matrix(rows)          -> (R, genes, lean, n_screens)
  - network_from_matrix(...)    -> response dict | None

The DB / mock seam lives in `coessential_network()`.
"""

from typing import Any

import numpy as np

from services.execution import offload

ORG2TAX = {"Homo sapiens": 9606, "Mus musculus": 10090}

# taxid -> {"R": np.ndarray, "genes": list[str], "lean": np.ndarray, "n_screens": int}
_MATRIX_CACHE: dict[int, dict[str, Any]] = {}

_TAX2ORG = {9606: "Homo sapiens", 10090: "Mus musculus"}

_MATRIX_SQL = """
    SELECT h.GENE_SYMBOL AS g, h.SCREEN_ID AS s, h.PERCENTILE_SCORE AS p
    FROM harmonized_scores h
    JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
    JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
    WHERE c.assay_domain = 'fitness' AND m.ORGANISM_OFFICIAL = ?
      AND h.PERCENTILE_SCORE IS NOT NULL
"""


def _lean_label(v: float) -> str:
    """Map a gene's mean fitness lean to a categorical label."""
    if v < -0.15:
        return "essential"
    if v > 0.15:
        return "advantageous"
    return "mixed"


def build_matrix(rows: list) -> tuple[np.ndarray, list[str], np.ndarray, int]:
    """Pure, DB-free construction of the co-essentiality matrix.

    Parameters
    ----------
    rows:
        Iterable of (gene, screen, percentile) triples — accepts mapping rows
        (row["g"]/["s"]/["p"]) or plain tuples/sequences.

    Returns
    -------
    (R, genes, lean, n_screens)
        R:         float32 genes x screens, mean-centered & L2-normalized rows
        genes:     list of gene symbols surviving the coverage filter
        lean:      per-gene nanmean of the raw (coverage-filtered) matrix
        n_screens: number of distinct fitness screens (S)
    """
    def _cell(row: Any, key: str, idx: int) -> Any:
        if hasattr(row, "__getitem__") and not isinstance(row, list | tuple):
            try:
                return row[key]
            except (KeyError, TypeError, IndexError):
                return row[idx]
        return row[idx]

    gene_index: dict[str, int] = {}
    screen_index: dict[Any, int] = {}
    triples: list[tuple[int, int, float]] = []

    for row in rows:
        g = _cell(row, "g", 0)
        s = _cell(row, "s", 1)
        p = _cell(row, "p", 2)
        if g is None or s is None or p is None:
            continue
        gi = gene_index.setdefault(g, len(gene_index))
        si = screen_index.setdefault(s, len(screen_index))
        triples.append((gi, si, float(p)))

    n_genes = len(gene_index)
    n_screens = len(screen_index)

    if n_genes == 0 or n_screens == 0:
        return (
            np.zeros((0, 0), dtype=np.float32),
            [],
            np.zeros((0,), dtype=np.float64),
            n_screens,
        )

    genes_all: list[str] = [""] * n_genes
    for g, gi in gene_index.items():
        genes_all[gi] = g

    # Pivot into genes x screens, NaN where unmeasured.
    M = np.full((n_genes, n_screens), np.nan, dtype=np.float64)
    for gi, si, p in triples:
        M[gi, si] = p

    # Coverage filter: keep genes measured in >= max(30, int(0.11 * S)) screens.
    min_cov = max(30, int(0.11 * n_screens))
    measured = np.sum(~np.isnan(M), axis=1)
    keep = measured >= min_cov

    M = M[keep]
    genes = [genes_all[i] for i in range(n_genes) if keep[i]]

    if M.shape[0] == 0:
        return (
            np.zeros((0, n_screens), dtype=np.float32),
            [],
            np.zeros((0,), dtype=np.float64),
            n_screens,
        )

    # Per-gene lean (nanmean across screens).
    lean = np.nanmean(M, axis=1)

    # Mean-impute each gene's NaNs with its lean, then center by subtracting lean.
    X = np.where(np.isnan(M), lean[:, None], M)
    X = X - lean[:, None]

    # L2-normalize each row; guard against zero norm.
    norms = np.linalg.norm(X, axis=1)
    norms[norms == 0] = 1.0
    R = (X / norms[:, None]).astype(np.float32)

    return R, genes, lean, n_screens


def network_from_matrix(
    R: np.ndarray,
    genes: list[str],
    lean: np.ndarray,
    n_screens: int,
    symbol: str,
    top: int = 14,
    r_min: float = 0.25,
) -> dict | None:
    """Pure, DB-free neighbour query over a prebuilt matrix.

    Returns the response dict, or None if the symbol is not in the matrix.
    """
    # Case-insensitive symbol match.
    upper = symbol.upper()
    qi = next((i for i, g in enumerate(genes) if str(g).upper() == upper), None)
    if qi is None:
        return None

    matched = genes[qi]

    r = R @ R[qi]
    r = np.asarray(r, dtype=np.float64).copy()
    r[qi] = -2.0  # exclude self

    # Neighbours: indices with r >= r_min, top by r.
    cand = np.where(r >= r_min)[0]
    order = cand[np.argsort(-r[cand])][:top]
    neighbour_idx = [int(i) for i in order]

    members = [qi] + neighbour_idx

    nodes = [
        {
            "name": genes[i],
            "lean": _lean_label(float(lean[i])),
            "focus": (i == qi),
        }
        for i in members
    ]

    # Partner-partner edges: pair (a,b) among members with R[a]·R[b] >= 0.30.
    edge_min = max(r_min, 0.30)
    edges = []
    for ai in range(len(members)):
        for bi in range(ai + 1, len(members)):
            a = members[ai]
            b = members[bi]
            score = float(R[a] @ R[b])
            if score >= edge_min:
                edges.append(
                    {
                        "a": genes[a],
                        "b": genes[b],
                        "r": round(score, 3),
                        "score": score,
                    }
                )

    return {
        "symbol": matched,
        "nodes": nodes,
        "edges": edges,
        "n_screens": int(n_screens),
    }


def _mock_network(symbol: str) -> dict:
    """Deterministic offline network: focus node + 2 neighbours + 1 edge."""
    return {
        "symbol": symbol,
        "nodes": [
            {"name": symbol, "lean": "essential", "focus": True},
            {"name": "ATG5", "lean": "essential", "focus": False},
            {"name": "ATG7", "lean": "essential", "focus": False},
        ],
        "edges": [
            {"a": symbol, "b": "ATG5", "r": 0.42, "score": 0.42},
        ],
        "n_screens": 3,
    }


def _get_matrix(taxid: int) -> dict[str, Any]:
    """Lazily build & cache the per-organism matrix (real DB only)."""
    cached = _MATRIX_CACHE.get(taxid)
    if cached is not None:
        return cached

    from services.db_service import db_fetchall

    org = _TAX2ORG.get(taxid, "Homo sapiens")
    rows = db_fetchall(_MATRIX_SQL, (org,))
    R, genes, lean, n_screens = build_matrix(rows)
    cached = {"R": R, "genes": genes, "lean": lean, "n_screens": n_screens}
    _MATRIX_CACHE[taxid] = cached
    return cached


@offload("cpu")
def coessential_network(
    symbol: str,
    taxid: int,
    top: int = 14,
    r_min: float = 0.25,
) -> dict | None:
    """Co-essentiality neighbours for `symbol` in the given organism.

    Offline (USE_PG False): returns a small deterministic network.
    Online: builds/caches the organism matrix and runs the pure query.
    """
    from services.db_service import USE_PG

    if not USE_PG:
        return _mock_network(symbol)

    mat = _get_matrix(taxid)
    return network_from_matrix(
        mat["R"], mat["genes"], mat["lean"], mat["n_screens"],
        symbol, top=top, r_min=r_min,
    )
