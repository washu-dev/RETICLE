"""Tests for GET /api/screen/{screen_id} and the screen_detail service.

The service is exercised through its offline mock branch (USE_PG forced False),
so these run without a database. Validation tests need no DB at all.
"""

import pytest
from fastapi.testclient import TestClient

import services.db_service as db
from services.screen_detail import _is_display_gene, get_screen_detail


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the mock branch regardless of local AWS_DB_HOST / .env."""
    monkeypatch.setattr(db, "USE_PG", False)


class TestScreenDetailEndpoint:
    def test_offline_returns_200_and_shape(self, client: TestClient, offline: None) -> None:
        # 833 is a verified reference screen (Behan FM 2019, PMID 30971826).
        r = client.get("/api/screen/833")
        assert r.status_code == 200
        data = r.json()
        # camelCase aliases on the wire
        assert data["screenId"] == "833"
        assert data["biogridUrl"].endswith("/Screen/833")
        assert data["similarityAvailable"] is True
        # Link-out and citation are derived from the same verified pmid.
        assert data["pubmedUrl"] == "https://pubmed.ncbi.nlm.nih.gov/30971826"
        assert data["pmid"] == "30971826"
        assert data["citation"] and data["articleTitle"]
        assert isinstance(data["genes"], list) and len(data["genes"]) > 0
        g = data["genes"][0]
        # both the raw deposited and harmonized columns are present
        assert set(g.keys()) >= {"symbol", "percentile", "isHit", "harmonizedScore", "rawScore"}
        assert data["rawScoreLabel"]  # e.g. "Log2FC"

    def test_offline_unknown_id_omits_fabricated_pmid(
        self, client: TestClient, offline: None
    ) -> None:
        """An unknown mock id links to its real ORCS page but must NOT invent a
        pmid — a fabricated PubMed link is exactly the bug this replaced."""
        r = client.get("/api/screen/999999")
        assert r.status_code == 200
        data = r.json()
        assert data["biogridUrl"].endswith("/Screen/999999")
        assert data["pmid"] is None
        assert data["pubmedUrl"] is None
        assert data["similarityAvailable"] is False


class TestScreenValidation:
    def test_non_digit_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen/abc;DROP").status_code == 422

    def test_overlong_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen/" + "1" * 50).status_code == 422


class TestScreenDetailService:
    def test_mock_payload_shape(self, offline: None) -> None:
        d = get_screen_detail("833")
        assert d is not None
        assert d.screen_id == "833"
        assert d.n_hits and d.n_hits > 0
        assert d.genes and all(g.symbol for g in d.genes)
        # both raw and harmonized values are carried per gene
        assert any(g.raw_score is not None for g in d.genes)
        assert any(g.harmonized_score is not None for g in d.genes)
        # nothing shown should be a control / guide id
        assert all(_is_display_gene(g.symbol) for g in d.genes)


class TestReferenceScreens:
    """The offline path must only ever hand out resolvable link-outs."""

    def test_reference_ids_and_pmids_are_numeric(self) -> None:
        from services.reference_screens import REFERENCE_SCREENS

        assert REFERENCE_SCREENS
        for s in REFERENCE_SCREENS:
            assert s["screen_id"].isdigit(), s
            assert s["pmid"].isdigit(), s
            assert s["title"] and s["author"]

    def test_mock_matched_screens_link_out_cleanly(self, offline: None) -> None:
        from services.mock_data_service import _MATCHED_SCREENS

        for ms in _MATCHED_SCREENS:
            # biogrid id resolves to a numeric ORCS screen id (no "ORCS-" prefix)
            assert ms.biogrid_id.isdigit(), ms.biogrid_id
            # every pmid is a real numeric id, so /pubmed/{pmid} resolves
            assert ms.pmid.isdigit(), ms.pmid

    def test_article_meta_offline_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No network in tests: article_meta must fail soft, never raise."""
        import services.external_sources as ext

        def boom(*_a: object, **_k: object) -> bytes:
            raise OSError("no network in tests")

        monkeypatch.setattr(ext, "_get", boom)
        monkeypatch.setattr(ext, "_cache_get", lambda _k: ext._MISS)
        assert ext.article_meta("30971826") is None
        assert ext.article_meta("not-a-pmid") is None


class TestControlFilter:
    def test_filters_controls_and_guides(self) -> None:
        assert _is_display_gene("STAT1")
        assert not _is_display_gene("SGR000121914.1_XPR003.1")
        assert not _is_display_gene("NTC_001")
        assert not _is_display_gene("safe-harbor-1")
        assert not _is_display_gene("")
