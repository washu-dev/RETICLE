import logging

from fastapi import APIRouter, HTTPException, status

from models.gene import GeneDetail
from services.mock_data_service import get_gene_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["genes"])


@router.get("/genes/{symbol}", response_model=GeneDetail)
async def get_gene(symbol: str) -> dict:
    logger.info("GET /api/genes/%s called", symbol)
    detail = await get_gene_detail(symbol.upper())
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gene '{symbol}' not found in reference set",
        )
    return detail.model_dump(by_alias=True)
