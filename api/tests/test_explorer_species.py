import asyncio

import pytest
from fastapi.testclient import TestClient

from routers import explorer
from services import explorer_gene, explorer_network


def test_gene_route_forwards_canonical_mouse_organism(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, str | None] = {}

    async def fake_payload(symbol: str, org: str | None = None) -> dict:
        called.update(symbol=symbol, org=org)
        return {"symbol": symbol, "organism": org}

    monkeypatch.setattr(explorer, "get_gene_payload", fake_payload)

    response = client.get("/api/gene", params={"symbol": "Trp53", "org": "mouse"})

    assert response.status_code == 200
    assert called == {"symbol": "Trp53", "org": "Mus musculus"}
    assert response.json()["organism"] == "Mus musculus"


def test_gene_route_keeps_legacy_auto_detection_when_org_is_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, str | None] = {}

    async def fake_payload(symbol: str, org: str | None = None) -> dict:
        called.update(symbol=symbol, org=org)
        return {"symbol": symbol, "organism": "Homo sapiens"}

    monkeypatch.setattr(explorer, "get_gene_payload", fake_payload)

    response = client.get("/api/gene", params={"symbol": "TP53"})

    assert response.status_code == 200
    assert called == {"symbol": "TP53", "org": None}


def test_gene_route_rejects_unknown_organism(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def should_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("service should not run for an invalid organism")

    monkeypatch.setattr(explorer, "get_gene_payload", should_not_run)

    response = client.get("/api/gene", params={"symbol": "TP53", "org": "rat"})

    assert response.status_code == 422
    assert "Unknown organism" in response.json()["detail"]


def test_gene_service_filters_rows_by_requested_organism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetchall(sql: str, params: tuple) -> list:
        captured.update(sql=sql, params=params)
        return []

    monkeypatch.setattr(explorer_gene, "USE_PG", True)
    monkeypatch.setattr(explorer_gene, "db_fetchall", fake_fetchall)

    result = asyncio.run(explorer_gene.get_gene_payload("Trp53", "Mus musculus"))

    assert result is None
    assert "m.ORGANISM_OFFICIAL = ?" in str(captured["sql"])
    assert captured["params"] == ("Trp53", "TRP53", "trp53", "Mus musculus")


def test_network_service_uses_species_for_string_and_fitness_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_string_network(symbol: str, taxid: int) -> dict:
        captured.update(symbol=symbol, taxid=taxid)
        return {"nodes": ["Trp53", "Mdm2"], "edges": []}

    def fake_fetchall(sql: str, params: tuple) -> list:
        captured.update(sql=sql, params=params)
        return []

    monkeypatch.setattr(explorer_network.ex, "string_network", fake_string_network)
    monkeypatch.setattr(explorer_network, "db_fetchall", fake_fetchall)

    result = asyncio.run(explorer_network.get_network("Trp53", "Mus musculus"))

    assert result["focus"] == "Trp53"
    assert captured["taxid"] == 10090
    assert "sm.ORGANISM_OFFICIAL = ?" in str(captured["sql"])
    assert captured["params"] == ("Trp53", "Mdm2", "Mus musculus")


def test_network_route_normalises_taxid_alias(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, str] = {}

    async def fake_network(symbol: str, org: str) -> dict:
        called.update(symbol=symbol, org=org)
        return {"focus": symbol, "nodes": [], "edges": []}

    monkeypatch.setattr(explorer, "get_network", fake_network)

    response = client.get("/api/network", params={"symbol": "Trp53", "org": "10090"})

    assert response.status_code == 200
    assert called == {"symbol": "Trp53", "org": "Mus musculus"}
