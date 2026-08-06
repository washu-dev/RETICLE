"""Gene-explorer endpoints (ported from the standalone prototype).

These power the webapp's Explorer page. Unlike the rest of the API, they return
the prototype's payload shape verbatim (snake_case, no camelCase aliasing) so the
ported Explorer frontend consumes them unchanged.

Phase 1 exposes the DB-only `/api/gene` endpoint. Network / context / matrix /
LLM endpoints are added in later phases.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.explorer_context import get_context
from services.explorer_gene import get_gene_payload
from services.explorer_network import get_network

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["explorer"])

# Gene symbols are short alphanumerics with a few allowed separators
# (e.g. TP53, Trp53, HLA-A, C1orf43, MT-CO1). Validate at the edge as
# defense-in-depth — DB access is parameterized regardless.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# `org` only ever selects a NCBI taxid / corpus partition.  The application has
# historically used three vocabularies for it (common name, binomial, and
# taxid), so normalise all supported spellings at the API boundary.  Services
# only receive the canonical binomial and can therefore never silently cross
# from the mouse corpus into the human corpus.
_ORGANISM_ALIASES = {
    "human": "Homo sapiens",
    "homo sapiens": "Homo sapiens",
    "hsapiens": "Homo sapiens",
    "hs": "Homo sapiens",
    "9606": "Homo sapiens",
    "mouse": "Mus musculus",
    "mus musculus": "Mus musculus",
    "mmusculus": "Mus musculus",
    "mm": "Mus musculus",
    "10090": "Mus musculus",
}


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


def _validate_org(org: str | None, *, default_human: bool = True) -> str | None:
    """Return a canonical organism, preserving the legacy auto mode for /gene.

    An omitted ``org`` on ``/api/gene`` historically meant "infer from the
    matching rows".  Keep that behavior for old clients, while an explicit
    value is now authoritative.  Unknown explicit values are rejected instead
    of being relabelled as human data.
    """
    if org is None or not org.strip():
        return "Homo sapiens" if default_human else None
    normalised = _ORGANISM_ALIASES.get(org.strip().lower())
    if normalised is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown organism '{org}' — expected human or mouse",
        )
    return normalised


@router.get("/gene")
async def gene(
    symbol: str = Query(..., min_length=1, max_length=40),
    org: str | None = Query(None),
) -> Any:
    """Per-gene behavior across screens, split by assay domain."""
    symbol = _validate_symbol(symbol)
    canonical_org = _validate_org(org, default_human=False)
    logger.info("GET /api/gene called with symbol=%s org=%s", symbol, canonical_org or "auto")
    payload = await get_gene_payload(symbol, canonical_org)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No screen data for gene '{symbol}'",
        )
    return payload


@router.get("/context")
async def context(
    symbol: str = Query(..., min_length=1, max_length=40),
    org: str = Query("Homo sapiens"),
) -> Any:
    """External context: annotation, darkness rating, STRING partners."""
    symbol = _validate_symbol(symbol)
    logger.info("GET /api/context called with symbol=%s", symbol)
    canonical_org = _validate_org(org)
    assert canonical_org is not None
    return await get_context(symbol, canonical_org)


@router.get("/network")
async def network(
    symbol: str = Query(..., min_length=1, max_length=40),
    org: str = Query("Homo sapiens"),
) -> Any:
    """STRING interaction network colored by CRISPR fitness behavior."""
    symbol = _validate_symbol(symbol)
    logger.info("GET /api/network called with symbol=%s", symbol)
    canonical_org = _validate_org(org)
    assert canonical_org is not None
    return await get_network(symbol, canonical_org)
