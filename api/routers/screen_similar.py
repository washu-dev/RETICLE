"""Canonical screen-similarity endpoint.

``GET /api/screen_similar`` reads the offline-computed ``screen_similarity``
and ``screen_sim_meta`` tables.  The retired request path loaded all raw scores,
built a dense matrix, and compared every screen synchronously, which could
block the sole API event loop for more than a minute.

The response retains ``weighted`` and ``plain`` aliases used by the legacy
Explorer bundle.  They both refer to the shipped PC1-removed Pearson ``r``;
new clients should use ``r`` and the query-relative ``z`` score directly.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.screen_similarity_aaron import get_screen_similar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["screen-similarity"])

# BioGRID ORCS ids are numeric and currently fit in nine digits.
_SCREEN_RE = re.compile(r"^[0-9]{1,9}$")


def _validate_screen(screen: str) -> str:
    screen = screen.strip()
    if not _SCREEN_RE.match(screen):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid screen id",
        )
    return screen


def _with_legacy_score_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the old Explorer renderer alive while exposing the fast contract.

    Copy the rows instead of modifying the service result in place.  That keeps
    this compatibility concern at the canonical legacy boundary and leaves the
    ``_aaron`` response unchanged.
    """
    return {
        **payload,
        "results": [
            {**row, "weighted": row["r"], "plain": row["r"]}
            for row in payload["results"]
        ],
    }


@router.get("/screen_similar")
async def screen_similar_endpoint(
    screen: str = Query(..., min_length=1, max_length=9),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_same_study: bool = Query(False),
) -> Any:
    """Screens most similar to the query in the precomputed comparable pool."""
    screen = _validate_screen(screen)
    logger.info("GET /api/screen_similar called with screen=%s", screen)
    payload = await get_screen_similar(
        screen,
        limit=limit,
        offset=offset,
        exclude_same_study=exclude_same_study,
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screen {screen} not in the human / fitness / genome-wide pool.",
        )
    return _with_legacy_score_aliases(payload)
