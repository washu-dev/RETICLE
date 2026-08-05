"""
Data service — real RDS queries when AWS_DB_HOST is set, mock data otherwise.

The two public async functions (run_query / get_gene_detail) are the seam
between the API layer and the database.  All mock reference data below stays
as a local-dev / no-DB fallback.
"""

import math
from uuid import uuid4

from models.gene import Citation, GeneDetail, StringInteractor
from models.query import (
    DarkGene,
    GraphEdge,
    GraphEdgeData,
    GraphElements,
    GraphNode,
    GraphNodeData,
    GraphNodePosition,
    MatchedScreen,
    QueryRequest,
    QueryResponse,
    QueryStats,
)
from services.reference_screens import REFERENCE_SCREENS, citation_for

# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

# Demo overlap stats (offline only) paired 1:1 with the verified real ORCS
# screens in REFERENCE_SCREENS. The identity fields (name, pmid, biogrid id,
# citation) come from the verified data so every PubMed/BioGRID link resolves;
# only the overlap numbers here are illustrative. Shared-gene tokens are kept to
# genes the offline gene lookup can resolve, so clicking one opens a real card.
_DEMO_OVERLAP = [
    {"rho": 0.82, "fdr": 0.0003, "dir": "agree",
     "shared": 18, "symbols": ["ATG5", "ATG7", "ULK1", "IRGM", "BECN1"]},
    {"rho": 0.74, "fdr": 0.0011, "dir": "agree",
     "shared": 15, "symbols": ["ATG7", "IRGM", "ATG5", "MAP1LC3B"]},
    {"rho": 0.61, "fdr": 0.0084, "dir": "agree",
     "shared": 12, "symbols": ["ULK1", "BECN1", "ATG5"]},
    {"rho": -0.55, "fdr": 0.0142, "dir": "inverted",
     "shared": 11, "symbols": ["ATG5", "IRGM"]},
    {"rho": 0.48, "fdr": 0.0389, "dir": "agree",
     "shared": 9, "symbols": ["ULK1", "IRGM"]},
    {"rho": 0.31, "fdr": 0.1204, "dir": "unknown",
     "shared": 6, "symbols": ["BECN1"]},
]

_MATCHED_SCREENS: list[MatchedScreen] = [
    MatchedScreen(
        id=i + 1,
        biogrid_id=s["screen_id"],
        name=s["title"],
        citation=citation_for(s),
        pmid=s["pmid"],
        organism="Human" if s["organism"] == "Homo sapiens" else "Mouse",
        modality=s["modality"],
        cell_type=s["cell_type"],
        rho=o["rho"],
        fdr=o["fdr"],
        directionality=o["dir"],
        shared_genes=o["shared"],
        total_genes=18009,
        shared_gene_symbols=o["symbols"],
        article_title=s["title"],
    )
    for i, (s, o) in enumerate(zip(REFERENCE_SCREENS, _DEMO_OVERLAP, strict=False))
]

