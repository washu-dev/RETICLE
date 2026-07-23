"""Per-gene external context: annotation, darkness rating, and STRING partners.
Ported from prototype/web/app.py's /api/context handler (delegates to
services.external_sources.enrich)."""

from services import external_sources as ex

ORG2TAX = {"Homo sapiens": 9606, "Mus musculus": 10090}


async def get_context(symbol: str, org: str) -> dict:
    return ex.enrich(symbol, ORG2TAX.get(org, 9606))
