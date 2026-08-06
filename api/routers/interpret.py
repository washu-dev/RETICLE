"""
AI narrative endpoints (Phase 5c) — POST /api/interpret, GET /api/reporter_explain.

Both canonical routes delegate to the current WashU Messages/Claude service.
The retired OpenAI-compatible GPT gateway remains in ``services.interpret``
only for its pure prompt helpers and is no longer on a request path. Responses
are RAW snake_case dicts (not CamelModel). Gateway failures retain the legacy
HTTP 503 ``{error}`` contract so the frontend can degrade gracefully.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from services.llm_analysis_aaron import get_interpret, get_reporter_explain
from services.llm_client_aaron import LLMUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["interpret"])

# Same edge-validation as routers/explorer.py — defense in depth.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_SCREEN_ID_RE = re.compile(r"^[0-9]{1,9}$")
_MAX_SCREENS = 6

_UNAVAILABLE = {
    "error": "AI narrative is unavailable (LLM gateway or model access unavailable)"
}


def _unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=_UNAVAILABLE
    )


@router.post("/interpret")
async def interpret(payload: dict[str, Any]) -> Any:
    """Generate a hypothesis-generating AI narrative for a gene footprint.

    Body is arbitrary JSON (the footprint dict). Returns {model, text, sources}.
    """
    raw_symbol = (payload or {}).get("symbol")
    symbol = raw_symbol.strip() if isinstance(raw_symbol, str) else ""
    if not _SYMBOL_RE.match(symbol):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Invalid or missing gene symbol"},
        )
    logger.info("POST /api/interpret called (symbol=%s)", symbol)
    data = {
        "organism": "Homo sapiens",
        "fitness": None,
        "stress": None,
        "reporter": {"n": 0, "ledger": []},
        **(payload or {}),
        "symbol": symbol,
    }
    try:
        return await get_interpret(data)
    except LLMUnavailable:
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
    screen_ids = [s.strip() for s in screens.split(",") if s.strip()][:_MAX_SCREENS]
    if not screen_ids or any(not _SCREEN_ID_RE.match(sid) for sid in screen_ids):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Invalid or missing screen ids"},
        )
    logger.info("GET /api/reporter_explain called (symbol=%s, n=%d)", symbol, len(screen_ids))
    try:
        return await get_reporter_explain(symbol, screen_ids)
    except LLMUnavailable:
        return _unavailable_response()