_DARK_GENES: list[DarkGene] = [
    DarkGene(symbol="CCDC6",    dark_score=8.2, correlation=0.71,
             pubs=23,   screens=4, go_terms=3,  is_bright=False, cluster="dark-matter"),
    DarkGene(symbol="FAM114A1", dark_score=9.1, correlation=0.68,
             pubs=8,    screens=3, go_terms=2,  is_bright=False, cluster="dark-matter"),
    DarkGene(symbol="ZSWIM8",   dark_score=7.8, correlation=0.65,
             pubs=31,   screens=4, go_terms=4,  is_bright=False, cluster="dark-matter"),
    DarkGene(symbol="C1orf43",  dark_score=8.9, correlation=0.62,
             pubs=12,   screens=3, go_terms=2,  is_bright=False, cluster="dark-matter"),
    DarkGene(symbol="ANKRD36C", dark_score=9.4, correlation=0.58,
             pubs=5,    screens=2, go_terms=1,  is_bright=False, cluster="dark-matter"),
    DarkGene(symbol="TMEM106B", dark_score=6.5, correlation=0.77,
             pubs=67,   screens=5, go_terms=6,  is_bright=False, cluster="selective-autophagy"),
    DarkGene(symbol="STK38L",   dark_score=7.2, correlation=0.54,
             pubs=44,   screens=3, go_terms=5,  is_bright=False, cluster="selective-autophagy"),
    DarkGene(symbol="BNIP3L",   dark_score=5.8, correlation=0.59,
             pubs=89,   screens=4, go_terms=7,  is_bright=False, cluster="selective-autophagy"),
    DarkGene(symbol="RAB7A",    dark_score=4.4, correlation=0.66,
             pubs=214,  screens=6, go_terms=12, is_bright=False, cluster="core-autophagy"),
    DarkGene(symbol="VAMP8",    dark_score=5.2, correlation=0.81,
             pubs=112,  screens=5, go_terms=8,  is_bright=False, cluster="selective-autophagy"),
    DarkGene(symbol="ATG5",     dark_score=2.1, correlation=0.85,
             pubs=892,  screens=7, go_terms=22, is_bright=True,  cluster="core-autophagy"),
    DarkGene(symbol="ATG7",     dark_score=1.8, correlation=0.82,
             pubs=743,  screens=7, go_terms=19, is_bright=True,  cluster="core-autophagy"),
    DarkGene(symbol="ULK1",     dark_score=3.2, correlation=0.78,
             pubs=501,  screens=6, go_terms=16, is_bright=True,  cluster="core-autophagy"),
    DarkGene(symbol="IRGM",     dark_score=4.1, correlation=0.73,
             pubs=278,  screens=6, go_terms=11, is_bright=True,  cluster="selective-autophagy"),
    DarkGene(symbol="BECN1",    dark_score=2.4, correlation=0.76,
             pubs=1204, screens=8, go_terms=24, is_bright=True,  cluster="core-autophagy"),
    DarkGene(symbol="MAP1LC3B", dark_score=3.0, correlation=0.70,
             pubs=631,  screens=7, go_terms=17, is_bright=True,  cluster="core-autophagy"),
]

# Short "Author Year" labels for the graph's screen nodes, aligned to the first
# five verified reference screens (so node pmids/citations link out correctly).
_GRAPH_SCREENS = [
    {"pos": (300, 200), "detail": "Cancer fitness · Human · KO"},
    {"pos": (500, 100), "detail": "Glioblastoma · Human · KO"},
    {"pos": (650, 280), "detail": "Formaldehyde tox · Human · KO"},
    {"pos": (150, 350), "detail": "Lung cancer · Human · KO"},
    {"pos": (480, 400), "detail": "Zika resistance · Human · KO"},
]


def _short_label(author: str) -> str:
    """'Behan FM (2019)' -> 'Behan 2019' for compact graph labels."""
    surname = author.split(" ")[0] if author else author
    year = "".join(c for c in author if c.isdigit())[:4]
    return f"{surname} {year}".strip()


