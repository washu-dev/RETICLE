"""STRING interaction network for a gene, each node colored by its RETICLE
fitness behavior. Ported from prototype/web/app.py `network_payload()`.

Combines an external STRING subnetwork (services.external_sources) with a DB
lookup of each node's median fitness percentile.
"""

from services import external_sources as ex
from services.db_service import db_fetchall

ORG2TAX = {"Homo sapiens": 9606, "Mus musculus": 10090}


def _lean(m: float | None) -> str | None:
    if m is None:
        return None
    return "essential" if m < -0.15 else "advantageous" if m > 0.15 else "mixed"


async def get_network(symbol: str, org: str) -> dict:
    """STRING subnetwork colored by CRISPR fitness. Empty graph if no partners."""
    taxid = ORG2TAX.get(org, 9606)
    net = ex.string_network(symbol, taxid)
    nodes = net.get("nodes", [])
    if not nodes:
        return {"focus": symbol, "nodes": [], "edges": []}

    ph = ",".join("?" * len(nodes))
    rows = db_fetchall(
        f"""SELECT h.GENE_SYMBOL AS g, AVG(h.PERCENTILE_SCORE) AS m
            FROM harmonized_scores h
            JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
            WHERE h.GENE_SYMBOL IN ({ph}) AND c.assay_domain = 'fitness'
              AND h.PERCENTILE_SCORE IS NOT NULL
            GROUP BY h.GENE_SYMBOL""",
        tuple(nodes),
    )
    med = {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}

    focus = next((n for n in nodes if n.upper() == symbol.upper()), symbol)
    out = [
        {
            "name": n,
            "median": round(med[n], 3) if n in med else None,
            "lean": _lean(med.get(n)),
            "focus": (n == focus),
        }
        for n in nodes
    ]
    return {"focus": focus, "nodes": out, "edges": net.get("edges", [])}
