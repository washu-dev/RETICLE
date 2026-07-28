"""Screen-detail router.

GET /api/screen/{screen_id} — a screen's metadata + its (capped) gene list, so
the results UI can open a matched screen and drill into its genes."""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, status

from services.screen_detail import get_screen_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["screen"])

# BioGRID ORCS screen ids are short digit strings. Validate at the edge as
# defense-in-depth — DB access is parameterized regardless.
_SCREEN_RE = re.compile(r"^[0-9]{1,40}$")


@router.get("/screen/{screen_id}")
async def screen_detail_endpoint(screen_id: str) -> Any:
    sid = screen_id.strip()
    if not _SCREEN_RE.match(sid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid screen id",
        )
    logger.info("GET /api/screen/%s", sid)
    detail = get_screen_detail(sid)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screen {sid} not found.",
        )
    return detail.model_dump(by_alias=True)