_GRAPH_ELEMENTS = GraphElements(
    nodes=[
        GraphNode(
            data=GraphNodeData(
                id=f"s{i + 1}",
                label=_short_label(ref["author"]),
                type="screen",
                detail=cfg["detail"],
                citation=citation_for(ref),
                pmid=ref["pmid"],
                gene_count=18009,
            ),
            position=GraphNodePosition(x=cfg["pos"][0], y=cfg["pos"][1]),
        )
        for i, (ref, cfg) in enumerate(zip(REFERENCE_SCREENS[:5], _GRAPH_SCREENS, strict=False))
    ] + [
        GraphNode(data=GraphNodeData(id="g1", label="ATG5",     type="gene",
                                     detail="Core autophagy · 892 pubs",   screen_count=3),
                  position=GraphNodePosition(x=350, y=320)),
        GraphNode(data=GraphNodeData(id="g2", label="ATG7",     type="gene",
                                     detail="Core autophagy · 743 pubs",   screen_count=2),
                  position=GraphNodePosition(x=420, y=250)),
        GraphNode(data=GraphNodeData(id="g3", label="IRGM",     type="gene",
                                     detail="Selective autophagy · 278 pubs", screen_count=3),
                  position=GraphNodePosition(x=280, y=150)),
        GraphNode(data=GraphNodeData(id="g4", label="CCDC6",    type="dark",
                                     detail="Dark candidate · 23 pubs",    screen_count=3),
                  position=GraphNodePosition(x=560, y=200)),
        GraphNode(data=GraphNodeData(id="g5", label="FAM114A1", type="dark",
                                     detail="Dark candidate · 8 pubs",     screen_count=3),
                  position=GraphNodePosition(x=200, y=260)),
        GraphNode(data=GraphNodeData(id="g6", label="ULK1",     type="gene",
                                     detail="Autophagy initiation · 501 pubs", screen_count=2),
                  position=GraphNodePosition(x=390, y=380)),
    ],
    edges=[
        GraphEdge(data=GraphEdgeData(source="s1", target="g1", rho=0.82)),
        GraphEdge(data=GraphEdgeData(source="s1", target="g2", rho=0.78)),
        GraphEdge(data=GraphEdgeData(source="s1", target="g3", rho=0.74)),
        GraphEdge(data=GraphEdgeData(source="s1", target="g4", rho=0.71)),
        GraphEdge(data=GraphEdgeData(source="s2", target="g1", rho=0.68)),
        GraphEdge(data=GraphEdgeData(source="s2", target="g3", rho=0.65)),
        GraphEdge(data=GraphEdgeData(source="s2", target="g4", rho=0.62)),
        GraphEdge(data=GraphEdgeData(source="s2", target="g5", rho=0.58)),
        GraphEdge(data=GraphEdgeData(source="s3", target="g2", rho=0.61)),
        GraphEdge(data=GraphEdgeData(source="s3", target="g6", rho=0.57)),
        GraphEdge(data=GraphEdgeData(source="s3", target="g4", rho=0.54)),
        GraphEdge(data=GraphEdgeData(source="s4", target="g5", rho=-0.55)),
        GraphEdge(data=GraphEdgeData(source="s4", target="g1", rho=-0.48)),
        GraphEdge(data=GraphEdgeData(source="s5", target="g6", rho=0.43)),
        GraphEdge(data=GraphEdgeData(source="s5", target="g3", rho=0.39)),
        GraphEdge(data=GraphEdgeData(source="s5", target="g5", rho=0.36)),
    ],
)

_GENE_RATIONALES: dict[str, dict] = {
    "CCDC6": {
        "hypothesis": (
            "CCDC6 (coiled-coil domain containing 6) co-clusters with core autophagy machinery "
            "(ATG5, ATG7, IRGM) across 4 of 8 matched screens, with a mean Spearman ρ of 0.71 "
            "to the query screen. Despite only 23 indexed publications, its pathway-correlation "
            "profile is indistinguishable from established autophagy genes, suggesting a "
            "functional role in autophagic flux or selective cargo recognition."
        ),
        "mechanistic_context": (
            "CCDC6 is known primarily as a fusion partner in thyroid carcinoma (RET/PTC "
            "rearrangements), where it acts as a substrate for ATM-mediated DNA damage "
            "checkpointing. However, its role in non-malignant macrophage biology is completely "
            "uncharacterized. The co-occurrence pattern with IFNγ-responsive genes (TBK1, IRGM) "
            "in matched screens suggests a potential regulatory node connecting innate immune "
            "signaling to autophagic clearance — a mechanism consistent with the itaconate/Irg1 "
            "axis being studied."
        ),
        "citations": [
            {"text": "Behan FM et al. (2019) Nature",            "pmid": "30971826"},
            {"text": "MacLeod G et al. (2019) Cell Reports",     "pmid": "30995489"},
            {"text": "Zhao Y et al. (2020) Chemosphere",         "pmid": "33189395"},
        ],
        "suggested_validation": (
            "Orthogonal validation via CRISPRi depletion in bone-marrow-derived macrophages with "
            "IFNγ/LPS co-stimulation. Assess LC3-II flux by western blot and p62/SQSTM1 "
            "accumulation as proxies for autophagic activity."
        ),
    },
    "FAM114A1": {
        "hypothesis": (
            "FAM114A1 (family with sequence similarity 114 member A1) has only 8 indexed "
            "publications and appears in 3 matched screens correlated with macrophage death "
            "regulators. Its functional annotation is limited to 2 GO terms — it is among the "
            "highest-darkness candidates in this query."
        ),
        "mechanistic_context": (
            "FAM114A1 encodes a poorly characterized transmembrane protein with predicted "
            "coiled-coil domains. It localizes to the ER in proteomics studies but has no "
            "assigned molecular function. The co-occurrence with known autophagy receptors in "
            "matched screens is unexplained by existing literature — this is a true dark matter "
            "candidate."
        ),
        "citations": [
            {"text": "Zhao Y et al. (2020) Chemosphere",             "pmid": "33189395"},
            {"text": "Krall EB et al. (2017) eLife",                 "pmid": "28145866"},
        ],
        "suggested_validation": (
            "Subcellular localization in activated macrophages using fluorescence microscopy. "
            "Proximity ligation assay with ATG5/ATG7 to test physical interaction."
        ),
    },
}

