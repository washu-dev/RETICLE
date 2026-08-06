"""Tests for the canonical fast screen route and legacy pure similarity math."""

import numpy as np
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import routers.screen_similar as screen_similar_router
import routers.screens_aaron as screens_aaron_router
from main import app
from services.screen_sim import plain_pearson, screen_similar, weighted_pearson


def _fast_payload(screen: str) -> dict:
    return {
        "query": {
            "screen_id": screen,
            "author": "Orvedahl",
            "cell_line": "HeLa",
            "pmid": "31097699",
            "n_genes": 18470,
        },
        "n_pool": 962,
        "n_total": 2,
        "offset": 0,
        "background": {"mean_r": 0.01, "sd_r": 0.1},
        "n_same_study": 1,
        "exclude_same_study": False,
        "results": [
            {
                "screen_id": "2123",
                "r": 0.71,
                "z": 7.0,
                "overlap": 16000,
                "same_study": True,
                "author": "Behan",
                "cell_line": "KMS-12-BM",
                "pmid": "30971826",
                "n_genes": 18100,
            },
            {
                "screen_id": "1999",
                "r": 0.52,
                "z": 5.1,
                "overlap": 15800,
                "same_study": False,
                "author": "Dharma",
                "cell_line": "Calu-3",
                "pmid": "12345678",
                "n_genes": 17700,
            },
        ],
    }


