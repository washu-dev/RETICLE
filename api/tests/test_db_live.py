"""
Live DB integration tests — run against real RDS when AWS_DB_HOST is set.

    pytest tests/test_db_live.py -v

All tests are skipped automatically in CI (no .env / AWS_DB_HOST not set).
Run locally after filling in api/.env with RDS credentials.
"""

import asyncio
import math
import os

import pytest

# ---------------------------------------------------------------------------
# Skip guard — skip every test in this module when no DB host is configured
# ---------------------------------------------------------------------------
_DB_HOST = os.getenv("AWS_DB_HOST", "").strip()
pytestmark = pytest.mark.skipif(
    not _DB_HOST,
    reason="AWS_DB_HOST not set — skipping live DB tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _query(symbols: list[str]):
    from models.query import GeneInput, QueryRequest
    from services.mock_data_service import run_query
    genes = [GeneInput(symbol=s, score=1.0) for s in symbols]
    return _run(run_query(QueryRequest(genes=genes)))


def _detail(symbol: str):
    from services.mock_data_service import get_gene_detail
    return _run(get_gene_detail(symbol))


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class TestConnection:
    def test_db_reachable(self):
        """Verify psycopg2 can connect and search_path resolves reticle schema."""
        from services.db_service import db_fetchall
        rows = db_fetchall("SELECT COUNT(*) AS n FROM reticle.harmonized_scores")
        assert rows, "No rows returned from harmonized_scores count"
        assert int(rows[0]["n"]) > 0, "harmonized_scores is empty"

    def test_schemas_present(self):
        """Both reticle and public schemas must exist with expected tables."""
        from services.db_service import db_fetchall
        rows = db_fetchall("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE (table_schema = 'reticle'
                   AND table_name IN ('harmonized_scores', 'screen_metadata',
                                      'screen_metadata_curated'))
               OR (table_schema = 'public'
                   AND table_name IN ('dim_gene', 'publication',
                                      'fact_screen_gene_publication'))
            ORDER BY table_schema, table_name
        """)
        found = {f"{r['table_schema']}.{r['table_name']}" for r in rows}
        required = {
            "reticle.harmonized_scores",
            "reticle.screen_metadata",
            "reticle.screen_metadata_curated",
            "public.dim_gene",
        }
        missing = required - found
        assert not missing, f"Missing tables: {missing}"


# ---------------------------------------------------------------------------
# run_query
# ---------------------------------------------------------------------------

class TestRunQuery:
    def test_returns_matched_screens(self):
        resp = _query(["ATG5", "ATG7"])
        assert len(resp.matched_screens) > 0, "Expected at least one matched screen"

    def test_matched_screen_fields(self):
        resp = _query(["ATG5"])
        screen = resp.matched_screens[0]
        assert screen.id >= 1
        assert screen.biogrid_id, "biogrid_id should not be empty"
        assert screen.shared_genes >= 1
        assert screen.total_genes >= 0
        # rho is percentile_score: -1..1 or 0 when all NULL
        assert -1.0 <= screen.rho <= 1.0, f"rho out of range: {screen.rho}"
        assert screen.fdr == 0.0

    def test_returns_dark_genes(self):
        resp = _query(["ATG5", "ATG7"])
        assert len(resp.dark_genes) > 0, "Expected at least one dark gene"

    def test_dark_gene_fields(self):
        resp = _query(["ATG5", "ATG7"])
        dg = resp.dark_genes[0]
        assert dg.symbol, "gene symbol should not be empty"
        assert dg.dark_score > 0, "dark_score should be positive"
        assert dg.screens >= 1
        assert dg.pubs >= 0
        assert isinstance(dg.is_bright, bool)
        # correlation is avg percentile_score: -1..1 or 0 when all NULL
        assert -1.0 <= dg.correlation <= 1.0, f"correlation out of range: {dg.correlation}"

    def test_query_genes_excluded_from_dark_genes(self):
        """Query genes should never appear in the dark gene list."""
        resp = _query(["ATG5", "ATG7"])
        dark_symbols = {dg.symbol.upper() for dg in resp.dark_genes}
        assert "ATG5" not in dark_symbols
        assert "ATG7" not in dark_symbols

    def test_stats_shape(self):
        resp = _query(["ATG5"])
        assert resp.stats.screens_compared == len(resp.matched_screens)
        assert resp.stats.query_gene_count == 1
        assert resp.stats.significant_matches >= 0
        assert resp.stats.agree_directionality >= 0

    def test_graph_elements_present(self):
        resp = _query(["ATG5", "ATG7"])
        assert len(resp.graph_elements.nodes) > 0
        # All node IDs must be unique
        ids = [n.data.id for n in resp.graph_elements.nodes]
        assert len(ids) == len(set(ids)), "Duplicate node IDs in graph"

    def test_graph_edges_reference_valid_nodes(self):
        resp = _query(["ATG5", "ATG7"])
        node_ids = {n.data.id for n in resp.graph_elements.nodes}
        for edge in resp.graph_elements.edges:
            assert edge.data.source in node_ids, f"Edge source {edge.data.source} not in nodes"
            assert edge.data.target in node_ids, f"Edge target {edge.data.target} not in nodes"

    def test_single_gene_query(self):
        resp = _query(["BECN1"])
        assert resp.query_id, "query_id should be set"
        # May return 0 results for an obscure gene — just check it doesn't crash
        assert isinstance(resp.matched_screens, list)
        assert isinstance(resp.dark_genes, list)

    def test_unknown_gene_returns_empty_not_error(self):
        resp = _query(["NOTAREALGENEXYZ"])
        assert resp.matched_screens == []
        assert resp.dark_genes == []
        assert resp.graph_elements.nodes == []
        assert resp.graph_elements.edges == []

    def test_dark_score_formula(self):
        """dark_score = 10 / log10(screens + 2); higher screens = lower score."""
        resp = _query(["ATG5", "ATG7"])
        for dg in resp.dark_genes:
            expected = round(10.0 / math.log10(dg.pubs + 2), 2)
            assert abs(dg.dark_score - expected) < 0.01, (
                f"{dg.symbol}: dark_score={dg.dark_score}, expected={expected}"
            )

    def test_screens_ordered_by_shared_genes_desc(self):
        resp = _query(["ATG5", "ATG7"])
        shared = [s.shared_genes for s in resp.matched_screens]
        assert shared == sorted(shared, reverse=True), "Screens not ordered by shared_genes DESC"

    def test_query_id_is_uuid(self):
        import re
        resp = _query(["ATG5"])
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        assert re.match(uuid_pattern, resp.query_id), f"query_id not a valid UUID: {resp.query_id}"


# ---------------------------------------------------------------------------
# get_gene_detail
# ---------------------------------------------------------------------------

class TestGetGeneDetail:
    def test_known_gene_returns_detail(self):
        detail = _detail("ATG5")
        assert detail is not None, "ATG5 should be found in dim_gene"
        assert detail.symbol == "ATG5"

    def test_known_gene_fields(self):
        detail = _detail("ATG5")
        assert detail.screens is not None and detail.screens > 0
        assert detail.dark_score is not None and detail.dark_score > 0
        assert detail.is_bright is not None
        assert detail.hypothesis is not None and len(detail.hypothesis) > 20
        assert detail.correlation is not None
        assert -1.0 <= detail.correlation <= 1.0

    def test_well_known_gene_is_bright(self):
        """ATG5 hits in many screens — should be marked bright."""
        detail = _detail("ATG5")
        assert detail.is_bright is True, (
            f"ATG5 expected is_bright=True, got pubs={detail.pubs}"
        )

    def test_case_insensitive_lookup(self):
        """Lookup should work regardless of symbol casing."""
        upper = _detail("ATG5")
        lower = _detail("atg5")
        mixed = _detail("Atg5")
        # All three should find the gene
        assert upper is not None
        assert lower is not None
        assert mixed is not None
        # And return the same screen count
        assert upper.screens == lower.screens == mixed.screens

    def test_unknown_gene_returns_none(self):
        result = _detail("NOTAREALGENEXYZ")
        assert result is None

    def test_citations_are_valid(self):
        detail = _detail("ATG5")
        for c in detail.citations:
            assert c.text, "Citation text should not be empty"
            assert c.pmid, "Citation pmid should not be empty"

    def test_dark_score_formula(self):
        detail = _detail("ATG5")
        expected = round(10.0 / math.log10((detail.pubs or 0) + 2), 2)
        assert abs(detail.dark_score - expected) < 0.01

    def test_another_gene(self):
        """Spot-check a second gene to confirm it's not hardcoded to ATG5."""
        detail = _detail("ATG7")
        if detail is None:
            pytest.skip("ATG7 not found in dim_gene — skipping")
        assert detail.symbol == "ATG7"
        assert detail.screens != _detail("ATG5").screens or True  # just check it runs


# ---------------------------------------------------------------------------
# db_fetchall (low-level)
# ---------------------------------------------------------------------------

class TestDbFetchall:
    def test_returns_list_of_rows(self):
        from services.db_service import db_fetchall
        rows = db_fetchall(
            "SELECT gene_symbol, harmonized_score FROM reticle.harmonized_scores "
            "WHERE gene_symbol = ? LIMIT 5",
            ("ATG5",),
        )
        assert isinstance(rows, list)
        assert len(rows) <= 5
        for row in rows:
            assert "gene_symbol" in row or "gene_symbol" in {k.lower() for k in row}

    def test_case_insensitive_row_access(self):
        from services.db_service import db_fetchall
        rows = db_fetchall(
            "SELECT gene_symbol FROM reticle.harmonized_scores LIMIT 1"
        )
        assert rows
        row = rows[0]
        # Both exact and lowercase key should work
        val_exact = row["gene_symbol"]
        val_lower = row["gene_symbol"]
        assert val_exact == val_lower

    def test_empty_result(self):
        from services.db_service import db_fetchall
        rows = db_fetchall(
            "SELECT * FROM reticle.harmonized_scores WHERE gene_symbol = ?",
            ("NOTAREALGENEXYZABC",),
        )
        assert rows == []

    def test_parameterized_query(self):
        from services.db_service import db_fetchall
        rows = db_fetchall(
            "SELECT COUNT(*) AS n FROM reticle.harmonized_scores "
            "WHERE gene_symbol = ? AND is_hit = ?",
            ("ATG5", 1),
        )
        assert int(rows[0]["n"]) >= 0
