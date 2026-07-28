"""Corpus router — live count of screens matching a set of compare-to filters.

GET /api/corpus/count powers the input page's cohort counter ("Comparing
against N screens"). Filters arrive as query params; 'Any'/empty/all-selected
values are no-ops (see corpus_service.build_corpus_where)."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from models.query import CorpusFilters
from services.corpus_service import corpus_count

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["corpus"])


@router.get("/corpus/count")
async def corpus_count_endpoint(
    organism: str = Query("Any"),
    assay_domains: list[str] = Query(default=[], alias="assayDomains"),
    coverage: str = Query("Any"),
    cell_types: list[str] = Query(default=[], alias="cellTypes"),
    modalities: list[str] = Query(default=[]),
    min_shared_genes: int = Query(0, ge=0, alias="minSharedGenes"),
) -> Any:
    filters = CorpusFilters(
        organism=organism,
        assay_domains=assay_domains,
        coverage=coverage,
        cell_types=cell_types,
        modalities=modalities,
        min_shared_genes=min_shared_genes,
    )
    count = corpus_count(filters)
    logger.info("GET /api/corpus/count → %d", count)
    return {"count": count}
