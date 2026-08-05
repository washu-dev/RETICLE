"""LLM-backed analysis endpoints (ported from the standalone prototype).

Kept in their own router — separate from routers/explorer.py, routers/screens_aaron.py and
routers/wiki_aaron.py — because these are the only four endpoints that call OUT to the WashU AI
gateway. Every other endpoint is pure retrieval, so isolating the ones that can fail for network
reasons (the gateway is reachable from the WashU network only) keeps that failure mode in one file
and keeps the deterministic routers free of it.

As elsewhere, responses keep the prototype's payload shape verbatim (snake_case) so the ported
frontend consumes them unchanged. The gateway is OpenAI-compatible, not Anthropic; model choice
lives in services/llm_client_aaron.py, never here.

  GET  /api/screen_analysis   — per-phenotype read of a gene's CRISPR-screen hits
  GET  /api/reporter_explain  — grounded synthesis of a gene's role in one reporter's process
  GET  /api/net_predict       — functions a gene likely has, from its co-essential partners
  POST /api/interpret         — RAG interpretation of a whole /api/gene payload (the request body)

Failure contract, matching the prototype: anything the gateway refuses becomes a 502 whose detail
carries the endpoint's own prefix plus a diagnostic hint for the two operational failures we
actually hit (403 = off the WashU network, 402 = gateway out of budget). Nothing in that detail
comes from the gateway credentials — services/llm_client_aaron.py raises LLMUnavailable with a
sanitized message, and this module never touches a secret.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

# The default network context ("all" / "mouse") is owned by the network service — reuse it rather
# than restating the mapping, since get_net_predict() takes a concrete context, not None.
from services.coessential_network_aaron import _default_context
from services.llm_analysis_aaron import (
    get_interpret,
    get_net_predict,
    get_reporter_explain,
    get_screen_analysis,
)
from services.llm_client_aaron import LLMUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["llm-analysis"])

# Same symbol rule as routers/explorer.py and the sibling _aaron routers.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# BioGRID ORCS screen ids are numeric. Validated at the edge as defense-in-depth — the service layer
# binds them as parameters regardless.
_SCREEN_ID_RE = re.compile(r"^[0-9]{1,9}$")

# `context` picks a stored net_edge partition ("all", "domain:fitness", "DDR·genotoxic", ...). It
# reaches SQL only as a bound parameter, but keep the surface tight anyway.
_CONTEXT_RE = re.compile(r"^[A-Za-z0-9:·._-]{1,40}$")

_TAXIDS = {9606, 10090}
_ORGANISMS = {"human", "mouse"}

# At most six reporter screens go into one explanation, as in the prototype.
_MAX_SCREENS = 6

# Gateway hints. DELIBERATELY not byte-identical to the prototype, which is inconsistent here for
# historical reasons rather than by design: its four handlers spell the 403 hint three different
# ways ("WashU network (LLM gateway...)", "WashU network (gateway...)", "WashU VPN (gateway...)"),
# and only /api/net_predict ever grew a 402 branch. Since 402 is what every call hits today, an
# unexplained "You have reached your total spend amount" on the other three would be the single
# most confusing thing a user could see. Both hints therefore apply to all four endpoints, with one
# wording. Nothing parses these strings — the frontend only displays them.
_HINT_OFF_NETWORK = "  Connect the WashU network (LLM gateway is WashU-only) and retry."
_HINT_OUT_OF_BUDGET = (
    "  The WashU LLM gateway has reached its spend limit — ask the team to top it up."
)


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


def _validate_organism(organism: str) -> str:
    return organism if organism in _ORGANISMS else "human"


def _validate_context(context: str | None) -> str | None:
    if context is None or context == "":
        return None
    if not _CONTEXT_RE.match(context):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid context",
        )
    return context


def _parse_screens(screens: str) -> list[str]:
    """Comma-separated screen ids -> a validated list, capped at six (prototype: `screens[:6]`).

    The cap is applied BEFORE validation so a long tail of ids is dropped, not rejected — same
    behaviour the prototype's slice gives.
    """
    ids = [s.strip() for s in screens.split(",") if s.strip()][:_MAX_SCREENS]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing screen ids",
        )
    for sid in ids:
        if not _SCREEN_ID_RE.match(sid):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid screen id",
            )
    return ids


def _err(status_code: int, message: str) -> JSONResponse:
    """An error body carrying BOTH keys: ``error`` and ``detail``.

    The ported frontend reads ``error`` — explorerBundle.js does `if(d.error)` for
    /api/reporter_explain and `j.error||'Interpretation unavailable.'` for /api/interpret, because
    it was written against the prototype, which sent {"error": ...}. FastAPI's HTTPException sends
    {"detail": ...} instead, so raising one here would mean the 402/403 hints this module exists to
    surface never reach the screen: /api/interpret would show a generic string and
    /api/reporter_explain would fall through its `if(d.error)` guard and render an empty "AI
    summary" box — a failure that looks like a success.

    Emitting both keys fixes the frontend without changing the shape any API client or the OpenAPI
    docs already expect, and without touching a shared exception handler in main.py (which would
    alter every teammate route's error contract). Validation errors are left in FastAPI's standard
    422 shape: they are unreachable from the UI, which only ever sends symbols from its own data.
    """
    return JSONResponse(status_code=status_code, content={"error": message, "detail": message})


def _gateway_error(prefix: str, exc: Exception) -> JSONResponse:
    """Turn a gateway/service failure into the prototype's 502 with its diagnostic hint.

    Prefer LLMUnavailable.status over sniffing the message; keep the substring checks as the
    fallback for plain exceptions that never reached the transport layer.
    """
    msg = str(exc)
    code = getattr(exc, "status", None)
    if code == 403 or "403" in msg or "Forbidden" in msg:
        hint = _HINT_OFF_NETWORK
    elif code == 402 or "402" in msg or "spend amount" in msg:
        hint = _HINT_OUT_OF_BUDGET
    else:
        hint = ""
    logger.warning("LLM gateway failure (%s, status=%s): %s", type(exc).__name__, code, msg)
    return _err(status.HTTP_502_BAD_GATEWAY, f"{prefix}{msg}{hint}")


class InterpretRequest(BaseModel):
    """The /api/gene payload, posted back verbatim.

    Only the fields the prompt builder reads are declared; everything else the frontend happens to
    send is carried through untouched (extra="allow") rather than rejected, because the whole dict
    is handed to the prompt builder exactly as the prototype did.
    """

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(..., min_length=1, max_length=40)
    # The full organism name from screen metadata ("Homo sapiens" / "Mus musculus"), NOT the
    # human/mouse slug the network endpoints use — do not validate it against _ORGANISMS.
    organism: str | None = Field(None, max_length=64)
    fitness: dict[str, Any] | None = None
    stress: dict[str, Any] | None = None
    reporter: dict[str, Any] | None = None


@router.get("/screen_analysis")
async def screen_analysis(
    gene: str = Query(..., min_length=1, max_length=40),
    taxid: int = Query(9606),
) -> Any:
    """Per-phenotype interpretation of ONLY this gene's BioGRID CRISPR-screen hits.

    The single piece of AI text on the gene-wiki page. An unknown gene is not an error here — the
    payload reports `found: false`, matching the prototype.
    """
    gene = _validate_symbol(gene)
    taxid = _validate_taxid(taxid)
    logger.info("GET /api/screen_analysis called with gene=%s taxid=%s", gene, taxid)
    try:
        return await get_screen_analysis(gene, taxid)
    except LLMUnavailable as exc:
        return _gateway_error("Screen analysis unavailable: ", exc)
    except HTTPException:
        raise
    except Exception as exc:
        return _gateway_error("Screen analysis unavailable: ", exc)


@router.get("/reporter_explain_aaron")
async def reporter_explain(
    symbol: str = Query(..., min_length=1, max_length=40),
    # Generous on purpose: the frontend sends the row's FULL screen-id list uncapped
    # (explorerBundle.js builds data-screens from every hit), and _parse_screens is what applies
    # the prototype's 6-id cap. A tight bound here would 422 exactly the well-studied genes with
    # the most hits — the prototype answered those from their first six ids. What actually reaches
    # SQL is bounded by that slice plus the per-id numeric check, not by this length.
    screens: str = Query(..., min_length=1, max_length=4000),
) -> Any:
    """Whether the gene's KNOWN function explains the process it scored in, for one reporter row.

    Extraction, not generation: grounded only in the curated summary, STRING partners and the
    screen papers' own abstracts. `screens` is comma-separated and capped at six ids.
    """
    symbol = _validate_symbol(symbol)
    screen_ids = _parse_screens(screens)
    logger.info(
        "GET /api/reporter_explain called with symbol=%s screens=%s", symbol, ",".join(screen_ids)
    )
    try:
        return await get_reporter_explain(symbol, screen_ids)
    except LLMUnavailable as exc:
        return _gateway_error("Explanation unavailable: ", exc)
    except HTTPException:
        raise
    except Exception as exc:
        return _gateway_error("Explanation unavailable: ", exc)


@router.get("/net_predict")
async def net_predict(
    gene: str = Query(..., min_length=1, max_length=40),
    organism: str = Query("human"),
    context: str | None = Query(None, max_length=40),
    reciprocal: bool = Query(True),
) -> Any:
    """Functions the gene likely shares with its co-essential partners but is not annotated with.

    Guilt-by-association over OUR OWN BioGRID co-essentiality network (not STRING, not DepMap):
    the partners' curated functions are the evidence, and every returned prediction cites the
    partners that support it.
    """
    gene = _validate_symbol(gene)
    organism = _validate_organism(organism)
    ctx = _validate_context(context) or _default_context(organism)
    logger.info(
        "GET /api/net_predict called with gene=%s organism=%s context=%s reciprocal=%s",
        gene, organism, ctx, reciprocal
    )
    try:
        payload = await get_net_predict(gene, ctx, organism, reciprocal_only=reciprocal)
    except LLMUnavailable as exc:
        return _gateway_error("Function prediction unavailable: ", exc)
    except HTTPException:
        raise
    except Exception as exc:
        return _gateway_error("Function prediction unavailable: ", exc)
    if payload is None:
        return _err(
            status.HTTP_404_NOT_FOUND,
            f"“{gene}” has no co-essential partners in this context to reason from.",
        )
    return payload


@router.post("/interpret_aaron")
async def interpret(payload: InterpretRequest) -> Any:
    """RAG interpretation of a gene's whole screen signal — the Explore page's AI paragraph.

    The request body is the /api/gene payload itself; it is combined with live external context
    (curated summary, darkness, STRING partners) and PubMed abstracts, and the answer cites the
    PMIDs it was grounded in.
    """
    symbol = _validate_symbol(payload.symbol)
    # exclude_unset: a field the client never sent must stay ABSENT, not become None.
    # build_rag_prompt does p["organism"]; with a materialized None it would emit
    # "GENE: TP53 (None)" and silently enrich against human, spending a gateway call on a
    # mis-grounded answer. Absent, it raises KeyError -> 502, exactly as the prototype does.
    data = payload.model_dump(exclude_unset=True)
    data["symbol"] = symbol
    logger.info("POST /api/interpret called with symbol=%s", symbol)
    try:
        return await get_interpret(data)
    except LLMUnavailable as exc:
        return _gateway_error("Interpretation unavailable: ", exc)
    except HTTPException:
        raise
    except Exception as exc:
        return _gateway_error("Interpretation unavailable: ", exc)
