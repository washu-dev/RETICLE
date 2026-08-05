"""
AI narrative endpoints (Phase 5c) — POST /api/interpret, GET /api/reporter_explain.

Both delegate to services.interpret, which talks to WashU's internal LLM gateway.
Responses are the ported prototype's RAW snake_case dicts (not CamelModel). When
the gateway is unconfigured or a call fails the service raises `LlmUnavailable`;
we catch it here and return HTTP 503 with an {error} body, matching the
frontend's error convention — a missing gateway is never a 500.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from services import interpret as interpret_service
from services.llm_client import LlmUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["interpret"])

# Same edge-validation as routers/explorer.py — defense in depth.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

_UNAVAILABLE = {"error": "AI narrative is unavailable (LLM gateway not configured)"}


def _unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=_UNAVAILABLE
    )


@router.post("/interpret")
async def interpret(payload: dict[str, Any]) -> Any:
    """Generate a hypothesis-generating AI narrative for a gene footprint.

    Body is arbitrary JSON (the footprint dict). Returns {model, text, sources}.
    """
    logger.info("POST /api/interpret called (symbol=%s)", (payload or {}).get("symbol"))
    try:
        return interpret_service.interpret(payload or {})
    except LlmUnavailable:
        return _unavailable_response()


@router.get("/reporter_explain")
async def reporter_explain(
    symbol: str = Query(..., min_length=1, max_length=40),
    screens: str = Query("", description="comma-separated screen ids"),
) -> Any:
    """Explain a gene's likely role across a set of reporter screens."""
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Invalid gene symbol"},
        )
    screen_ids = [s.strip() for s in screens.split(",") if s.strip()]
    logger.info("GET /api/reporter_explain called (symbol=%s, n=%d)", symbol, len(screen_ids))
    try:
        return interpret_service.reporter_explain(symbol, screen_ids)
    except LlmUnavailable:
        return _unavailable_response()
