"""Co-essentiality network endpoints (ported from the standalone prototype).

All three endpoints here read the SAME source of truth: reticle.net_edge (human) /
reticle.net_edge_mouse (mouse), built offline by prototype/script/compute_coessential.py and synced
by prototype/script/migrate_net_to_rds.py.

WHAT CHANGED VERSUS THE PROTOTYPE — /api/coessential now reads net_edge too.
In the prototype that endpoint loaded a dense 61 MB coess_<taxid>.npz from local disk and computed
`R @ R[query]` per request. That file has no RDS counterpart, so the endpoint could not run in the
cloud at all, and it was also a second, WEAKER co-essentiality channel than the one the Network page
already used:

  coess_<taxid>.npz            net_edge  (what we serve now)
  --------------------------   -------------------------------------------------
  dense cosine == Pearson      same Pearson, but with PC1 (the pan-essentiality axis, ~44.5% of
                               variance) projected out first, so real complexes outrank generic
                               "everything essential co-drops" similarity
  fixed r >= 0.25 cutoff       per-context threshold calibrated against a within-screen-shuffle
                               null at FDR <= 0.05
  no support / reciprocity     carries co-measured support count and a mutual-best (reciprocal) flag
  no node gates                nodes gated on hit count, coverage and hit rate (suppresses
                               multi-mapping-sgRNA artifact cliques)

Measured on the shipped edge set, reciprocal net_edge edges recover CORUM complexes at 32.9%
precision (42.5x over chance) and precision falls monotonically with edge strength — so this is a
strict upgrade, not just a portability workaround. The RESPONSE SHAPE is kept byte-compatible with
the prototype (nodes[].name/lean/focus, edges[].a/b/r/score) so the existing frontend is unchanged.
"""

import logging
from typing import Any

from services.db_service import db_fetchall

logger = logging.getLogger(__name__)

# Mirrors prototype/web/app.py::NET_CTX_LABELS.
NET_CTX_LABELS = {
    "all": "All screens · pooled",
    "mouse": "All mouse screens · pooled",
    "domain:fitness": "Fitness · generic proliferation",
    "DDR·genotoxic": "DNA damage · genotoxic",
}

# Node colouring cut-offs on the mean within-screen fitness percentile, as in the prototype.
_ESSENTIAL_MAX = -0.15
_ADVANTAGEOUS_MIN = 0.15


def _edge_table(organism: str) -> str:
    """Both species share one schema on RDS, so mouse is a suffixed table (locally they are two
    files that both call it `net_edge`). The name comes from a fixed set — never from user input."""
    return "net_edge_mouse" if organism == "mouse" else "net_edge"


def _default_context(organism: str) -> str:
    return "mouse" if organism == "mouse" else "all"


def _lean_label(m: float | None) -> str | None:
    if m is None:
        return None
    if m < _ESSENTIAL_MAX:
        return "essential"
    if m > _ADVANTAGEOUS_MIN:
        return "advantageous"
    return "mixed"


def _fitness_lean(genes: list[str], organism: str) -> dict[str, float]:
    """Mean fitness percentile per gene, from the precomputed reticle.gene_fitness_lean lookup.

    Never aggregate harmonized_scores here: doing that at request time measured 92 s on a cold cache
    (an optimal index-scan still pulls ~24k rows out of 28M), which is why the lookup table exists.
    """
    if not genes:
        return {}
    org = "Mus musculus" if organism == "mouse" else "Homo sapiens"
    ph = ",".join("?" * len(genes))
    rows = db_fetchall(
        f"SELECT gene_symbol g, mean_percentile m FROM gene_fitness_lean "
        f"WHERE organism = ? AND gene_symbol IN ({ph})",
        tuple([org] + list(genes)),
    )
    return {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}


def _resolve_seed(gene: str, tbl: str, context: str) -> str | None:
    """net_edge is keyed by gene SYMBOL, so try the casings BioGRID actually uses."""
    seen: list[str] = []
    for v in (gene, gene.upper(), gene.capitalize()):
        if v in seen:
            continue
        seen.append(v)
        if db_fetchall(
            f"SELECT 1 FROM {tbl} WHERE context=? AND (gene_a=? OR gene_b=?) LIMIT 1",
            (context, v, v),
        ):
            return v
    return None


async def get_net_contexts(organism: str = "human") -> list[dict[str, Any]]:
    """Available network contexts with edge/node counts."""
    tbl = _edge_table(organism)
    out = []
    for r in db_fetchall(
        f"SELECT context, COUNT(*) n, SUM(reciprocal) nr FROM {tbl} "
        f"WHERE channel='coessential' GROUP BY context ORDER BY n DESC"
    ):
        ctx = r["context"]
        nodes = db_fetchall(
            f"SELECT COUNT(*) c FROM (SELECT gene_a FROM {tbl} WHERE context=? "
            f"UNION SELECT gene_b FROM {tbl} WHERE context=?) t",
            (ctx, ctx),
        )[0]["c"]
        out.append(
            {
                "value": ctx,
                "label": NET_CTX_LABELS.get(ctx, ctx),
                "n_edges": r["n"],
                "n_reciprocal": int(r["nr"] or 0),
                "n_nodes": nodes,
            }
        )
    return out


