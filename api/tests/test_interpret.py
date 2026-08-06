"""
Tests for the AI narrative endpoints (POST /api/interpret, GET
/api/reporter_explain) and the interpret service.

These run fully offline: the WashULLMClient.chat method is patched so no token
exchange or network call ever happens. We mount the interpret router on a
throwaway FastAPI app so the tests don't depend on main.py registration.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import interpret as interpret_router
from routers.interpret import router
from services import interpret as interpret_service
from services.llm_client import (
    LlmUnavailable as LegacyLlmUnavailable,
)
from services.llm_client import (
    WashULLMClient,
    _is_reasoning_model,
)
from services.llm_client_aaron import LLMUnavailable

CANNED = (
    "This gene shows a coherent cross-screen fitness footprint suggesting a role "
    "in autophagic flux (PMID 31097699). A bench biologist could follow up with "
    "CRISPRi depletion and LC3-II western blots."
)

FOOTPRINT = {
    "symbol": "CCDC6",
    "organism": "Homo sapiens",
    "n_total": 8,
    "fitness": {"mean_score": -0.6, "n_hits": 4},
    "stress": {"contexts": "IFNg,LPS"},
    "reporter": {},
}


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# --------------------------------------------------------------------------
# POST /api/interpret
# --------------------------------------------------------------------------

class TestInterpretEndpoint:
    def test_returns_200_with_contract_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_interpret(_payload: dict[str, Any]) -> dict[str, Any]:
            return {"model": "claude-opus-4-7", "text": CANNED, "sources": []}

        monkeypatch.setattr(interpret_router, "get_interpret", fake_interpret)
        resp = client.post("/api/interpret", json=FOOTPRINT)
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"model", "text", "sources"}
        assert data["text"] == CANNED
        assert data["model"] == "claude-opus-4-7"
        assert data["sources"] == []

    def test_sparse_payload_still_ok(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_interpret(payload: dict[str, Any]) -> dict[str, Any]:
            captured.update(payload)
            return {"model": "claude-opus-4-7", "text": CANNED, "sources": []}

        monkeypatch.setattr(interpret_router, "get_interpret", fake_interpret)
        resp = client.post("/api/interpret", json={"symbol": "ATG5"})
        assert resp.status_code == 200
        assert resp.json()["text"] == CANNED
        assert captured["organism"] == "Homo sapiens"
        assert captured["reporter"] == {"n": 0, "ledger": []}

    def test_llm_unavailable_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unavailable(_payload: dict[str, Any]) -> dict[str, Any]:
            raise LLMUnavailable("not configured")

        monkeypatch.setattr(interpret_router, "get_interpret", unavailable)
        resp = client.post("/api/interpret", json=FOOTPRINT)
        assert resp.status_code == 503
        assert "error" in resp.json()

    def test_missing_symbol_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/interpret", json={})
        assert resp.status_code == 422


# --------------------------------------------------------------------------
# GET /api/reporter_explain
# --------------------------------------------------------------------------

class TestReporterExplainEndpoint:
    def test_returns_200_with_contract_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_explain(_symbol: str, _screens: list[str]) -> dict[str, Any]:
            return {"text": CANNED, "process": "autophagy", "darkness": None, "sources": []}

        monkeypatch.setattr(interpret_router, "get_reporter_explain", fake_explain)
        resp = client.get(
            "/api/reporter_explain", params={"symbol": "CCDC6", "screens": "1,2"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"text", "process", "darkness", "sources"}
        assert data["text"] == CANNED
        assert isinstance(data["process"], str)
        assert data["darkness"] is None
        assert data["sources"] == []

    def test_llm_unavailable_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def unavailable(_symbol: str, _screens: list[str]) -> dict[str, Any]:
            raise LLMUnavailable("down")

        monkeypatch.setattr(interpret_router, "get_reporter_explain", unavailable)
        resp = client.get(
            "/api/reporter_explain", params={"symbol": "CCDC6", "screens": "1"}
        )
        assert resp.status_code == 503
        assert "error" in resp.json()

    def test_invalid_symbol_rejected(self, client: TestClient) -> None:
        resp = client.get(
            "/api/reporter_explain", params={"symbol": "TP53; DROP TABLE x"}
        )
        assert resp.status_code == 422

    def test_screens_capped_to_six(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[str] = []

        async def fake_explain(_symbol: str, screens: list[str]) -> dict[str, Any]:
            captured.extend(screens)
            return {"text": CANNED, "process": "autophagy", "darkness": None, "sources": []}

        monkeypatch.setattr(interpret_router, "get_reporter_explain", fake_explain)
        many = ",".join(str(i) for i in range(10))
        resp = client.get(
            "/api/reporter_explain", params={"symbol": "CCDC6", "screens": many}
        )
        assert resp.status_code == 200
        assert captured == ["0", "1", "2", "3", "4", "5"]

    def test_missing_screens_is_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/reporter_explain", params={"symbol": "CCDC6"})
        assert resp.status_code == 422


# --------------------------------------------------------------------------
# Pure helpers (no network)
# --------------------------------------------------------------------------

class TestPureHelpers:
    def test_build_footprint_messages_shape(self) -> None:
        msgs = interpret_service.build_footprint_messages(FOOTPRINT)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "CCDC6" in msgs[1]["content"]
        assert "140-200" in msgs[1]["content"]

    def test_build_footprint_messages_handles_empty(self) -> None:
        msgs = interpret_service.build_footprint_messages({})
        assert len(msgs) == 2
        assert "the query gene" in msgs[1]["content"]

    def test_build_reporter_messages_lists_screens(self) -> None:
        msgs = interpret_service.build_reporter_messages("ATG5", ["s1", "s2"])
        assert "ATG5" in msgs[1]["content"]
        assert "s1" in msgs[1]["content"]

    def test_reasoning_model_detection(self) -> None:
        assert _is_reasoning_model("gpt-5")
        assert _is_reasoning_model("o3-mini")
        assert not _is_reasoning_model("gpt-4.1")


# --------------------------------------------------------------------------
# Client fail-soft behavior (no network)
# --------------------------------------------------------------------------

class TestClientFailSoft:
    def test_unconfigured_client_raises_llm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure no credentials are visible so the client is "unconfigured".
        for var in (
            "WASHU_TOKEN_URL", "SECURE_API_CLIENT_ID", "WASHU_CLIENT_ID",
            "SECURE_API_CLIENT_SECRET", "WASHU_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)
        c = WashULLMClient()
        with pytest.raises(LegacyLlmUnavailable):
            c.chat([{"role": "user", "content": "hi"}])
