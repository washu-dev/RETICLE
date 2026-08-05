"""Tests for GET /api/coessential and the pure co-essentiality math.

Runs offline (USE_PG is False under conftest): the endpoint exercises the mock
branch, and the pure `network_from_matrix` is unit-tested on a hand-built R.
"""

import numpy as np
from fastapi.testclient import TestClient

from services.coessential import build_matrix, network_from_matrix


class TestCoessentialEndpoint:
    def test_offline_returns_200_and_shape(self, client: TestClient) -> None:
        r = client.get("/api/coessential", params={"symbol": "ATG5"})
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"symbol", "nodes", "edges", "n_screens"}
        assert data["symbol"] == "ATG5"
        assert isinstance(data["nodes"], list) and len(data["nodes"]) > 0
        assert isinstance(data["edges"], list)
        assert isinstance(data["n_screens"], int)

    def test_offline_focus_node_present(self, client: TestClient) -> None:
        data = client.get("/api/coessential", params={"symbol": "TP53"}).json()
        focus = [n for n in data["nodes"] if n["focus"]]
        assert len(focus) == 1
        assert focus[0]["name"] == "TP53"
        # Every node carries a lean label.
        assert all("lean" in n for n in data["nodes"])

    def test_org_defaults_when_unknown(self, client: TestClient) -> None:
        r = client.get(
            "/api/coessential", params={"symbol": "ATG5", "org": "Klingon"}
        )
        assert r.status_code == 200

    def test_mouse_org_accepted(self, client: TestClient) -> None:
        r = client.get(
            "/api/coessential",
            params={"symbol": "Atg5", "org": "Mus musculus"},
        )
        assert r.status_code == 200


class TestCoessentialValidation:
    def test_missing_symbol_rejected(self, client: TestClient) -> None:
        assert client.get("/api/coessential").status_code == 422

    def test_empty_symbol_rejected(self, client: TestClient) -> None:
        assert client.get("/api/coessential?symbol=").status_code == 422

    def test_injection_attempt_rejected(self, client: TestClient) -> None:
        r = client.get(
            "/api/coessential", params={"symbol": "TP53; DROP TABLE x"}
        )
        assert r.status_code == 422

    def test_overlong_symbol_rejected(self, client: TestClient) -> None:
        r = client.get("/api/coessential", params={"symbol": "A" * 50})
        assert r.status_code == 422


class TestNetworkFromMatrix:
    """Pure math on a hand-built 3-gene R (rows are already L2-normalized)."""

    def _fixture(self) -> tuple:
        # A ~ B (cosine 0.9); A ~ C (cosine 0.1, below r_min so excluded).
        R = np.array(
            [
                [1.0, 0.0],
                [0.9, np.sqrt(1 - 0.81)],
                [0.1, np.sqrt(1 - 0.01)],
            ],
            dtype=np.float32,
        )
        genes = ["A", "B", "C"]
        lean = np.array([-0.5, -0.3, 0.2])
        return R, genes, lean

    def test_neighbour_and_edge_selection(self) -> None:
        R, genes, lean = self._fixture()
        out = network_from_matrix(R, genes, lean, n_screens=42, symbol="A")
        assert out is not None
        assert out["symbol"] == "A"
        assert out["n_screens"] == 42

        names = [n["name"] for n in out["nodes"]]
        # B is a neighbour (0.9 >= 0.25); C is not (0.1 < 0.25).
        assert names == ["A", "B"]
        assert out["nodes"][0]["focus"] is True
        assert out["nodes"][1]["focus"] is False
        # Lean labels come from the lean vector.
        assert out["nodes"][0]["lean"] == "essential"
        assert out["nodes"][1]["lean"] == "essential"

        # Exactly one edge: A-B (0.9 >= 0.30).
        assert len(out["edges"]) == 1
        edge = out["edges"][0]
        assert {edge["a"], edge["b"]} == {"A", "B"}
        assert edge["r"] == 0.9
        assert abs(edge["score"] - 0.9) < 1e-5

    def test_case_insensitive_match(self) -> None:
        R, genes, lean = self._fixture()
        out = network_from_matrix(R, genes, lean, n_screens=5, symbol="a")
        assert out is not None
        # Returns the matrix's stored casing.
        assert out["symbol"] == "A"

    def test_unknown_symbol_returns_none(self) -> None:
        R, genes, lean = self._fixture()
        assert network_from_matrix(R, genes, lean, 5, "ZZZ") is None


class TestBuildMatrix:
    def test_coverage_filter_and_normalization(self) -> None:
        # 2 genes across 40 screens; both fully measured so both survive the
        # max(30, int(0.11*S)) = 30 coverage floor.
        rows = []
        for s in range(40):
            rows.append({"g": "G1", "s": s, "p": 0.5 if s % 2 else -0.5})
            rows.append({"g": "G2", "s": s, "p": -0.5 if s % 2 else 0.5})
        # A sparse gene measured in only 3 screens is dropped.
        for s in range(3):
            rows.append({"g": "SPARSE", "s": s, "p": 0.1})

        R, genes, lean, n_screens = build_matrix(rows)
        assert n_screens == 40
        assert set(genes) == {"G1", "G2"}
        # Rows are unit-normalized.
        norms = np.linalg.norm(R, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-4)

    def test_empty_input(self) -> None:
        R, genes, lean, n_screens = build_matrix([])
        assert genes == []
        assert n_screens == 0
