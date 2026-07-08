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

from services.explorer_gene import get_gene_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["explorer"])

# Gene symbols are short alphanumerics with a few allowed separators
# (e.g. TP53, Trp53, HLA-A, C1orf43, MT-CO1). Validate at the edge as
# defense-in-depth — DB access is parameterized regardless.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


@router.get("/gene")
async def gene(symbol: str = Query(..., min_length=1, max_length=40)) -> Any:
    """Per-gene behavior across screens, split by assay domain."""
    symbol = _validate_symbol(symbol)
    logger.info("GET /api/gene called with symbol=%s", symbol)
    payload = await get_gene_payload(symbol)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No screen data for gene '{symbol}'",
        )
    return payload
