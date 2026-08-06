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
from services.execution import offload

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
    try:
        rows = db_fetchall(
            f"SELECT gene_symbol g, mean_percentile m FROM gene_fitness_lean "
            f"WHERE organism = ? AND gene_symbol IN ({ph})",
            tuple([org] + list(genes)),
        )
    except Exception:
        # The lean only decides node COLOUR. Letting it raise takes the whole graph down with it,
        # which is the wrong trade — an uncoloured graph is still the graph. The network and the
        # lean also live in different places (net_edge vs the gene_fitness_lean lookup), so one
        # can be present and populated while the other is missing or unreadable.
        logger.warning("fitness lean unavailable; network nodes will be uncoloured", exc_info=True)
        return {}
    return {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}


# ---------------------------------------------------------------------------------------------
# EVIDENCE TIERS — what separates a real edge from a coincidence.
#
# The graph used to draw every edge identically, with thickness keyed on |r|. Three near-orthogonal
# statements about a pair exist in the data and the request path read one:
#
#   channel 1  net_edge.strength / .reciprocal   percentile-profile correlation over ALL screens
#   channel 2  hit_only_connection               Fisher co-hit enrichment over ONLY the screens
#                                                where both genes were CALLED HITS — the cells
#                                                channel 1 dilutes away. 417,924 human rows,
#                                                never read by any endpoint before now.
#   Jaccard    computed from the edge list       do the two genes share third parties?
#
# prototype/script/exp_evidence_tiers.py measures all four against CORUM same-complex membership,
# over the 11,954 drawn edges whose BOTH endpoints are CORUM-annotated (baseline 0.615%):
#
#     reciprocal AND co-hit     862 edges   7.2%    46.4% precision    75x chance
#     reciprocal only         1,578        13.2%    22.4%              36x
#     co-hit only             1,062         8.9%    17.7%              29x
#     neither                 8,452        70.7%     4.9%               8x
#
# A 9.5x spread, and seven of every ten drawn edges are in the bottom cell — rendered identically to
# the top cell. |r| is deliberately NOT part of the tier: it is the weakest dimension (AUROC 0.6361
# against 0.6991 for reciprocal) and non-monotone where it matters, its top decile scoring 17.3%
# against the second decile's 20.9%. Concordance is deliberately not a filter either (AUROC 0.5347).
# ---------------------------------------------------------------------------------------------
TIER_LABEL: dict[int, str] = {
    1: "both channels",
    2: "mutual-best",
    3: "co-hit only",
    4: "correlation only",
}

# Organisms whose co-hit table could not be read. reticle.hit_only_connection is newer than the rest
# of the schema — migrate_net_to_rds.py only started carrying it alongside this feature — so a
# deployment can legitimately be running against a database that predates it.
_COHIT_UNAVAILABLE: set[str] = set()


def cohit_table(organism: str) -> str:
    """Channel 2's table. Mirrors _edge_table: one schema for both species on RDS, so mouse is
    suffixed. The name comes from a fixed set — never from user input."""
    return "hit_only_connection_mouse" if organism == "mouse" else "hit_only_connection"


def cohit_available(organism: str) -> bool:
    return organism not in _COHIT_UNAVAILABLE


def cohit_among(genes: list[str], organism: str) -> dict[tuple[str, str], dict[str, Any]]:
    """{(a, b) ordered a<=b: {co_hit, fold, q_value, concordance, support}} for the co-hit pairs
    among `genes`. Absent from the dict means no significant co-hit: the table is BH-FDR filtered at
    build time, so presence IS significance.

    hit_only_connection stores ONE DIRECTION per pair — FANCA->FANCD2 is a row and the reverse is
    not — so every lookup has to agree on an ordering or it silently misses half the table. Both
    endpoints are inside `genes`, so a symmetric IN/IN predicate catches whichever way it was
    stored.

    Returns {} rather than raising when the table is missing. A graph whose tiers collapse to
    channel 1 is still a graph; a 500 is not. The failure is latched per organism so one missing
    table does not mean one failed query per request forever.
    """
    if not genes or organism in _COHIT_UNAVAILABLE:
        return {}
    tbl = cohit_table(organism)
    ph = ",".join("?" * len(genes))
    try:
        rows = db_fetchall(
            f"SELECT gene_a, gene_b, co_hit, fold, q_value, concordance, support FROM {tbl} "
            f"WHERE gene_a IN ({ph}) AND gene_b IN ({ph})",
            tuple(list(genes) + list(genes)),
        )
    except Exception:
        _COHIT_UNAVAILABLE.add(organism)
        logger.warning(
            "co-hit channel unavailable for %s; edges will be graded on channel 1 alone",
            organism,
            exc_info=True,
        )
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        a, b = r["gene_a"], r["gene_b"]
        out[(a, b) if a <= b else (b, a)] = {
            "co_hit": int(r["co_hit"]),
            "fold": round(float(r["fold"]), 2),
            "q_value": float(r["q_value"]),
            "concordance": round(float(r["concordance"]), 3),
            "support": int(r["support"]),
        }
    return out