def _neighbourhood(
    seed: str, tbl: str, context: str, reciprocal_only: bool, top: int
) -> tuple[list[dict], bool, str]:
    """Top partners, preferring mutual-best and widening if there are none.

    Only ~40% of genes HAVE a reciprocal partner, so asking for reciprocal-only and returning
    nothing rendered an empty graph for most of the network. Fall back and tell the caller.
    """

    def fetch(recip: bool) -> tuple[str, list]:
        clause = "AND reciprocal=1 " if recip else ""
        return clause, db_fetchall(
            f"SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength "
            f"FROM {tbl} WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) "
            f"{clause}ORDER BY strength DESC LIMIT ?",
            (seed, context, seed, seed, top),
        )

    clause, rows = fetch(reciprocal_only)
    fellback = False
    if not rows and reciprocal_only:
        clause, rows = fetch(False)
        fellback = True
    return rows, fellback, clause


async def get_screen_net(
    gene: str,
    context: str | None = None,
    reciprocal_only: bool = True,
    organism: str = "human",
    top: int = 18,
) -> dict[str, Any] | None:
    """One gene's context neighbourhood as a clustered graph (seed + partners + partner-partner
    edges, so it reads as modules rather than a star)."""
    tbl = _edge_table(organism)
    ctx = context or _default_context(organism)

    seed = _resolve_seed(gene.strip(), tbl, ctx)
    if seed is None:
        return None

    rows, fellback, clause = _neighbourhood(seed, tbl, ctx, reciprocal_only, top)
    if not rows:
        return None
    if fellback:
        reciprocal_only = False

    nodeset = [seed] + [r["nb"] for r in rows]
    nsi = set(nodeset)
    ph = ",".join("?" * len(nodeset))
    erows = db_fetchall(
        f"SELECT gene_a, gene_b, strength, reciprocal FROM {tbl} "
        f"WHERE context=? AND channel='coessential' "
        f"AND gene_a IN ({ph}) AND gene_b IN ({ph}) {clause}",
        tuple([ctx] + nodeset + nodeset),
    )
    lean = _fitness_lean(nodeset, organism)

    degree: dict[str, int] = {}
    edges = []
    for e in erows:
        a, b = e["gene_a"], e["gene_b"]
        if a in nsi and b in nsi and a != b:
            edges.append(
                {
                    "source": a,
                    "target": b,
                    "strength": round(float(e["strength"]), 3),
                    "reciprocal": int(e["reciprocal"]),
                }
            )
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1

    nodes = [
        {
            "id": n,
            "label": n,
            "focus": n == seed,
            "lean": _lean_label(lean.get(n)),
            # `mean_percentile`, not `median`: gene_fitness_lean stores an average.
            "mean_percentile": round(lean[n], 3) if n in lean else None,
            "degree": degree.get(n, 0),
        }
        for n in nodeset
    ]
    return {
        "focus": seed,
        "context": ctx,
        "context_label": NET_CTX_LABELS.get(ctx, ctx),
        "reciprocal_only": reciprocal_only,
        "fellback": fellback,
        "nodes": nodes,
        "edges": edges,
    }


async def get_coessential(
    symbol: str, organism: str = "human", top: int = 14
) -> dict[str, Any] | None:
    """The Explore page's inline co-essentiality graph.

    Same net_edge source as get_screen_net (see the module docstring for why the old local .npz was
    retired), but returns the prototype's ORIGINAL payload shape so the existing Explore frontend
    needs no change: nodes[].name/lean/focus and edges[].a/b/r/score.
    """
    tbl = _edge_table(organism)
    ctx = _default_context(organism)

    seed = _resolve_seed(symbol.strip(), tbl, ctx)
    if seed is None:
        return None

    # Reciprocal-preferred like the Network page: the mutual-best view is markedly cleaner
    # (32.9% vs 8.9% CORUM same-complex precision on the shipped edge set).
    rows, _fellback, clause = _neighbourhood(seed, tbl, ctx, True, top)
    if not rows:
        return None

    partners = [r["nb"] for r in rows]
    members = [seed] + partners
    ph = ",".join("?" * len(members))
    erows = db_fetchall(
        f"SELECT gene_a, gene_b, strength FROM {tbl} "
        f"WHERE context=? AND channel='coessential' "
        f"AND gene_a IN ({ph}) AND gene_b IN ({ph}) {clause}",
        tuple([ctx] + members + members),
    )
    lean = _fitness_lean(members, organism)

    nodes = [{"name": n, "lean": _lean_label(lean.get(n)), "focus": n == seed} for n in members]
    mset = set(members)
    edges = []
    for e in erows:
        a, b = e["gene_a"], e["gene_b"]
        if a in mset and b in mset and a != b:
            r = round(float(e["strength"]), 3)
            edges.append({"a": a, "b": b, "r": r, "score": r})

    n_screens = db_fetchall(
        "SELECT COUNT(*) c FROM net_screen WHERE coverage_type='FULL' AND n_genes >= 15000"
    )[0]["c"] if organism != "mouse" else None

    return {"symbol": seed, "nodes": nodes, "edges": edges, "n_screens": n_screens}