_STRING_INTERACTORS: dict[str, list[dict]] = {
    "CCDC6": [
        {"symbol": "ATM",   "combined_score": 0.921, "direction": "upregulated"},
        {"symbol": "RET",   "combined_score": 0.903, "direction": "upregulated"},
        {"symbol": "ATG5",  "combined_score": 0.741, "direction": "downregulated"},
        {"symbol": "IRGM",  "combined_score": 0.688, "direction": "downregulated"},
        {"symbol": "TBK1",  "combined_score": 0.654, "direction": "upregulated"},
        {"symbol": "BECN1", "combined_score": 0.612, "direction": "unknown"},
    ],
    "FAM114A1": [
        {"symbol": "ATG5",   "combined_score": 0.712, "direction": "downregulated"},
        {"symbol": "ULK1",   "combined_score": 0.681, "direction": "downregulated"},
        {"symbol": "SQSTM1", "combined_score": 0.643, "direction": "unknown"},
        {"symbol": "BNIP3L", "combined_score": 0.598, "direction": "downregulated"},
        {"symbol": "VAMP8",  "combined_score": 0.571, "direction": "unknown"},
    ],
    "ATG5": [
        {"symbol": "ATG7",     "combined_score": 0.999, "direction": "upregulated"},
        {"symbol": "BECN1",    "combined_score": 0.997, "direction": "upregulated"},
        {"symbol": "MAP1LC3B", "combined_score": 0.995, "direction": "upregulated"},
        {"symbol": "ULK1",     "combined_score": 0.988, "direction": "upregulated"},
        {"symbol": "ATG14",    "combined_score": 0.976, "direction": "upregulated"},
        {"symbol": "RUBCN",    "combined_score": 0.931, "direction": "downregulated"},
        {"symbol": "IRGM",     "combined_score": 0.912, "direction": "upregulated"},
    ],
    "ATG7": [
        {"symbol": "ATG5",     "combined_score": 0.999, "direction": "upregulated"},
        {"symbol": "BECN1",    "combined_score": 0.996, "direction": "upregulated"},
        {"symbol": "MAP1LC3B", "combined_score": 0.992, "direction": "upregulated"},
        {"symbol": "ULK1",     "combined_score": 0.981, "direction": "upregulated"},
        {"symbol": "ATG16L1",  "combined_score": 0.974, "direction": "upregulated"},
    ],
    "ULK1": [
        {"symbol": "ATG5",   "combined_score": 0.988, "direction": "upregulated"},
        {"symbol": "BECN1",  "combined_score": 0.982, "direction": "upregulated"},
        {"symbol": "ATG7",   "combined_score": 0.981, "direction": "upregulated"},
        {"symbol": "PIK3C3", "combined_score": 0.962, "direction": "upregulated"},
        {"symbol": "RPTOR",  "combined_score": 0.941, "direction": "downregulated"},
        {"symbol": "MTOR",   "combined_score": 0.934, "direction": "downregulated"},
    ],
}

# Index for O(1) look-ups
_DARK_GENE_INDEX: dict[str, DarkGene] = {g.symbol: g for g in _DARK_GENES}


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def _verify_citations(screens: list[MatchedScreen]) -> None:
    """Overwrite each screen's citation/article_title with NCBI-verified values,
    keyed on its own pmid. Best-effort and cached; a network failure leaves the
    stored citation untouched. Mutates the list in place."""
    try:
        from services.external_sources import article_meta
    except Exception:
        return
    for s in screens:
        try:
            meta = article_meta(s.pmid)
        except Exception:
            meta = None
        if meta:
            if meta.get("citation"):
                s.citation = meta["citation"]
            if meta.get("title"):
                s.article_title = meta["title"]