def edge_tier(reciprocal: bool, has_cohit: bool) -> int:
    """1 both channels · 2 mutual-best only · 3 co-hit only · 4 neither. Ordered by MEASURED CORUM
    precision (46.4 / 22.4 / 17.7 / 4.9%), which is why mutual-best-only outranks co-hit-only rather
    than the other way round."""
    if reciprocal and has_cohit:
        return 1
    if reciprocal:
        return 2
    return 3 if has_cohit else 4


def _neighbour_sets(genes: list[str], tbl: str, context: str) -> dict[str, set[str]]:
    """gene -> its channel-1 partners in this context, over the WHOLE network.

    Deliberately not restricted to the displayed subgraph: Jaccard measured inside the subgraph is
    circular, because every node is there precisely because it is the seed's partner. The measured
    lift comes from full-network neighbourhoods.
    """
    if not genes:
        return {}
    ph = ",".join("?" * len(genes))
    try:
        rows = db_fetchall(
            f"SELECT gene_a, gene_b FROM {tbl} WHERE context=? AND channel='coessential' "
            f"AND (gene_a IN ({ph}) OR gene_b IN ({ph}))",
            tuple([context] + list(genes) + list(genes)),
        )
    except Exception:
        logger.warning("neighbourhood Jaccard unavailable", exc_info=True)
        return {}
    want = set(genes)
    nb: dict[str, set[str]] = {g: set() for g in genes}
    for r in rows:
        a, b = r["gene_a"], r["gene_b"]
        if a in want:
            nb[a].add(b)
        if b in want:
            nb[b].add(a)
    return nb


def _jaccard(nb: dict[str, set[str]], a: str, b: str) -> float | None:
    """|N(a) & N(b)| / |N(a) | N(b)|, excluding a and b themselves so a plain A-B edge cannot
    inflate their own coherence. None when either neighbourhood is unknown."""
    na, nbs = nb.get(a), nb.get(b)
    if na is None or nbs is None:
        return None
    left = na - {a, b}
    right = nbs - {a, b}
    union = left | right
    return round(len(left & right) / len(union), 3) if union else 0.0


