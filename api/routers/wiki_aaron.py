"""Gene-wiki page endpoints (ported from the standalone prototype).

Separate from routers/explorer.py on purpose: that file owns the Explorer page's gene endpoints
(/api/gene, /api/context, /api/network) and is under active development. These four power the
distinct Gene-Wiki page and are kept apart so the two workstreams do not collide in one file.

Like explorer.py, responses keep the prototype's payload shape verbatim (snake_case) so the ported
frontend consumes them unchanged.

  GET /api/gene_wiki                 — the full knowledge-base record for one gene
  GET /api/gene_screen_distribution  — where the gene sits inside a screen's own distribution
  GET /api/gene_predictions          — guilt-by-association GO predictions (deterministic, no LLM)
  GET /api/gene_structure            — AlphaFold + experimental PDB structures
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.gene_wiki_aaron import (
    get_gene_predictions,
    get_gene_screen_distribution,
    get_gene_structure,
    get_gene_wiki,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["gene-wiki"])

# Same symbol rule as routers/explorer.py. Digits are allowed on purpose: the wiki resolver also
# accepts a bare Entrez GeneID.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_SCREEN_ID_RE = re.compile(r"^[0-9]{1,9}$")

_TAXIDS = {9606, 10090}
_SCORES = {"native", "percentile", "robustz"}


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


def _validate_taxid(taxid: int) -> int:
    return taxid if taxid in _TAXIDS else 9606


@router.get("/gene_wiki")
async def gene_wiki(
    gene: str = Query(..., min_length=1, max_length=40),
    taxid: int = Query(9606),
) -> Any:
    """Everything the knowledge base holds for one gene. Pure retrieval — no LLM."""
    gene = _validate_symbol(gene)
    taxid = _validate_taxid(taxid)
    logger.info("GET /api/gene_wiki called with gene=%s taxid=%s", gene, taxid)
    payload = await get_gene_wiki(gene, taxid)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{gene}' not found in the knowledge base",
        )
    return payload


@router.get("/gene_screen_distribution")
async def gene_screen_distribution(
    gene: str = Query(..., min_length=1, max_length=40),
    taxid: int = Query(9606),
    screen: str | None = Query(None, max_length=9),
    score: str = Query("percentile"),
) -> Any:
    """The gene's position within one screen, against that screen's full gene distribution.

    `score` selects which stored normalization the axis uses: percentile (default), robustz, or the
    screen's native score.
    """
    gene = _validate_symbol(gene)
    taxid = _validate_taxid(taxid)
    if score not in _SCORES:
        score = "percentile"
    if screen is not None and screen != "" and not _SCREEN_ID_RE.match(screen):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid screen id",
        )
    logger.info("GET /api/gene_screen_distribution called with gene=%s", gene)
    payload = await get_gene_screen_distribution(gene, taxid, screen or None, score)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No FULL-screen distribution available for '{gene}'",
        )
    return payload


@router.get("/gene_predictions")
async def gene_predictions(
    gene: str = Query(..., min_length=1, max_length=40),
    taxid: int = Query(9606),
) -> Any:
    """Biological processes the gene is likely involved in but is NOT yet annotated with.

    Deterministic guilt-by-association over two orthogonal layers (annotation-independent STRING
    channels + co-essentiality); no LLM. Each prediction ships its supporting genes so the
    hypothesis is auditable.
    """
    gene = _validate_symbol(gene)
    taxid = _validate_taxid(taxid)
    logger.info("GET /api/gene_predictions called with gene=%s", gene)
    return await get_gene_predictions(gene, taxid)


@router.get("/gene_structure")
async def gene_structure(
    gene: str = Query(..., min_length=1, max_length=40),
    taxid: int = Query(9606),
) -> Any:
    """AlphaFold predicted model + experimental PDB entries for the gene's UniProt accession.

    Resolved live from the EBI/RCSB APIs and cached per process; `available` is false when the gene
    has no UniProt accession or neither source returns a model.
    """
    gene = _validate_symbol(gene)
    taxid = _validate_taxid(taxid)
    logger.info("GET /api/gene_structure called with gene=%s", gene)
    return await get_gene_structure(gene, taxid)