async def run_query(request: QueryRequest) -> QueryResponse:
    from services.corpus_service import build_corpus_where, corpus_count
    from services.db_service import USE_PG, db_fetchall

    pool_size = corpus_count(request.corpus_filters)

    if not USE_PG:
        sig_count   = sum(1 for s in _MATCHED_SCREENS if s.fdr < 0.05)
        agree_count = sum(1 for s in _MATCHED_SCREENS if s.directionality == "agree")
        return QueryResponse(
            query_id=str(uuid4()),
            stats=QueryStats(
                screens_compared=pool_size,
                significant_matches=sig_count,
                agree_directionality=agree_count,
                query_gene_count=len(request.genes),
            ),
            matched_screens=_MATCHED_SCREENS,
            dark_genes=_DARK_GENES,
            graph_elements=_GRAPH_ELEMENTS,
            screen_context=request.screen_context,
            corpus_pool_size=pool_size,
        )

    symbols = [g.symbol.upper() for g in request.genes] or ["ATG5"]
    gene_ph = ", ".join("?" * len(symbols))
    corpus_where, corpus_params = build_corpus_where(request.corpus_filters)

    # nosec B608 — placeholders only (gene_ph / corpus_where are fixed clauses)
    screen_rows = db_fetchall(f"""
        SELECT
            sm.screen_id                                        AS biogrid_id,
            sm.screen_name                                      AS name,
            COALESCE(sm.author, 'Unknown')                      AS citation,
            COALESCE(smc.pmid, '')                              AS pmid,
            COALESCE(sm.organism_official, 'Homo sapiens')      AS organism,
            COALESCE(smc.selection_method, sm.screen_type, 'KO') AS modality,
            COALESCE(sm.cell_type, sm.cell_line, 'Unknown')     AS cell_type,
            AVG(hs.percentile_score) FILTER (WHERE hs.percentile_score IS NOT NULL) AS rho,
            COALESCE(smc.growth_direction, 'none')              AS directionality,
            COUNT(DISTINCT hs.gene_symbol)                      AS shared_genes,
            array_agg(DISTINCT hs.gene_symbol)                  AS shared_symbols,
            COALESCE(sm.scores_size, 0)                         AS total_genes
        FROM reticle.harmonized_scores hs
        JOIN  reticle.screen_metadata          sm  ON hs.screen_id = sm.screen_id
        LEFT JOIN reticle.screen_metadata_curated smc ON hs.screen_id = smc.screen_id
        WHERE hs.gene_symbol IN ({gene_ph})
          AND hs.is_hit = 1{corpus_where}
        GROUP BY sm.screen_id, sm.screen_name, sm.author, sm.organism_official,
                 smc.pmid, smc.selection_method, sm.screen_type, sm.cell_type,
                 sm.cell_line, smc.growth_direction, sm.scores_size
        HAVING COUNT(DISTINCT hs.gene_symbol) >= ?
        ORDER BY shared_genes DESC, rho DESC
        LIMIT 20
    """,
        tuple(symbols)
        + tuple(corpus_params)
        + (int(getattr(request.corpus_filters, "min_shared_genes", 0) or 0),),
    )

    matched_screens = [
        MatchedScreen(
            id=i + 1,
            biogrid_id=str(row["biogrid_id"]),
            name=str(row["name"] or ""),
            citation=str(row["citation"]),
            pmid=str(row["pmid"]),
            organism=str(row["organism"]),
            modality=str(row["modality"]),
            cell_type=str(row["cell_type"]),
            rho=round(float(row["rho"] or 0), 4),
            fdr=0.0,
            directionality=str(row["directionality"] or "normal"),
            shared_genes=int(row["shared_genes"]),
            total_genes=int(row["total_genes"]),
            shared_gene_symbols=[str(g) for g in (row["shared_symbols"] or [])],
        )
        for i, row in enumerate(screen_rows)
    ]

    # Verify each match's citation against its own pmid (best-effort, cached) so
    # the citation text shown in the UI always matches the PubMed link it sits next
    # to. Leaves the DB author string in place when NCBI is unreachable.
    _verify_citations(matched_screens)

    matched_ids = [r["biogrid_id"] for r in screen_rows]
    dark_genes: list[DarkGene] = []

    if matched_ids:
        screen_ph = ", ".join("?" * len(matched_ids))
        # nosec B608 — placeholders only, no user data in SQL
        dark_rows = db_fetchall(f"""
            SELECT
                hs.gene_symbol                          AS symbol,
                COUNT(DISTINCT hs.screen_id)            AS screen_count,
                AVG(hs.percentile_score)
                    FILTER (WHERE hs.percentile_score IS NOT NULL) AS avg_score,
                COALESCE(dg.total_screens, 1)           AS pubs,
                COALESCE(dg.total_screens, 1)           AS total_screens
            FROM reticle.harmonized_scores hs
            LEFT JOIN public.dim_gene dg
                   ON LOWER(hs.gene_symbol) = LOWER(dg.gene_symbol) AND dg.is_current = TRUE
            WHERE hs.screen_id IN ({screen_ph})
              AND hs.is_hit = 1
              AND hs.gene_symbol NOT IN ({gene_ph})
            GROUP BY hs.gene_symbol, dg.total_publications, dg.total_screens
            ORDER BY screen_count DESC, pubs ASC
            LIMIT 20
        """, tuple(matched_ids) + tuple(symbols))

        dark_genes = [
            DarkGene(
                symbol=str(row["symbol"]),
                dark_score=round(10.0 / math.log10(int(row["pubs"]) + 2), 2),
                correlation=round(float(row["avg_score"] or 0), 4),
                pubs=int(row["pubs"]),
                screens=int(row["screen_count"]),
                go_terms=0,
                is_bright=int(row["pubs"]) > 100,
                cluster="co-hit",
            )
            for row in dark_rows
        ]

    # Graph: top 5 screens + top 8 dark genes as nodes; edges from co-hit data
    screen_nodes = [
        GraphNode(data=GraphNodeData(
            id=f"s{i + 1}",
            label=ms.citation.split(",")[0],
            type="screen",
            citation=ms.citation,
            pmid=ms.pmid,
            gene_count=ms.total_genes,
        ))
        for i, ms in enumerate(matched_screens[:5])
    ]
    gene_nodes = [
        GraphNode(data=GraphNodeData(
            id=f"g{i + 1}",
            label=dg.symbol,
            type="gene",
            detail=f"{dg.pubs} pubs · {dg.screens} screens",
            screen_count=dg.screens,
        ))
        for i, dg in enumerate(dark_genes[:8])
    ]

    edges: list[GraphEdge] = []
    if matched_ids:
        screen_id_map = {ms.biogrid_id: f"s{i + 1}" for i, ms in enumerate(matched_screens[:5])}
        gene_id_map   = {dg.symbol: f"g{i + 1}" for i, dg in enumerate(dark_genes[:8])}
        top_screen_ph = ", ".join("?" * len(matched_ids[:5]))
        top_gene_syms = list(gene_id_map.keys())
        top_gene_ph   = ", ".join("?" * len(top_gene_syms))
        if top_gene_syms:
            # nosec B608 — placeholders only, no user data in SQL
            edge_rows = db_fetchall(f"""
                SELECT screen_id, gene_symbol, harmonized_score
                FROM reticle.harmonized_scores
                WHERE screen_id IN ({top_screen_ph})
                  AND gene_symbol IN ({top_gene_ph})
                  AND is_hit = 1
                LIMIT 40
            """, tuple(matched_ids[:5]) + tuple(top_gene_syms))
            for row in edge_rows:
                s_node = screen_id_map.get(str(row["screen_id"]))
                g_node = gene_id_map.get(str(row["gene_symbol"]))
                if s_node and g_node:
                    edges.append(GraphEdge(data=GraphEdgeData(
                        source=s_node,
                        target=g_node,
                        rho=round(float(row["harmonized_score"] or 0), 4),
                        edge_label=f"{row['screen_id']} → {row['gene_symbol']}",
                    )))

    stats = QueryStats(
        screens_compared=len(matched_screens),
        significant_matches=sum(1 for ms in matched_screens if ms.rho > 0.7),
        agree_directionality=sum(
            1 for ms in matched_screens if ms.directionality in ("promoting", "suppressing")
        ),
        query_gene_count=len(symbols),
    )

    return QueryResponse(
        query_id=str(uuid4()),
        stats=stats,
        matched_screens=matched_screens,
        dark_genes=dark_genes,
        graph_elements=GraphElements(nodes=screen_nodes + gene_nodes, edges=edges),
        screen_context=request.screen_context,
        corpus_pool_size=pool_size,
    )


