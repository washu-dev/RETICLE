"""Screen-level and network-level endpoints (ported from the standalone prototype).

Deliberately a SEPARATE router from routers/explorer.py: that file covers the GENE-level Explorer
endpoints (/api/gene, /api/context, /api/network) and is under active development, so screen- and
network-level endpoints live here to keep the two workstreams from colliding in one file.

Like explorer.py, these return the prototype's payload shape verbatim (snake_case, no camelCase
aliasing) so the ported frontend consumes them unchanged.

Currently exposed:
  GET /api/screen_similar_aaron  — screens whose fitness profile resembles a query screen
  GET /api/net_contexts          — available co-essentiality network contexts
  GET /api/screen_net            — one gene's co-essentiality neighbourhood (the Network page)
  GET /api/coessential_aaron     — the gene wiki's inline co-essentiality graph

WHY TWO OF THESE CARRY AN _aaron SUFFIX IN THE PATH, NOT JUST THE FILENAME
-------------------------------------------------------------------------
routers/coessential.py and routers/screen_similar.py serve /api/coessential and
/api/screen_similar from a DIFFERENT implementation (cosine similarity over L2-normalised
fitness profiles) for the Explorer. FastAPI matches the first registered route, and main.py
includes those before this module — so these two were silently dead after that landed, and
anything calling the plain path got the other implementation.

The payloads are not interchangeable. The Explorer's edges are {a, b, r, score}; these carry
`tier`, `tier_label`, `direct` and a `tiers` histogram, which is exactly what the gene wiki's
evidence lane draws with. Serving one where the other is expected does not error, it just
renders an untiered graph — so the paths are distinct rather than merged, and the Explorer's
routes are left alone.

Still to port from prototype/web/app.py (all RDS-backed and ready):
  /api/gene_wiki, /api/gene_predictions        (reticle.kb_*)
  /api/gene_screen_distribution                (reticle.harmonized_scores)
  /api/gene_structure                          (kb_gene + live AlphaFold/PDBe)
  /api/interpret, /api/reporter_explain,
  /api/screen_analysis, /api/net_predict       (WashU LLM gateway)
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.coessential_network_aaron import (
    get_coessential,
    get_net_contexts,
    get_screen_net,
)
from services.screen_similarity_aaron import get_screen_similar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["screens"])

# BioGRID ORCS screen ids are numeric. Validate at the edge as defense-in-depth — DB access is
# parameterized regardless.
_SCREEN_ID_RE = re.compile(r"^[0-9]{1,9}$")

# Same symbol rule as routers/explorer.py (TP53, Trp53, HLA-A, C1orf43, MT-CO1, ...).
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# `context` picks a stored net_edge partition. Free text never reaches SQL as an identifier (it is a
# bound parameter), but keep the surface tight anyway.
_CONTEXT_RE = re.compile(r"^[A-Za-z0-9:·._-]{1,40}$")

_ORGANISMS = {"human", "mouse"}

# Every spelling of a species this API has ever been asked for, mapped to the two the services
# understand. Three vocabularies are in play and they are not interchangeable: the cloud routes
# say "human"/"mouse", the prototype pages say "Homo sapiens"/"Mus musculus" (they still do — the
# Explore page and the gene wiki both pass the full binomial), and the wiki routes key off the
# NCBI taxid. Normalising here is what stops a mouse request from being served human data.
_ORGANISM_ALIASES = {
    "human": "human", "homo sapiens": "human", "hsapiens": "human",
    "hs": "human", "9606": "human",
    "mouse": "mouse", "mus musculus": "mouse", "mmusculus": "mouse",
    "mm": "mouse", "10090": "mouse",
}


def _validate_screen_id(screen_id: str) -> str:
    screen_id = screen_id.strip()
    if not _SCREEN_ID_RE.match(screen_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid screen id",
        )
    return screen_id


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid gene symbol",
        )
    return symbol


def _validate_organism(organism: str | None) -> str:
    """Normalise any accepted spelling to "human"/"mouse"; reject anything else.

    The old body was `organism if organism in _ORGANISMS else "human"`, which turned every
    unrecognised value into human data with a 200 attached. That is how /api/coessential came to
    serve the HUMAN network for mouse genes: the page sends `org=Mus musculus`, the route only
    declared `organism`, so the value never arrived and the default won. Silently answering a
    different question than the one asked is worse than failing, so an unknown non-empty value is
    now a 422. Empty and absent still mean "human", which is what every existing caller relies on.
    """
    if organism is None or organism.strip() == "":
        return "human"
    norm = _ORGANISM_ALIASES.get(organism.strip().lower())
    if norm is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown organism '{organism}' — expected human or mouse",
        )
    return norm


def _validate_context(context: str | None) -> str | None:
    if context is None or context == "":
        return None
    if not _CONTEXT_RE.match(context):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid context",
        )
    return context


@router.get("/screen_similar_aaron")
async def screen_similar(
    screen: str = Query(..., min_length=1, max_length=9),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    exclude_same_study: bool = Query(False),
) -> Any:
    """Screens correlated with the query screen (human, fitness, genome-wide pool).

    `results[].z` is the number the UI should foreground: how far above this screen's OWN background
    the match sits. A raw `r` is not comparable across query screens.
    """
    screen = _validate_screen_id(screen)
    logger.info("GET /api/screen_similar called with screen=%s", screen)
    payload = await get_screen_similar(
        screen, limit=limit, offset=offset, exclude_same_study=exclude_same_study
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screen '{screen}' is not in the human / fitness / genome-wide pool",
        )
    return payload


@router.get("/net_contexts")
async def net_contexts(organism: str = Query("human")) -> Any:
    """Co-essentiality network contexts available for this organism, with edge/node counts."""
    organism = _validate_organism(organism)
    logger.info("GET /api/net_contexts called with organism=%s", organism)
    return {"contexts": await get_net_contexts(organism)}


@router.get("/screen_net")
async def screen_net(
    gene: str = Query(..., min_length=1, max_length=40),
    context: str | None = Query(None, max_length=40),
    reciprocal: bool = Query(True),
    organism: str = Query("human"),
) -> Any:
    """One gene's co-essentiality neighbourhood: seed + top partners + partner-partner edges.

    `reciprocal` asks for the mutual-best view. Only ~40% of genes have a reciprocal partner, so if
    none exists the response widens to one-directional partners and sets `fellback: true` rather
    than returning an empty graph.
    """
    gene = _validate_symbol(gene)
    organism = _validate_organism(organism)
    context = _validate_context(context)
    logger.info("GET /api/screen_net called with gene=%s organism=%s", gene, organism)
    payload = await get_screen_net(gene, context, reciprocal_only=reciprocal, organism=organism)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{gene}' has no co-essentiality edges in this context — "
            f"it may not be hit-active here",
        )
    return payload


@router.get("/coessential_aaron")
async def coessential(
    symbol: str = Query(..., min_length=1, max_length=40),
    organism: str | None = Query(None),
    org: str | None = Query(None),
) -> Any:
    """The Explore page's inline co-essentiality graph.

    Now served from the same net_edge table as /api/screen_net (the prototype read a local 61 MB
    .npz that had no cloud counterpart); the response shape is unchanged for the frontend.

    `org` is accepted alongside `organism` because that is the name the shipped pages send
    (gene.html and index.html both build `...&org=` + the full binomial). FastAPI drops query
    params a route does not declare, so before this the value was discarded and every mouse
    request silently returned the human graph — verified against production: `Cars` came back
    with 12 nodes from the human pool instead of 15 from the mouse one.
    """
    symbol = _validate_symbol(symbol)
    organism = _validate_organism(organism or org)
    logger.info("GET /api/coessential called with symbol=%s organism=%s", symbol, organism)
    payload = await get_coessential(symbol, organism)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No co-essentiality neighbourhood for '{symbol}'",
        )
    return payload
