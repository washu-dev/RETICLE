"""corpus_service.py — comparison-corpus filtering.

Turns a CorpusFilters object into a parameterized SQL predicate over the
`screen_metadata` (alias `sm`) / `screen_metadata_curated` (alias `smc`) pair,
and answers "how many screens match these filters?" for the live cohort counter.

'Any' / empty / all-selected values are no-ops, so the default (unfiltered)
request reproduces the full corpus — narrowing is opt-in.
"""

from models.query import CorpusFilters

# Full known vocabularies — used to detect "all selected" (a no-op).
_ALL_ASSAY_DOMAINS = {"fitness", "stress", "reporter", "other"}
_ALL_MODALITIES = {"KO", "CRISPRi", "CRISPRa", "RNAi", "Other"}

# Deterministic offline corpus size, so the counter is meaningful without a DB.
_MOCK_TOTAL = 1745
_MOCK_ORGANISM = {"Human": 1412, "Mouse": 333}
_MOCK_ASSAY = {"fitness": 611, "stress": 802, "reporter": 274, "other": 58}


def _organism_official(organism: str) -> str | None:
    if organism == "Human":
        return "Homo sapiens"
    if organism == "Mouse":
        return "Mus musculus"
    return None


def build_corpus_where(filters: CorpusFilters | None) -> tuple[str, list]:
    """Return an ` AND …`-prefixed SQL fragment + bind params for the given
    filters. Empty string when nothing narrows the corpus."""
    if filters is None:
        return "", []

    clauses: list[str] = []
    params: list = []

    org = _organism_official(filters.organism)
    if org is not None:
        clauses.append("sm.organism_official = ?")
        params.append(org)

    domains = [d for d in filters.assay_domains if d]
    if domains and set(domains) != _ALL_ASSAY_DOMAINS:
        placeholders = ", ".join("?" * len(domains))
        clauses.append(f"smc.assay_domain IN ({placeholders})")
        params.extend(domains)

    if filters.coverage and filters.coverage != "Any":
        clauses.append("sm.coverage_type = ?")
        params.append(filters.coverage)

    modalities = [m for m in filters.modalities if m]
    if modalities and set(modalities) != _ALL_MODALITIES:
        placeholders = ", ".join("?" * len(modalities))
        clauses.append(f"COALESCE(smc.screen_type, sm.screen_type) IN ({placeholders})")
        params.extend(modalities)

    cell_types = [c for c in filters.cell_types if c]
    if cell_types:
        # Free-text cell types → OR of case-insensitive LIKE matches.
        likes = " OR ".join("LOWER(sm.cell_type) LIKE ?" for _ in cell_types)
        clauses.append(f"({likes})")
        params.extend(f"%{c.lower()}%" for c in cell_types)

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def _mock_count(filters: CorpusFilters | None) -> int:
    """Deterministic offline estimate that responds to the filters so the UI
    counter demonstrably reacts without a database."""
    if filters is None:
        return _MOCK_TOTAL
    count = _MOCK_ORGANISM.get(filters.organism, _MOCK_TOTAL)
    domains = [d for d in filters.assay_domains if d]
    if domains and set(domains) != _ALL_ASSAY_DOMAINS:
        frac = sum(_MOCK_ASSAY.get(d, 0) for d in domains) / sum(_MOCK_ASSAY.values())
        count = round(count * frac)
    if filters.coverage == "FULL":
        count = round(count * 0.62)
    if [c for c in filters.cell_types if c]:
        count = round(count * 0.35)
    return max(0, count)


def corpus_count(filters: CorpusFilters | None) -> int:
    """Number of corpus screens matching `filters`."""
    from services.db_service import USE_PG, db_fetchall

    if not USE_PG:
        return _mock_count(filters)

    where, params = build_corpus_where(filters)
    # nosec B608 — `where` is built from fixed clauses; all values are bound params
    rows = db_fetchall(f"""
        SELECT COUNT(DISTINCT sm.screen_id) AS n
        FROM reticle.screen_metadata sm
        LEFT JOIN reticle.screen_metadata_curated smc ON sm.screen_id = smc.screen_id
        WHERE 1 = 1{where}
    """, tuple(params))
    return int(rows[0]["n"]) if rows else 0
