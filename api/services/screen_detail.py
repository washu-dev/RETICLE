"""screen_detail.py — one screen's metadata + its gene/score list.

Powers GET /api/screen/{screen_id}: given a BioGRID ORCS screen id, return the
screen's metadata (joined across screen_metadata + screen_metadata_curated) plus
a capped, control-filtered list of its genes ranked by hit then |score|.

Follows the USE_PG dual path: a deterministic mock payload offline, real RDS
otherwise. Mirrors the harmonized_scores join in explorer_gene.get_gene_payload,
but keyed by screen_id (indexed by idx_hs_screen) instead of gene_symbol.
"""

import re

from models.query import ScreenDetail, ScreenGene
from services.explorer_gene import is_control

# Guide-level / sgRNA identifiers that ride along in gene_symbol but aren't genes
# (e.g. "SGR000121914.1_XPR003.1"). is_control() handles NTC/safe-harbor/reporter;
# this covers the guide-id shapes on top of that.
_GUIDE_RE = re.compile(r"(^SGR\d|_XPR|_SG\d|^SGR000)", re.I)

GENE_CAP = 200
BIOGRID_SCREEN_URL = "https://orcs.thebiogrid.org/Screen/"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/"


def _is_display_gene(sym: str) -> bool:
    """A real, showable gene symbol (not a control or a guide id)."""
    return bool(sym) and not is_control(sym) and not _GUIDE_RE.search(sym)


def _mock_screen_detail(screen_id: str) -> ScreenDetail:
    """Deterministic offline payload so the endpoint works without a DB."""
    genes = [
        ScreenGene(symbol=s, percentile=p, is_hit=True, harmonized_score=h, robust_z=z)
        for s, p, h, z in [
            ("IFNGR1", 1.0, 11.3, 4.96), ("STAT1", 0.999, 9.55, 4.21),
            ("IFNGR2", 0.998, 9.28, 4.09), ("JAK2", 0.996, 8.7, 3.9),
            ("B2M", 0.994, 8.1, 3.6), ("TAP1", 0.99, 7.4, 3.3),
        ]
    ]
    return ScreenDetail(
        screen_id=str(screen_id),
        biogrid_url=f"{BIOGRID_SCREEN_URL}{screen_id}",
        pmid="31509742",
        pubmed_url=f"{PUBMED_URL}31509742",
        author="Freeman AJ (2019)",
        name=f"Mock screen {screen_id}",
        organism="Mus musculus",
        cell_line="B16-F10",
        cell_type="Melanoma Cell Line",
        screen_type="Phenotype Screen",
        modality="KO",
        analysis="MaGeCK",
        methodology="Knockout",
        phenotype="protein/peptide accumulation",
        rationale="Regulation of MHC I expression after IFNgamma exposure",
        coverage_type="FULL",
        assay_domain="reporter",
        condition_name="Interferon gamma",
        growth_direction="none",
        score_basis="DIR_POS(Log2FC)",
        is_directional=True,
        scores_size=20570,
        n_genes=20570,
        n_hits=1066,
        genes_shown=len(genes),
        genes=genes,
    )


def get_screen_detail(screen_id: str, gene_cap: int = GENE_CAP) -> ScreenDetail | None:
    """Screen metadata + top genes, or None when the screen id is unknown."""
    from services.db_service import USE_PG, db_fetchall

    sid = str(screen_id).strip()
    if not USE_PG:
        return _mock_screen_detail(sid)

    meta = db_fetchall(
        """SELECT sm.screen_id, sm.author, sm.screen_name, sm.scores_size, sm.analysis,
                  sm.screen_type, sm.methodology, sm.cell_line, sm.cell_type, sm.phenotype,
                  sm.organism_official, sm.screen_rationale, sm.coverage_type,
                  sm.score_basis, sm.is_directional,
                  smc.pmid, smc.assay_domain, smc.selection_method,
                  smc.condition_name, smc.growth_direction
           FROM screen_metadata sm
           LEFT JOIN screen_metadata_curated smc ON sm.screen_id = smc.screen_id
           WHERE sm.screen_id = ?
           LIMIT 1""",
        (sid,),
    )
    if not meta:
        return None
    m = meta[0]

    counts = db_fetchall(
        "SELECT COUNT(*) AS n, COALESCE(SUM(is_hit), 0) AS hits "
        "FROM harmonized_scores WHERE screen_id = ?",
        (sid,),
    )
    n_genes = int(counts[0]["n"]) if counts else 0
    n_hits = int(counts[0]["hits"]) if counts else 0

    # Hits first, then strongest by |percentile|. Over-fetch to survive control
    # filtering, then cap. ABS() works on both Postgres and SQLite.
    rows = db_fetchall(
        """SELECT gene_symbol, percentile_score, is_hit, harmonized_score, robust_z_score
           FROM harmonized_scores
           WHERE screen_id = ? AND percentile_score IS NOT NULL
           ORDER BY is_hit DESC, ABS(percentile_score) DESC
           LIMIT ?""",
        (sid, gene_cap * 3),
    )

    genes: list[ScreenGene] = []
    for r in rows:
        sym = str(r["gene_symbol"])
        if not _is_display_gene(sym):
            continue
        genes.append(ScreenGene(
            symbol=sym,
            percentile=_f(r["percentile_score"]),
            is_hit=bool(r["is_hit"]),
            harmonized_score=_f(r["harmonized_score"]),
            robust_z=_f(r["robust_z_score"]),
        ))
        if len(genes) >= gene_cap:
            break

    pmid = str(m["pmid"]) if m["pmid"] else None
    return ScreenDetail(
        screen_id=sid,
        biogrid_url=f"{BIOGRID_SCREEN_URL}{sid}",
        pmid=pmid,
        pubmed_url=f"{PUBMED_URL}{pmid}" if pmid else None,
        author=_s(m["author"]),
        name=_s(m["screen_name"]),
        organism=_s(m["organism_official"]),
        cell_line=_s(m["cell_line"]),
        cell_type=_s(m["cell_type"]),
        screen_type=_s(m["screen_type"]),
        modality=_s(m["selection_method"]) or _s(m["screen_type"]),
        analysis=_s(m["analysis"]),
        methodology=_s(m["methodology"]),
        phenotype=_s(m["phenotype"]),
        rationale=_s(m["screen_rationale"]),
        coverage_type=_s(m["coverage_type"]),
        assay_domain=_s(m["assay_domain"]),
        condition_name=_s(m["condition_name"]),
        growth_direction=_s(m["growth_direction"]),
        score_basis=_s(m["score_basis"]),
        is_directional=bool(m["is_directional"]) if m["is_directional"] is not None else None,
        scores_size=int(m["scores_size"]) if m["scores_size"] is not None else None,
        n_genes=n_genes,
        n_hits=n_hits,
        genes_shown=len(genes),
        genes=genes,
    )


def _s(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _f(v: object) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
