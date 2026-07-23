"""Tests for POST /api/pathways and the Enrichr enrichment service.

CI runs offline (USE_PG is False) — but unlike the DB endpoints, enrichment
reaches out over HTTP rather than to the database, so USE_PG does not gate it.
We therefore never make a real network call: the endpoint tests patch
`enrich_pathways` with a canned list, and the service test patches httpx so the
two-step Enrichr flow can be exercised deterministically.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from services import enrichment

# A canned Enrichr result set: three rows, one of which is above the adj-p cutoff.
_CANNED_TERMS = [
    {
        "term": "Autophagy R-HSA-9612973",
        "p_value": 1e-8,
        "adj_p_value": 1e-6,
        "combined_score": 210.5,
        "overlap_genes": ["ATG5", "ATG7"],
    },
    {
        "term": "Macroautophagy R-HSA-1632852",
        "p_value": 3e-5,
        "adj_p_value": 4e-4,
        "combined_score": 88.2,
        "overlap_genes": ["ULK1"],
    },
]


class TestPathwaysEndpoint:
    def test_returns_200_and_shape(self, client: TestClient, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "routers.pathways.enrich_pathways",
            lambda genes, library="Reactome_2022": list(_CANNED_TERMS),
        )
        resp = client.post("/api/pathways", json={"genes": ["ATG5", "ATG7", "ULK1"]})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"library", "terms"}
        assert data["library"] == "Reactome_2022"
        assert isinstance(data["terms"], list)
        assert len(data["terms"]) == 2
        first = data["terms"][0]
        assert set(first) == {
            "term",
            "p_value",
            "adj_p_value",
            "combined_score",
            "overlap_genes",
        }
        assert isinstance(first["overlap_genes"], list)

    def test_library_is_echoed(self, client: TestClient, monkeypatch: Any) -> None:
        seen: dict[str, Any] = {}

        def fake(genes: list[str], library: str = "Reactome_2022") -> list[dict]:
            seen["genes"] = genes
            seen["library"] = library
            return []

        monkeypatch.setattr("routers.pathways.enrich_pathways", fake)
        resp = client.post(
            "/api/pathways",
            json={"genes": ["TP53"], "library": "GO_Biological_Process_2021"},
        )
        assert resp.status_code == 200
        assert resp.json()["library"] == "GO_Biological_Process_2021"
        assert seen["library"] == "GO_Biological_Process_2021"

    def test_missing_genes_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/pathways", json={})
        assert resp.status_code == 422

    def test_empty_genes_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/pathways", json={"genes": []})
        assert resp.status_code == 422

    def test_invalid_symbol_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/pathways", json={"genes": ["TP53; DROP TABLE x"]})
        assert resp.status_code == 422

    def test_overlong_symbol_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/pathways", json={"genes": ["A" * 50]})
        assert resp.status_code == 422


class TestMapEnrichrRows:
    """Unit tests for the pure row-mapping/filtering function (no I/O)."""

    def test_filters_sorts_and_maps(self) -> None:
        # rows: [rank, term, pvalue, zscore, combined, genes[], adj_pvalue, ...]
        rows = [
            [1, "Term A", 1e-3, 2.0, 50.0, ["G1", "G2"], 0.01],
            [2, "Term B", 1e-2, 1.0, 300.0, ["G3"], 0.9],   # dropped: adj_p > 0.05
            [3, "Term C", 1e-4, 3.0, 120.0, ["G4"], 0.04],
        ]
        out = enrichment.map_enrichr_rows(rows)
        assert [r["term"] for r in out] == ["Term C", "Term A"]  # sorted by combined desc
        assert out[0]["combined_score"] == 120.0
        assert out[0]["overlap_genes"] == ["G4"]
        assert out[0]["adj_p_value"] == 0.04

    def test_boundary_adj_p_kept(self) -> None:
        rows = [[1, "Edge", 1e-3, 2.0, 10.0, ["G1"], 0.05]]
        out = enrichment.map_enrichr_rows(rows)
        assert len(out) == 1

    def test_caps_at_15(self) -> None:
        rows = [[i, f"T{i}", 1e-3, 1.0, float(i), ["G"], 0.01] for i in range(30)]
        out = enrichment.map_enrichr_rows(rows)
        assert len(out) == 15
        # highest combined_score first
        assert out[0]["combined_score"] == 29.0

    def test_malformed_rows_ignored(self) -> None:
        assert enrichment.map_enrichr_rows("not a list") == []
        assert enrichment.map_enrichr_rows([[1, "short"]]) == []


class TestEnrichPathways:
    def test_empty_input_short_circuits(self) -> None:
        assert enrichment.enrich_pathways([]) == []
        assert enrichment.enrich_pathways(["", "  "]) == []

    def test_full_flow_patched_httpx(self, monkeypatch: Any) -> None:
        """Patch httpx.Client so both Enrichr calls are canned (no network)."""

        class FakeResp:
            def __init__(self, payload: Any) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                return self._payload

        enrich_payload = {
            "Reactome_2022": [
                [1, "Autophagy", 1e-8, 4.0, 200.0, ["ATG5", "ATG7"], 1e-6],
                [2, "Noise", 1e-1, 0.5, 999.0, ["X"], 0.8],  # filtered out
            ]
        }

        class FakeClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def __enter__(self) -> "FakeClient":
                return self

            def __exit__(self, *a: Any) -> None:
                return None

            def post(self, url: str, **kwargs: Any) -> FakeResp:
                return FakeResp({"userListId": 42})

            def get(self, url: str, **kwargs: Any) -> FakeResp:
                return FakeResp(enrich_payload)

        monkeypatch.setattr(enrichment.httpx, "Client", FakeClient)
        out = enrichment.enrich_pathways(["ATG5", "ATG7"])
        assert len(out) == 1
        assert out[0]["term"] == "Autophagy"
        assert out[0]["overlap_genes"] == ["ATG5", "ATG7"]

    def test_network_error_fails_soft(self, monkeypatch: Any) -> None:
        class BoomClient:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def __enter__(self) -> "BoomClient":
                return self

            def __exit__(self, *a: Any) -> None:
                return None

            def post(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("network down")

            def get(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("network down")

        monkeypatch.setattr(enrichment.httpx, "Client", BoomClient)
        assert enrichment.enrich_pathways(["ATG5"]) == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
