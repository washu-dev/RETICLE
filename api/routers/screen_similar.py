"""Screen-vs-screen similarity endpoint (ported from the standalone prototype).

GET /api/screen_similar returns the screens most similar to a query corpus
screen, ranked by a weighted Pearson over shared genes. Like the other ported
Explorer endpoints it returns the prototype's raw snake_case payload verbatim.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.screen_sim import screen_similar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["screen-similarity"])

# BioGRID screen ids are short digit strings. Validate at the edge as
# defense-in-depth — DB access is parameterized regardless.
_SCREEN_RE = re.compile(r"^[0-9]{1,40}$")


def _validate_screen(screen: str) -> str:
    screen = screen.strip()
    if not _SCREEN_RE.match(screen):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid screen id",
        )
    return screen


@router.get("/screen_similar")
async def screen_similar_endpoint(
    screen: str = Query(..., min_length=1, max_length=40),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Any:
    """Screens most similar to the query screen (human · fitness · genome-wide)."""
    screen = _validate_screen(screen)
    logger.info("GET /api/screen_similar called with screen=%s", screen)
    payload = screen_similar(screen, limit=limit, offset=offset)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screen {screen} not in the human · fitness · genome-wide pool.",
        )
    return payload
