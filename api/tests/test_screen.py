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
        r = client.get("/api/screen/1839")
        assert r.status_code == 200
        data = r.json()
        # camelCase aliases on the wire
        assert data["screenId"] == "1839"
        assert data["biogridUrl"].endswith("/Screen/1839")
        assert data["pubmedUrl"].startswith("https://pubmed.ncbi.nlm.nih.gov/")
        assert isinstance(data["genes"], list) and len(data["genes"]) > 0
        g = data["genes"][0]
        assert set(g.keys()) >= {"symbol", "percentile", "isHit"}


class TestScreenValidation:
    def test_non_digit_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen/abc;DROP").status_code == 422

    def test_overlong_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen/" + "1" * 50).status_code == 422


class TestScreenDetailService:
    def test_mock_payload_shape(self, offline: None) -> None:
        d = get_screen_detail("1839")
        assert d is not None
        assert d.screen_id == "1839"
        assert d.n_hits and d.n_hits > 0
        assert d.genes and all(g.symbol for g in d.genes)
        # nothing shown should be a control / guide id
        assert all(_is_display_gene(g.symbol) for g in d.genes)


class TestControlFilter:
    def test_filters_controls_and_guides(self) -> None:
        assert _is_display_gene("STAT1")
        assert not _is_display_gene("SGR000121914.1_XPR003.1")
        assert not _is_display_gene("NTC_001")
        assert not _is_display_gene("safe-harbor-1")
        assert not _is_display_gene("")
