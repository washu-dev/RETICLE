"""Co-essentiality endpoint (ported from the standalone prototype).

GET /api/coessential returns a gene's co-essentiality neighbour network,
derived from cosine similarity of L2-normalized CRISPR fitness profiles across
all fitness screens for the organism.

Like the rest of the Explorer surface, this returns the prototype's raw
snake_case payload verbatim (not a CamelModel) so the ported frontend consumes
it unchanged.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.coessential import ORG2TAX, coessential_network

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["coessential"])

# Gene symbols: short alphanumerics with a few allowed separators. Validate at
# the edge as defense-in-depth — DB access is parameterized regardless.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# `org` only ever selects a taxid — restrict to known organisms.
_ORGANISMS = {"Homo sapiens", "Mus musculus"}


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


def _validate_org(org: str) -> str:
    return org if org in _ORGANISMS else "Homo sapiens"


@router.get("/coessential")
async def coessential(
    symbol: str = Query(..., min_length=1, max_length=40),
    org: str = Query("Homo sapiens"),
) -> Any:
    """Gene co-essentiality neighbour network across fitness screens."""
    symbol = _validate_symbol(symbol)
    org = _validate_org(org)
    taxid = ORG2TAX[org]
    logger.info("GET /api/coessential called with symbol=%s org=%s", symbol, org)
    payload = await coessential_network(symbol, taxid)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No co-essentiality data for gene '{symbol}'",
        )
    return payload
