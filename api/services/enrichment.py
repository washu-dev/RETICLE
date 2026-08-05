"""Pathway enrichment via Enrichr (https://maayanlab.cloud/Enrichr).

The Explorer's "pathways" panel takes a gene list (e.g. the co-hit / dark-gene
set for a query) and asks Enrichr which annotated pathways are over-represented.

There is no shared enrichment helper in the codebase — external_sources.py talks
only to STRING/NCBI — so this module is self-contained. It uses httpx and fails
soft: every public entry point returns [] on empty input, network error, or any
malformed response, and NEVER raises into the web layer.

The two-step Enrichr flow:
  1. POST {ENRICHR}/addList  (multipart form) -> {"userListId": <int>}
  2. GET  {ENRICHR}/enrich?userListId=<id>&backgroundType=<library>
         -> {<library>: [[rank, term, pvalue, zscore, combined, genes[], adj_p, ...], ...]}

Row mapping / filtering (kept in a pure function for unit testing without a
network round-trip): map each row to a small dict, keep rows with
adj_p_value <= 0.05, sort by combined_score desc, take the top 15.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENRICHR = "https://maayanlab.cloud/Enrichr"

# Gene-set libraries the Explorer is allowed to query.
_LIBRARIES = {"Reactome_2022", "GO_Biological_Process_2021"}
_DEFAULT_LIBRARY = "Reactome_2022"

ADJ_P_CUTOFF = 0.05
TOP_N = 15
_TIMEOUT = 20.0


def _resolve_library(library: str) -> str:
    return library if library in _LIBRARIES else _DEFAULT_LIBRARY


def _to_float(value: Any) -> float:
    """Coerce an Enrichr numeric cell to float, defaulting to 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def map_enrichr_rows(rows: Any) -> list[dict]:
    """Pure transform: Enrichr result rows -> filtered/sorted list of dicts.

    Each Enrichr row is
      [rank, term, pvalue, zscore, combined_score, overlapping_genes[], adj_pvalue, ...]
    We keep rows with adj_p_value <= 0.05, sort by combined_score desc, take top 15.
    No I/O — safe to unit-test with a canned list.
    """
    mapped: list[dict] = []
    if not isinstance(rows, list):
        return mapped

    for row in rows:
        # A well-formed row needs at least through the adj_pvalue at index 6.
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue
        genes = row[5]
        overlap = [str(g) for g in genes] if isinstance(genes, (list, tuple)) else []
        adj_p = _to_float(row[6])
        if adj_p > ADJ_P_CUTOFF:
            continue
        mapped.append(
            {
                "term": str(row[1]),
                "p_value": _to_float(row[2]),
                "adj_p_value": adj_p,
                "combined_score": _to_float(row[4]),
                "overlap_genes": overlap,
            }
        )

    mapped.sort(key=lambda r: r["combined_score"], reverse=True)
    return mapped[:TOP_N]


def enrich_pathways(genes: list[str], library: str = _DEFAULT_LIBRARY) -> list[dict]:
    """Return the top enriched pathways for `genes`, or [] on any failure.

    Fails soft: empty input, HTTP error, non-2xx status, or malformed JSON all
    yield []. Never raises.
    """
    if not genes:
        return []

    clean = [str(g).strip() for g in genes if str(g).strip()]
    if not clean:
        return []

    lib = _resolve_library(library)

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            add_resp = client.post(
                f"{ENRICHR}/addList",
                files={
                    "list": (None, "\n".join(clean)),
                    "description": (None, "RETICLE"),
                },
            )
            add_resp.raise_for_status()
            user_list_id = add_resp.json().get("userListId")
            if user_list_id is None:
                return []

            enrich_resp = client.get(
                f"{ENRICHR}/enrich",
                params={"userListId": user_list_id, "backgroundType": lib},
            )
            enrich_resp.raise_for_status()
            payload = enrich_resp.json()
    except Exception:  # noqa: BLE001 — fail soft, never leak into the web layer
        logger.warning("Enrichr enrichment failed for %d genes", len(clean), exc_info=True)
        return []

    if not isinstance(payload, dict):
        return []
    return map_enrichr_rows(payload.get(lib, []))
