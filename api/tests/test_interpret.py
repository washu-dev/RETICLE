"""
Tests for the AI narrative endpoints (POST /api/interpret, GET
/api/reporter_explain) and the interpret service.

These run fully offline: the WashULLMClient.chat method is patched so no token
exchange or network call ever happens. We mount the interpret router on a
throwaway FastAPI app so the tests don't depend on main.py registration.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.interpret import router
from services import interpret as interpret_service
from services.llm_client import LlmUnavailable, WashULLMClient, _is_reasoning_model

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
    def test_returns_200_with_contract_shape(self, client: TestClient) -> None:
        with patch.object(interpret_service.client, "chat", return_value=CANNED):
            resp = client.post("/api/interpret", json=FOOTPRINT)
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"model", "text", "sources"}
        assert data["text"] == CANNED
        assert data["model"] == interpret_service.client.model
        assert data["sources"] == []

    def test_sparse_payload_still_ok(self, client: TestClient) -> None:
        with patch.object(interpret_service.client, "chat", return_value=CANNED):
            resp = client.post("/api/interpret", json={"symbol": "ATG5"})
        assert resp.status_code == 200
        assert resp.json()["text"] == CANNED

    def test_llm_unavailable_returns_503(self, client: TestClient) -> None:
        with patch.object(
            interpret_service.client, "chat",
            side_effect=LlmUnavailable("not configured"),
        ):
            resp = client.post("/api/interpret", json=FOOTPRINT)
        assert resp.status_code == 503
        assert "error" in resp.json()


# --------------------------------------------------------------------------
# GET /api/reporter_explain
# --------------------------------------------------------------------------

class TestReporterExplainEndpoint:
    def test_returns_200_with_contract_shape(self, client: TestClient) -> None:
        with patch.object(interpret_service.client, "chat", return_value=CANNED):
            resp = client.get(
                "/api/reporter_explain", params={"symbol": "CCDC6", "screens": "s1,s2"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"text", "process", "darkness", "sources"}
        assert data["text"] == CANNED
        assert isinstance(data["process"], str)
        assert data["darkness"] is None
        assert data["sources"] == []

    def test_llm_unavailable_returns_503(self, client: TestClient) -> None:
        with patch.object(
            interpret_service.client, "chat", side_effect=LlmUnavailable("down")
        ):
            resp = client.get("/api/reporter_explain", params={"symbol": "CCDC6"})
        assert resp.status_code == 503
        assert "error" in resp.json()

    def test_invalid_symbol_rejected(self, client: TestClient) -> None:
        resp = client.get(
            "/api/reporter_explain", params={"symbol": "TP53; DROP TABLE x"}
        )
        assert resp.status_code == 422

    def test_screens_capped_to_six(self, client: TestClient) -> None:
        captured = {}

        def fake_chat(messages: object, **kw: object) -> str:
            captured["messages"] = messages
            return CANNED

        many = ",".join(f"s{i}" for i in range(10))
        with patch.object(interpret_service.client, "chat", side_effect=fake_chat):
            resp = client.get(
                "/api/reporter_explain", params={"symbol": "CCDC6", "screens": many}
            )
        assert resp.status_code == 200
        user_msg = captured["messages"][-1]["content"]
        # s0..s5 present, s6+ dropped by the 6-screen cap.
        assert "s5" in user_msg
        assert "s6" not in user_msg


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
        with pytest.raises(LlmUnavailable):
            c.chat([{"role": "user", "content": "hi"}])