async def get_gene_detail(symbol: str) -> GeneDetail | None:
    from services.db_service import USE_PG, db_fetchall

    if not USE_PG:
        dark        = _DARK_GENE_INDEX.get(symbol)
        rationale   = _GENE_RATIONALES.get(symbol)
        interactors = _STRING_INTERACTORS.get(symbol)
        if dark is None and rationale is None:
            return None
        return GeneDetail(
            symbol=symbol,
            dark_score=dark.dark_score if dark else None,
            pubs=dark.pubs if dark else None,
            screens=dark.screens if dark else None,
            correlation=dark.correlation if dark else None,
            is_bright=dark.is_bright if dark else None,
            hypothesis=rationale.get("hypothesis") if rationale else None,
            mechanistic_context=rationale.get("mechanistic_context") if rationale else None,
            citations=[
                Citation(text=c["text"], pmid=c["pmid"])
                for c in (rationale.get("citations") or [])
            ] if rationale else [],
            suggested_validation=rationale.get("suggested_validation") if rationale else None,
            string_interactors=[
                StringInteractor(symbol=i["symbol"], combined_score=i["combined_score"],
                                 direction=i["direction"])
                for i in interactors
            ] if interactors else None,
        )

    stats_rows = db_fetchall("""
        SELECT total_screens AS screens
        FROM public.dim_gene
        WHERE LOWER(gene_symbol) = LOWER(?) AND is_current = TRUE
        LIMIT 1
    """, (symbol,))

    if not stats_rows:
        return None

    screens = int(stats_rows[0]["screens"] or 0)

    score_rows = db_fetchall("""
        SELECT AVG(percentile_score) FILTER (WHERE percentile_score IS NOT NULL) AS avg_score,
               COUNT(DISTINCT screen_id) AS hit_screens
        FROM reticle.harmonized_scores
        WHERE UPPER(gene_symbol) = UPPER(?) AND is_hit = 1
    """, (symbol,))
    avg_score   = round(float((score_rows[0]["avg_score"] or 0) if score_rows else 0), 4)
    hit_screens = int((score_rows[0]["hit_screens"] or 0) if score_rows else 0)

    # Citations: pull screens where gene is a hit, using screen_metadata author/name as proxy
    citation_rows = db_fetchall("""
        SELECT DISTINCT smc.pmid, sm.author, sm.screen_name
        FROM reticle.harmonized_scores hs
        JOIN reticle.screen_metadata sm ON hs.screen_id = sm.screen_id
        LEFT JOIN reticle.screen_metadata_curated smc ON hs.screen_id = smc.screen_id
        WHERE UPPER(hs.gene_symbol) = UPPER(?) AND hs.is_hit = 1 AND smc.pmid IS NOT NULL
        ORDER BY smc.pmid
        LIMIT 5
    """, (symbol,))

    citations = [
        Citation(text=str(row["author"] or row["screen_name"]), pmid=str(row["pmid"]))
        for row in citation_rows
        if row["pmid"]
    ]

    # Use hit_screens as darkness proxy — more screens hit = better characterized
    dark_score = round(10.0 / math.log10(hit_screens + 2), 2)
    is_bright  = hit_screens > 50

    hypothesis = (
        f"{symbol} appears as a significant hit in {hit_screens} of {screens} CRISPR screens "
        f"(mean percentile score {avg_score:.3f}). "
        f"It is a {'well-characterized' if is_bright else 'dark'} candidate — "
        f"appearing as a hit in {'many' if is_bright else 'few'} screens relative to the dataset."
    )

    return GeneDetail(
        symbol=symbol,
        dark_score=dark_score,
        pubs=hit_screens,
        screens=screens,
        correlation=avg_score,
        is_bright=is_bright,
        hypothesis=hypothesis,
        citations=citations,
    )