class TestScreenSimilarEndpoint:
    def test_canonical_route_uses_precomputed_service(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        calls = []

        async def fake_get_screen_similar(
            screen: str,
            limit: int,
            offset: int,
            exclude_same_study: bool,
        ) -> dict:
            calls.append((screen, limit, offset, exclude_same_study))
            return _fast_payload(screen)

        monkeypatch.setattr(
            screen_similar_router,
            "get_screen_similar",
            fake_get_screen_similar,
        )
        r = client.get("/api/screen_similar", params={"screen": "12345"})
        assert r.status_code == 200
        data = r.json()
        assert calls == [("12345", 50, 0, False)]

        q = data["query"]
        assert set(q.keys()) == {"screen_id", "author", "cell_line", "pmid", "n_genes"}
        assert q["screen_id"] == "12345"
        assert isinstance(data["n_pool"], int)
        assert isinstance(data["n_total"], int)
        assert data["offset"] == 0

        assert isinstance(data["results"], list) and len(data["results"]) > 0
        row = data["results"][0]
        assert row["r"] == 0.71
        assert row["z"] == 7.0
        # Compatibility fields keep the legacy Explorer from crashing while
        # it transitions to the precomputed response contract.
        assert row["weighted"] == row["r"]
        assert row["plain"] == row["r"]
        assert isinstance(row["overlap"], int)

    def test_query_options_are_forwarded(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        calls = []

        async def fake_get_screen_similar(
            screen: str,
            limit: int,
            offset: int,
            exclude_same_study: bool,
        ) -> dict:
            calls.append((screen, limit, offset, exclude_same_study))
            payload = _fast_payload(screen)
            payload["offset"] = offset
            payload["results"] = payload["results"][offset : offset + limit]
            payload["exclude_same_study"] = exclude_same_study
            return payload

        monkeypatch.setattr(
            screen_similar_router,
            "get_screen_similar",
            fake_get_screen_similar,
        )
        response = client.get(
            "/api/screen_similar",
            params={
                "screen": "77",
                "limit": 1,
                "offset": 1,
                "exclude_same_study": "true",
            },
        )
        data = response.json()
        assert response.status_code == 200
        assert calls == [("77", 1, 1, True)]
        assert data["offset"] == 1
        assert len(data["results"]) == 1

    def test_missing_precomputed_screen_returns_404(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        async def fake_get_screen_similar(
            screen: str,
            limit: int,
            offset: int,
            exclude_same_study: bool,
        ) -> None:
            return None

        monkeypatch.setattr(
            screen_similar_router,
            "get_screen_similar",
            fake_get_screen_similar,
        )
        response = client.get("/api/screen_similar", params={"screen": "42"})
        assert response.status_code == 404

    def test_compatibility_alias_still_uses_fast_contract(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        async def fake_get_screen_similar(
            screen: str,
            limit: int,
            offset: int,
            exclude_same_study: bool,
        ) -> dict:
            return _fast_payload(screen)

        monkeypatch.setattr(
            screen_similar_router,
            "get_screen_similar",
            fake_get_screen_similar,
        )
        monkeypatch.setattr(
            screens_aaron_router,
            "get_screen_similar",
            fake_get_screen_similar,
        )

        canonical = client.get(
            "/api/screen_similar",
            params={"screen": "2123", "exclude_same_study": "true"},
        )
        compatibility = client.get(
            "/api/screen_similar_aaron",
            params={"screen": "2123", "exclude_same_study": "true"},
        )
        assert canonical.status_code == compatibility.status_code == 200
        canonical_payload = canonical.json()
        compatibility_payload = compatibility.json()
        assert canonical_payload["query"] == compatibility_payload["query"]
        assert canonical_payload["background"] == compatibility_payload["background"]
        for canonical_row, compatibility_row in zip(
            canonical_payload["results"],
            compatibility_payload["results"],
            strict=True,
        ):
            canonical_row.pop("weighted")
            canonical_row.pop("plain")
            assert canonical_row == compatibility_row

    def test_openapi_has_one_canonical_and_one_compatibility_route(
        self, client: TestClient
    ) -> None:
        schema = client.get("/api/openapi.json").json()
        assert "get" in schema["paths"]["/api/screen_similar"]
        assert "get" in schema["paths"]["/api/screen_similar_aaron"]

        paths = [
            route.path
            for route in app.routes
            if isinstance(route, APIRoute)
            and "GET" in route.methods
            and route.path
            in {"/api/screen_similar", "/api/screen_similar_aaron"}
        ]
        assert paths.count("/api/screen_similar") == 1
        assert paths.count("/api/screen_similar_aaron") == 1


class TestScreenSimilarValidation:
    def test_missing_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen_similar").status_code == 422

    def test_empty_screen_rejected(self, client: TestClient) -> None:
        assert client.get("/api/screen_similar?screen=").status_code == 422

    def test_non_digit_screen_rejected(self, client: TestClient) -> None:
        r = client.get("/api/screen_similar", params={"screen": "abc; DROP TABLE x"})
        assert r.status_code == 422

    def test_overlong_screen_rejected(self, client: TestClient) -> None:
        r = client.get("/api/screen_similar", params={"screen": "1" * 50})
        assert r.status_code == 422

    def test_out_of_range_limit_rejected(self, client: TestClient) -> None:
        r = client.get(
            "/api/screen_similar", params={"screen": "12345", "limit": 999}
        )
        assert r.status_code == 422


class TestWeightedPearson:
    """Pure math — hand-computed reference on two tiny vectors."""

    def test_matches_hand_computed_value(self) -> None:
        a = np.array([1.0, 2.0, 3.0])
        c = np.array([2.0, 1.0, 4.0])
        # w = |a|*|c| = [2, 2, 12]; weighted means aw=2.625, cw=3.375;
        # cov=0.640625, vaw=0.484375, vcw=1.234375 ->
        # cov / sqrt(vaw*vcw) = 0.8284941842352037.
        expected = 0.8284941842352037
        got = weighted_pearson(a, c)
        assert got is not None
        assert abs(got - expected) < 1e-6

    def test_zero_weight_returns_none(self) -> None:
        # All weights zero (one vector is all zeros) -> undefined.
        a = np.array([0.0, 0.0, 0.0])
        c = np.array([1.0, 2.0, 3.0])
        assert weighted_pearson(a, c) is None

    def test_zero_variance_returns_none(self) -> None:
        # c is constant -> weighted variance of c is zero -> undefined.
        a = np.array([1.0, 2.0, 3.0])
        c = np.array([5.0, 5.0, 5.0])
        assert weighted_pearson(a, c) is None

    def test_perfect_positive_correlation(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0])
        c = np.array([2.0, 4.0, 6.0, 8.0])
        got = weighted_pearson(a, c)
        assert got is not None
        assert abs(got - 1.0) < 1e-6


class TestPlainPearson:
    def test_plain_matches_numpy(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 5.0])
        c = np.array([2.0, 1.0, 4.0, 3.0])
        got = plain_pearson(a, c)
        assert got is not None
        assert abs(got - float(np.corrcoef(a, c)[0, 1])) < 1e-6

    def test_constant_returns_none(self) -> None:
        assert plain_pearson(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0])) is None


class TestScreenSimilarService:
    def test_mock_payload_shape(self) -> None:
        out = screen_similar("999", limit=50, offset=0)
        assert out is not None
        assert out["query"]["screen_id"] == "999"
        assert out["n_total"] == len(out["results"])
        assert all("weighted" in r for r in out["results"])
