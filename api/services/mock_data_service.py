"""
Data service â€” real RDS queries when AWS_DB_HOST is set, mock data otherwise.

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

# ---------------------------------------------------------------------------
# Static reference data (mirrors mockData.js)
# ---------------------------------------------------------------------------

_MATCHED_SCREENS: list[MatchedScreen] = [
    MatchedScreen(id=1, biogrid_id="ORCS-4421",
                  name="Autophagy regulation in LPS-stimulated macrophages",
                  citation="Orvedahl et al., 2019", pmid="31097699",
                  organism="Human", modality="KO", cell_type="THP-1 macrophages",
                  rho=0.82, fdr=0.0003, directionality="agree",
                  shared_genes=18, total_genes=847),
    MatchedScreen(id=2, biogrid_id="ORCS-6102",
                  name="IFNÎ³ pathway modulators in monocyte-derived macrophages",
                  citation="Zhao et al., 2021", pmid="33782614",
                  organism="Human", modality="KO", cell_type="MDMs",
                  rho=0.74, fdr=0.0011, directionality="agree",
                  shared_genes=15, total_genes=912),
    MatchedScreen(id=3, biogrid_id="ORCS-7883",
                  name="mTOR complex regulation in nutrient stress",
                  citation="Lin et al., 2022", pmid="35124892",
                  organism="Human", modality="KO", cell_type="HEK293T",
                  rho=0.61, fdr=0.0084, directionality="agree",
                  shared_genes=12, total_genes=1204),
    MatchedScreen(id=4, biogrid_id="ORCS-5519",
                  name="Macrophage activation enhancers â€” CRISPRa gain-of-function",
                  citation="Park et al., 2023", pmid="36891234",
                  organism="Human", modality="CRISPRa",
                  cell_type="iPSC-derived macrophages",
                  rho=-0.55, fdr=0.0142, directionality="inverted",
                  shared_genes=11, total_genes=763),
    MatchedScreen(id=5, biogrid_id="ORCS-8234",
                  name="Inflammatory cell death regulators in RAW264.7",
                  citation="Huang et al., 2021", pmid="33441802",
                  organism="Mouse", modality="KO", cell_type="RAW264.7",
                  rho=0.48, fdr=0.0389, directionality="agree",
                  shared_genes=9, total_genes=688),
    MatchedScreen(id=6, biogrid_id="ORCS-9041",
                  name="Autophagic flux determinants in J774 cells",
                  citation="Chen et al., 2022", pmid="35672901",
                  organism="Mouse", modality="KO", cell_type="J774A.1",
                  rho=0.43, fdr=0.0512, directionality="agree",
                  shared_genes=8, total_genes=731),
    MatchedScreen(id=7, biogrid_id="ORCS-11203",
                  name="Pyroptosis effector screen in BMDMs",
                  citation="Kim et al., 2023", pmid="37102456",
                  organism="Mouse", modality="KO", cell_type="BMDMs",
                  rho=0.31, fdr=0.1204, directionality="unknown",
                  shared_genes=6, total_genes=522),
    MatchedScreen(id=8, biogrid_id="ORCS-10087",
                  name="Immune checkpoint regulators in T cells",
                  citation="Wilson et al., 2022", pmid="35984321",
                  organism="Human", modality="KO",
                  cell_type="Primary CD8+ T cells",
                  rho=-0.28, fdr=0.1891, directionality="inverted",
                  shared_genes=5, total_genes=1043),
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

_GRAPH_ELEMENTS = GraphElements(
    nodes=[
        GraphNode(data=GraphNodeData(id="s1", label="Orvedahl 2019", type="screen",
                                     detail="Autophagy Â· Human Â· KO",
                                     citation="Orvedahl et al., 2019 Â· Nature Immunology",
                                     pmid="31097699", gene_count=847),
                  position=GraphNodePosition(x=300, y=200)),
        GraphNode(data=GraphNodeData(id="s2", label="Zhao 2021", type="screen",
                                     detail="IFNÎ³ Â· Human Â· KO",
                                     citation="Zhao et al., 2021 Â· Cell Reports",
                                     pmid="33782614", gene_count=912),
                  position=GraphNodePosition(x=500, y=100)),
        GraphNode(data=GraphNodeData(id="s3", label="Lin 2022", type="screen",
                                     detail="mTOR Â· Human Â· KO",
                                     citation="Lin et al., 2022 Â· eLife",
                                     pmid="35124892", gene_count=1204),
                  position=GraphNodePosition(x=650, y=280)),
        GraphNode(data=GraphNodeData(id="s4", label="Park 2023", type="screen",
                                     detail="Activation Â· iPSC Â· CRISPRa",
                                     citation="Park et al., 2023 Â· Cell Stem Cell",
                                     pmid="36891234", gene_count=763),
                  position=GraphNodePosition(x=150, y=350)),
        GraphNode(data=GraphNodeData(id="s5", label="Huang 2021", type="screen",
                                     detail="Cell death Â· Mouse Â· KO",
                                     citation="Huang et al., 2021 Â· Science Immunology",
                                     pmid="33441802", gene_count=688),
                  position=GraphNodePosition(x=480, y=400)),
        GraphNode(data=GraphNodeData(id="g1", label="ATG5",     type="gene",
                                     detail="Core autophagy Â· 892 pubs",   screen_count=3),
                  position=GraphNodePosition(x=350, y=320)),
        GraphNode(data=GraphNodeData(id="g2", label="ATG7",     type="gene",
                                     detail="Core autophagy Â· 743 pubs",   screen_count=2),
                  position=GraphNodePosition(x=420, y=250)),
        GraphNode(data=GraphNodeData(id="g3", label="IRGM",     type="gene",
                                     detail="Selective autophagy Â· 278 pubs", screen_count=3),
                  position=GraphNodePosition(x=280, y=150)),
        GraphNode(data=GraphNodeData(id="g4", label="CCDC6",    type="dark",
                                     detail="Dark candidate Â· 23 pubs",    screen_count=3),
                  position=GraphNodePosition(x=560, y=200)),
        GraphNode(data=GraphNodeData(id="g5", label="FAM114A1", type="dark",
                                     detail="Dark candidate Â· 8 pubs",     screen_count=3),
                  position=GraphNodePosition(x=200, y=260)),
        GraphNode(data=GraphNodeData(id="g6", label="ULK1",     type="gene",
                                     detail="Autophagy initiation Â· 501 pubs", screen_count=2),
                  position=GraphNodePosition(x=390, y=380)),
    ],
    edges=[
        GraphEdge(data=GraphEdgeData(
            source="s1", target="g1", rho=0.82, edge_label="Orvedahl 2019 â†’ ATG5")),
        GraphEdge(data=GraphEdgeData(
            source="s1", target="g2", rho=0.78, edge_label="Orvedahl 2019 â†’ ATG7")),
        GraphEdge(data=GraphEdgeData(
            source="s1", target="g3", rho=0.74, edge_label="Orvedahl 2019 â†’ IRGM")),
        GraphEdge(data=GraphEdgeData(
            source="s1", target="g4", rho=0.71, edge_label="Orvedahl 2019 â†’ CCDC6")),
        GraphEdge(data=GraphEdgeData(
            source="s2", target="g1", rho=0.68, edge_label="Zhao 2021 â†’ ATG5")),
        GraphEdge(data=GraphEdgeData(
            source="s2", target="g3", rho=0.65, edge_label="Zhao 2021 â†’ IRGM")),
        GraphEdge(data=GraphEdgeData(
            source="s2", target="g4", rho=0.62, edge_label="Zhao 2021 â†’ CCDC6")),
        GraphEdge(data=GraphEdgeData(
            source="s2", target="g5", rho=0.58, edge_label="Zhao 2021 â†’ FAM114A1")),
        GraphEdge(data=GraphEdgeData(
            source="s3", target="g2", rho=0.61, edge_label="Lin 2022 â†’ ATG7")),
        GraphEdge(data=GraphEdgeData(
            source="s3", target="g6", rho=0.57, edge_label="Lin 2022 â†’ ULK1")),
        GraphEdge(data=GraphEdgeData(
            source="s3", target="g4", rho=0.54, edge_label="Lin 2022 â†’ CCDC6")),
        GraphEdge(data=GraphEdgeData(
            source="s4", target="g5", rho=-0.55, edge_label="Park 2023 â†’ FAM114A1")),
        GraphEdge(data=GraphEdgeData(
            source="s4", target="g1", rho=-0.48, edge_label="Park 2023 â†’ ATG5")),
        GraphEdge(data=GraphEdgeData(
            source="s5", target="g6", rho=0.43, edge_label="Huang 2021 â†’ ULK1")),
        GraphEdge(data=GraphEdgeData(
            source="s5", target="g3", rho=0.39, edge_label="Huang 2021 â†’ IRGM")),
        GraphEdge(data=GraphEdgeData(
            source="s5", target="g5", rho=0.36, edge_label="Huang 2021 â†’ FAM114A1")),
    ],
)

_GENE_RATIONALES: dict[str, dict] = {
    "CCDC6": {
        "hypothesis": (
            "CCDC6 (coiled-coil domain containing 6) co-clusters with core autophagy machinery "
            "(ATG5, ATG7, IRGM) across 4 of 8 matched screens, with a mean Spearman Ï of 0.71 "
            "to the query screen. Despite only 23 indexed publications, its pathway-correlation "
            "profile is indistinguishable from established autophagy genes, suggesting a "
            "functional role in autophagic flux or selective cargo recognition."
        ),
        "mechanistic_context": (
            "CCDC6 is known primarily as a fusion partner in thyroid carcinoma (RET/PTC "
            "rearrangements), where it acts as a substrate for ATM-mediated DNA damage "
            "checkpointing. However, its role in non-malignant macrophage biology is completely "
            "uncharacterized. The co-occurrence pattern with IFNÎ³-responsive genes (TBK1, IRGM) "
            "in matched screens suggests a potential regulatory node connecting innate immune "
            "signaling to autophagic clearance â€” a mechanism consistent with the itaconate/Irg1 "
            "axis being studied."
        ),
        "citations": [
            {"text": "Orvedahl et al. (2019) Nature Immunology", "pmid": "31097699"},
            {"text": "Zhao et al. (2021) Cell Reports",           "pmid": "33782614"},
            {"text": "Lin et al. (2022) eLife",                    "pmid": "35124892"},
        ],
        "suggested_validation": (
            "Orthogonal validation via CRISPRi depletion in bone-marrow-derived macrophages with "
            "IFNÎ³/LPS co-stimulation. Assess LC3-II flux by western blot and p62/SQSTM1 "
            "accumulation as proxies for autophagic activity."
        ),
    },
    "FAM114A1": {
        "hypothesis": (
            "FAM114A1 (family with sequence similarity 114 member A1) has only 8 indexed "
            "publications and appears in 3 matched screens correlated with macrophage death "
            "regulators. Its functional annotation is limited to 2 GO terms â€” it is among the "
            "highest-darkness candidates in this query."
        ),
        "mechanistic_context": (
            "FAM114A1 encodes a poorly characterized transmembrane protein with predicted "
            "coiled-coil domains. It localizes to the ER in proteomics studies but has no "
            "assigned molecular function. The co-occurrence with known autophagy receptors in "
            "matched screens is unexplained by existing literature â€” this is a true dark matter "
            "candidate."
        ),
        "citations": [
            {"text": "Zhao et al. (2021) Cell Reports",              "pmid": "33782614"},
            {"text": "Huang et al. (2021) Science Immunology",        "pmid": "33441802"},
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

async def run_query(request: QueryRequest) -> QueryResponse:
    from services.db_service import USE_PG, db_fetchall

    if not USE_PG:
        sig_count   = sum(1 for s in _MATCHED_SCREENS if s.fdr < 0.05)
        agree_count = sum(1 for s in _MATCHED_SCREENS if s.directionality == "agree")
        return QueryResponse(
            query_id=str(uuid4()),
            stats=QueryStats(
                screens_compared=287,
                significant_matches=sig_count,
                agree_directionality=agree_count,
                query_gene_count=len(request.genes),
            ),
            matched_screens=_MATCHED_SCREENS,
            dark_genes=_DARK_GENES,
            graph_elements=_GRAPH_ELEMENTS,
        )

    symbols = [g.symbol.upper() for g in request.genes] or ["ATG5"]
    gene_ph = ", ".join("?" * len(symbols))

    # nosec B608 — placeholders only, no user data in SQL
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
            COALESCE(sm.scores_size, 0)                         AS total_genes
        FROM reticle.harmonized_scores hs
        JOIN  reticle.screen_metadata          sm  ON hs.screen_id = sm.screen_id
        LEFT JOIN reticle.screen_metadata_curated smc ON hs.screen_id = smc.screen_id
        WHERE hs.gene_symbol IN ({gene_ph})
          AND hs.is_hit = 1
        GROUP BY sm.screen_id, sm.screen_name, sm.author, sm.organism_official,
                 smc.pmid, smc.selection_method, sm.screen_type, sm.cell_type,
                 sm.cell_line, smc.growth_direction, sm.scores_size
        ORDER BY shared_genes DESC, rho DESC
        LIMIT 20
    """, tuple(symbols))

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
        )
        for i, row in enumerate(screen_rows)
    ]

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
            detail=f"{dg.pubs} pubs Â· {dg.screens} screens",
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
                        edge_label=f"{row['screen_id']} â†’ {row['gene_symbol']}",
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

    # Use hit_screens as darkness proxy â€” more screens hit = better characterized
    dark_score = round(10.0 / math.log10(hit_screens + 2), 2)
    is_bright  = hit_screens > 50

    hypothesis = (
        f"{symbol} appears as a significant hit in {hit_screens} of {screens} CRISPR screens "
        f"(mean percentile score {avg_score:.3f}). "
        f"It is a {'well-characterized' if is_bright else 'dark'} candidate â€” "
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

