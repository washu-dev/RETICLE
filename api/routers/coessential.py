"""Canonical co-essentiality endpoint.

``GET /api/coessential`` is intentionally backed by the precomputed
``net_edge`` tables.  The former implementation lazily materialised the whole
gene-by-screen matrix from ``harmonized_scores`` and then multiplied the dense
matrix for every cold process.  Besides being much slower, that synchronous
work ran on the event-loop thread and could make every route (including
``/api/health``) unresponsive.

The ``/api/coessential_aaron`` compatibility alias is kept in
``routers.screens_aaron``.  Both public paths now use the same fast service and
return the same backwards-compatible graph fields.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.coessential_network_aaron import get_coessential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["coessential"])

# Gene symbols: short alphanumerics with a few allowed separators. Validate at
# the edge as defense-in-depth -- DB access is parameterized regardless.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# Callers use three vocabularies: short names, full binomials, and taxids.
# Normalise all of them before selecting the fixed net_edge table name.
_ORGANISM_ALIASES = {
    "human": "human",
    "homo sapiens": "human",
    "hsapiens": "human",
    "hs": "human",
    "9606": "human",
    "mouse": "mouse",
    "mus musculus": "mouse",
    "mmusculus": "mouse",
    "mm": "mouse",
    "10090": "mouse",
}


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


def _validate_organism(organism: str | None) -> str:
    """Return the service's ``human``/``mouse`` spelling.

    Missing or blank means human for backwards compatibility.  A supplied but
    unknown value must not silently serve a plausible-looking human graph.
    """
    if organism is None or organism.strip() == "":
        return "human"
    normalised = _ORGANISM_ALIASES.get(organism.strip().lower())
    if normalised is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown organism '{organism}' -- expected human or mouse",
        )
    return normalised


@router.get("/coessential")
async def coessential(
    symbol: str = Query(..., min_length=1, max_length=40),
    org: str | None = Query(None),
    organism: str | None = Query(None),
) -> Any:
    """Gene co-essentiality neighbours from the precomputed edge network."""
    symbol = _validate_symbol(symbol)
    organism = _validate_organism(organism or org)
    logger.info(
        "GET /api/coessential called with symbol=%s organism=%s",
        symbol,
        organism,
    )
    payload = await get_coessential(symbol, organism)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No co-essentiality data for gene '{symbol}'",
        )
    return payload
