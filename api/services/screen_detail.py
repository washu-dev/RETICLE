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


# Illustrative genes for the offline payload. All resolve in the offline gene
# lookup (mock_data_service), so clicking one from the drawer opens a real card.
_MOCK_GENES = [
    ScreenGene(symbol=s, percentile=p, is_hit=hit, harmonized_score=h, robust_z=z, raw_score=raw)
    for s, p, hit, h, z, raw in [
        ("ATG5", 0.998, True, 10.9, 4.71, -2.84), ("ATG7", 0.996, True, 9.82, 4.30, -2.61),
        ("ULK1", 0.993, True, 8.74, 3.95, -2.30), ("BECN1", 0.988, True, 7.91, 3.58, -2.02),
        ("IRGM", 0.981, True, 7.05, 3.21, -1.77), ("MAP1LC3B", 0.812, False, 3.10, 1.34, -0.71),
    ]
]


def _mock_screen_detail(screen_id: str) -> ScreenDetail:
    """Deterministic offline payload built from a *verified real* ORCS screen so
    both link-outs resolve. When `screen_id` is one of the reference screens we
    return that one; otherwise we default to a verified screen but keep the
    clicked id's ORCS page (real) and omit a (would-be fabricated) pmid."""
    from services.reference_screens import BY_ID, REFERENCE_SCREENS, citation_for

    known = BY_ID.get(str(screen_id))
    entry = known or REFERENCE_SCREENS[0]
    # The ORCS link always points at the clicked screen's real page. A pmid is
    # attached only for a known reference screen — we never fabricate one for an
    # unknown id (fabricated PubMed links were the original bug).
    pmid = entry["pmid"] if known else None

    return ScreenDetail(
        screen_id=str(screen_id),
        biogrid_url=f"{BIOGRID_SCREEN_URL}{screen_id}",
        similarity_available=known is not None,
        pmid=pmid,
        pubmed_url=f"{PUBMED_URL}{pmid}" if pmid else None,
        author=entry["author"],
        name=entry["title"],
        article_title=entry["title"] if pmid else None,
        citation=citation_for(entry) if pmid else None,
        organism=entry["organism"],
        cell_line=entry["cell_line"],
        cell_type=entry["cell_type"],
        screen_type="Fitness Screen",
        modality=entry["modality"],
        analysis="MAGeCK",
        methodology="Knockout",
        phenotype=entry["phenotype"],
        rationale=entry["title"],
        coverage_type="FULL",
        assay_domain="fitness",
        condition_name=None,
        growth_direction="none",
        score_basis="DIR_NEG(Log2FC)",
        raw_score_label="Log2FC",
        is_directional=True,
        scores_size=18009,
        n_genes=18009,
        n_hits=sum(1 for g in _MOCK_GENES if g.is_hit),
        genes_shown=len(_MOCK_GENES),
        genes=list(_MOCK_GENES),
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
                  smc.condition_name, smc.growth_direction,
                  EXISTS (
                      SELECT 1 FROM screen_sim_meta sim
                      WHERE CAST(sim.screen_id AS TEXT) = CAST(sm.screen_id AS TEXT)
                  ) AS similarity_available
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
    # filtering, then cap. Includes the raw deposited score alongside the
    # harmonized columns so the UI can show both.
    rows = _fetch_screen_genes(sid, gene_cap * 3)

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
            raw_score=_f(r["raw_score"]) if "raw_score" in r else None,
        ))
        if len(genes) >= gene_cap:
            break

    pmid = str(m["pmid"]) if m["pmid"] else None
    score_basis = _s(m["score_basis"])
    article = _verified_article(pmid)
    return ScreenDetail(
        screen_id=sid,
        biogrid_url=f"{BIOGRID_SCREEN_URL}{sid}",
        similarity_available=bool(m["similarity_available"]),
        pmid=pmid,
        pubmed_url=f"{PUBMED_URL}{pmid}" if pmid else None,
        author=_s(m["author"]),
        name=_s(m["screen_name"]),
        article_title=(article or {}).get("title"),
        citation=(article or {}).get("citation"),
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
        score_basis=score_basis,
        raw_score_label=_raw_score_label(score_basis),
        is_directional=bool(m["is_directional"]) if m["is_directional"] is not None else None,
        scores_size=int(m["scores_size"]) if m["scores_size"] is not None else None,
        n_genes=n_genes,
        n_hits=n_hits,
        genes_shown=len(genes),
        genes=genes,
    )


def _fetch_screen_genes(sid: str, limit: int) -> list:
    """Genes for a screen, hits first then strongest by |percentile|.

    Prefers the raw deposited score (raw_score) alongside the harmonized columns;
    falls back to the harmonized-only shape if the raw column isn't present in
    this deployment's schema, so the endpoint never 500s on a column mismatch.
    ABS() works on both Postgres and SQLite.
    """
    from services.db_service import db_fetchall

    order = "ORDER BY is_hit DESC, ABS(percentile_score) DESC LIMIT ?"
    try:
        return db_fetchall(
            "SELECT gene_symbol, percentile_score, is_hit, harmonized_score, "
            f"robust_z_score, raw_score FROM harmonized_scores "
            f"WHERE screen_id = ? AND percentile_score IS NOT NULL {order}",
            (sid, limit),
        )
    except Exception:
        return db_fetchall(
            "SELECT gene_symbol, percentile_score, is_hit, harmonized_score, "
            f"robust_z_score FROM harmonized_scores "
            f"WHERE screen_id = ? AND percentile_score IS NOT NULL {order}",
            (sid, limit),
        )


def _raw_score_label(score_basis: str | None) -> str | None:
    """Human label for the raw score column, parsed from score_basis.

    score_basis looks like 'DIR_NEG(Log2FC)' or 'DIR_POS(BayesFactor)'; we surface
    the inner metric name so the table header reads 'Raw (Log2FC)' rather than an
    opaque code. Returns the basis unchanged if it doesn't match that shape.
    """
    if not score_basis:
        return None
    m = re.search(r"\(([^)]+)\)", score_basis)
    return m.group(1).strip() if m else score_basis


def _verified_article(pmid: str | None) -> dict | None:
    """Resolve a pmid to verified article metadata (title + citation), best-effort.
    Never raises into the request path; returns None offline or on any failure."""
    if not pmid:
        return None
    try:
        from services.external_sources import article_meta
        meta = article_meta(pmid)
        return meta if isinstance(meta, dict) else None
    except Exception:
        return None


def _s(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _f(v: object) -> float | None:
    try:
        # v is an arbitrary DB cell (object); non-floatable values raise below.
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