def _annotate_edges(
    edges: list[dict[str, Any]], context: str, organism: str, tbl: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Attach cohit / jaccard / tier / tier_label to each edge, and return a tier histogram."""
    genes = sorted({g for e in edges for g in (e["source"], e["target"])})
    ch = cohit_among(genes, organism)
    nb = _neighbour_sets(genes, tbl, context)
    hist: dict[int, int] = {}
    for e in edges:
        a, b = e["source"], e["target"]
        c = ch.get((a, b) if a <= b else (b, a))
        e["cohit"] = c
        e["jaccard"] = _jaccard(nb, a, b)
        e["tier"] = edge_tier(bool(e["reciprocal"]), c is not None)
        e["tier_label"] = TIER_LABEL[e["tier"]]
        hist[e["tier"]] = hist.get(e["tier"], 0) + 1
    return edges, {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)}


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


@offload("db")
def get_net_contexts(organism: str = "human") -> list[dict[str, Any]]:
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


@offload("db")
def get_screen_net(
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

    # Second channel + neighbourhood coherence. In the reciprocal view `erows` is already
    # filtered to reciprocal=1, so every edge lands in tier 1 or 2 and the tier only reports
    # whether channel 2 agrees. The full four-tier spread appears once the user widens the view —
    # exactly where they most need to know which of the newly drawn edges is worth anything,
    # given 70.7% of all drawn edges sit in the 4.9%-precision bottom tier.
    edges, tiers = _annotate_edges(edges, ctx, organism, tbl)

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
    # How many partners the WIDER view holds. A gene with one mutual-best partner renders a
    # two-node graph that reads as a failure, so the panel needs to be able to say how much is
    # behind the reciprocal filter rather than leaving the reader to guess whether one partner
    # means "no signal" or "nothing loaded". A count, not the edges — the panel only decides
    # whether widening is worth offering.
    n_wider = db_fetchall(
        f"SELECT COUNT(*) c FROM {tbl} WHERE context=? AND channel='coessential' "
        f"AND (gene_a=? OR gene_b=?)",
        (ctx, seed, seed),
    )[0]["c"]
    return {
        "focus": seed,
        "context": ctx,
        "context_label": NET_CTX_LABELS.get(ctx, ctx),
        "reciprocal_only": reciprocal_only,
        "fellback": fellback,
        "nodes": nodes,
        "edges": edges,
        "tiers": tiers,
        "n_wider": int(n_wider),
        "cohit_available": cohit_available(organism),
    }


@offload("db")
def get_coessential(
    symbol: str, organism: str = "human", top: int = 14
) -> dict[str, Any] | None:
    """The gene wiki's inline co-essentiality graph.

    Same net_edge source as get_screen_net (see the module docstring for why the old local .npz was
    retired), and the prototype's ORIGINAL payload shape is preserved — nodes[].name/lean/focus and
    edges[].a/b/r/score — so nothing downstream breaks.

    ADDED: `tier` on every edge, `direct` (does it touch the focal gene), and a `tiers` histogram
    over the direct ones. The wiki draws only the direct edges — 14 lines instead of 57 — but keeps
    the partner-partner set because its force simulation needs them: they are what pulls a complex
    into a clump, so dropping them server-side would flatten the picture into a bare radial star.
    """
    tbl = _edge_table(organism)
    ctx = _default_context(organism)

    seed = _resolve_seed(symbol.strip(), tbl, ctx)
    if seed is None:
        return None

    # Reciprocal-preferred like the Network page: the mutual-best view is markedly cleaner
    # (46.4% vs 4.9% CORUM same-complex precision between the top and bottom evidence tiers).
    rows, _fellback, _clause = _neighbourhood(seed, tbl, ctx, True, top)
    if not rows:
        return None

    partners = [r["nb"] for r in rows]
    members = [seed] + partners
    ph = ",".join("?" * len(members))
    # No reciprocal clause here, deliberately: an edge the view will not DRAW still has to be
    # fetched, because it carries the tier and it shapes the layout.
    erows = db_fetchall(
        f"SELECT gene_a, gene_b, strength, reciprocal FROM {tbl} "
        f"WHERE context=? AND channel='coessential' "
        f"AND gene_a IN ({ph}) AND gene_b IN ({ph})",
        tuple([ctx] + members + members),
    )
    ch = cohit_among(members, organism)
    lean = _fitness_lean(members, organism)

    nodes = [{"name": n, "lean": _lean_label(lean.get(n)), "focus": n == seed} for n in members]
    mset = set(members)
    edges = []
    hist: dict[int, int] = {}
    for e in erows:
        a, b = e["gene_a"], e["gene_b"]
        if a not in mset or b not in mset or a == b:
            continue
        tier = edge_tier(bool(e["reciprocal"]), ((a, b) if a <= b else (b, a)) in ch)
        direct = seed in (a, b)
        r = round(float(e["strength"]), 3)
        edges.append({"a": a, "b": b, "r": r, "score": r, "tier": tier, "direct": direct})
        if direct:
            hist[tier] = hist.get(tier, 0) + 1

    n_screens = db_fetchall(
        "SELECT COUNT(*) c FROM net_screen WHERE coverage_type='FULL' AND n_genes >= 15000"
    )[0]["c"] if organism != "mouse" else None

    return {
        "symbol": seed,
        "nodes": nodes,
        "edges": edges,
        "n_screens": n_screens,
        "context_label": NET_CTX_LABELS.get(ctx, ctx),
        "tiers": {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)},
        "cohit_available": cohit_available(organism),
    }
