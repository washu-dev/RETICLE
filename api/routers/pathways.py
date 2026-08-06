"""Pathway-enrichment endpoint (POST /api/pathways).

Takes a gene list from the Explorer and returns the pathways over-represented in
it, via Enrichr. Like the other ported Explorer endpoints this returns a RAW
snake_case dict (not a CamelModel) so the ported frontend consumes it unchanged.

The heavy lifting (and all network I/O) lives in services.enrichment; this router
only validates input and shapes the response. Enrichment fails soft, so a valid
request against an unreachable Enrichr still returns 200 with an empty terms list.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.enrichment import enrich_pathways
from services.execution import run_blocking

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pathways"])

# Gene symbols are short alphanumerics with a few allowed separators
# (e.g. TP53, HLA-A, C1orf43, MT-CO1) — same shape as routers/explorer.py.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# Bound the request so a caller can't submit an unbounded list to Enrichr.
_MAX_GENES = 500


class PathwaysRequest(BaseModel):
    genes: list[str] = Field(..., min_length=1)
    library: str = "Reactome_2022"


def _validate_genes(genes: list[str]) -> list[str]:
    if not isinstance(genes, list) or not genes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="genes must be a non-empty list",
        )
    if len(genes) > _MAX_GENES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"too many genes (max {_MAX_GENES})",
        )
    cleaned: list[str] = []
    for g in genes:
        if not isinstance(g, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="each gene must be a string",
            )
        sym = g.strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid gene symbol: {g!r}",
            )
        cleaned.append(sym)
    return cleaned


@router.post("/pathways")
async def pathways(body: PathwaysRequest) -> Any:
    """Pathway enrichment for a gene list via Enrichr."""
    genes = _validate_genes(body.genes)
    logger.info("POST /api/pathways called with %d genes", len(genes))
    terms = await run_blocking(
        enrich_pathways, genes, body.library, workload="external"
    )
    return {"library": body.library, "terms": terms}
