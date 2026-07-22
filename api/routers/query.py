import logging
from typing import Any

from fastapi import APIRouter

from models.query import QueryRequest, QueryResponse
from services.mock_data_service import run_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_genes(request: QueryRequest) -> Any:
    logger.info("POST /api/query called with %d genes", len(request.genes))
    result = await run_query(request)
    return result.model_dump(by_alias=True)
