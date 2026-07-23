"""Tests for GET /api/screen_similar and the pure weighted-Pearson math.

Runs offline (USE_PG is False under conftest): the endpoint exercises the mock
branch, and the ranking metric `weighted_pearson` is unit-tested against a
hand-computed value on two tiny synthetic vectors.
"""

import numpy as np
from fastapi.testclient import TestClient

from services.screen_sim import plain_pearson, screen_similar, weighted_pearson


class TestScreenSimilarEndpoint:
    def test_offline_returns_200_and_shape(self, client: TestClient) -> None:
        r = client.get("/api/screen_similar", params={"screen": "12345"})
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"query", "n_pool", "n_total", "offset", "results"}

        q = data["query"]
        assert set(q.keys()) == {"screen_id", "author", "cell_line", "pmid", "n_genes"}
        assert q["screen_id"] == "12345"
        assert isinstance(data["n_pool"], int)
        assert isinstance(data["n_total"], int)
        assert data["offset"] == 0

        assert isinstance(data["results"], list) and len(data["results"]) > 0
        row = data["results"][0]
        assert set(row.keys()) == {
            "screen_id", "weighted", "plain", "overlap",
            "author", "cell_line", "pmid", "n_genes",
        }
        assert isinstance(row["overlap"], int)

    def test_offline_results_sorted_by_weighted_desc(self, client: TestClient) -> None:
        data = client.get("/api/screen_similar", params={"screen": "77"}).json()
        weights = [r["weighted"] for r in data["results"]]
        assert weights == sorted(weights, reverse=True)

    def test_pagination_params_respected(self, client: TestClient) -> None:
        data = client.get(
            "/api/screen_similar",
            params={"screen": "77", "limit": 1, "offset": 1},
        ).json()
        assert data["offset"] == 1
        assert len(data["results"]) <= 1


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
