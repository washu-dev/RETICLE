from fastapi.testclient import TestClient


class TestHealth:
    def test_health_check(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "reticle-api-server"
        assert "version" in data


class TestGreetings:
    def test_get_greetings(self, client: TestClient) -> None:
        response = client.get("/api/greetings")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Welcome to RETICLE"

    def test_greetings_response_model(self, client: TestClient) -> None:
        response = client.get("/api/greetings")
        assert response.status_code == 200
        assert "message" in response.json()


class TestLogin:
    def test_login_success(self, client: TestClient) -> None:
        payload = {"username": "testuser", "password": "testpass", "scopes": []}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert "testuser" in data["access_token"]

    def test_login_with_scopes(self, client: TestClient) -> None:
        payload = {"username": "user", "password": "pass", "scopes": ["read", "write"]}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "Bearer"

    def test_login_missing_username(self, client: TestClient) -> None:
        payload = {"username": "", "password": "testpass"}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_login_missing_password(self, client: TestClient) -> None:
        payload = {"username": "testuser", "password": ""}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_login_schema_validation(self, client: TestClient) -> None:
        payload = {"username": "testuser"}
        response = client.post("/api/login", json=payload)
        assert response.status_code == 422


class TestQuery:
    VALID_PAYLOAD = {
        "genes": [
            {"symbol": "TP53", "score": -1.2},
            {"symbol": "ATG5", "score": -0.8},
            {"symbol": "CCDC6", "score": -0.6},
        ],
        "options": {},
    }

    def test_query_returns_200(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        assert response.status_code == 200

    def test_query_response_shape(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        data = response.json()
        assert "matchedScreens" in data
        assert "darkGenes" in data
        assert "graphElements" in data
        assert "stats" in data

    def test_query_matched_screens_structure(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        screens = response.json()["matchedScreens"]
        assert len(screens) > 0
        first = screens[0]
        assert "biogridId" in first
        assert "name" in first
        assert "rho" in first
        assert "fdr" in first
        assert "sharedGenes" in first

    def test_query_dark_genes_structure(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        dark_genes = response.json()["darkGenes"]
        assert len(dark_genes) > 0
        first = dark_genes[0]
        assert "symbol" in first
        assert "darkScore" in first
        assert "correlation" in first
        assert "isBright" in first

    def test_query_graph_elements_structure(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        graph = response.json()["graphElements"]
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0

    def test_query_stats_present(self, client: TestClient) -> None:
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        stats = response.json()["stats"]
        assert "screensCompared" in stats
        assert "significantMatches" in stats
        assert "queryGeneCount" in stats

    def test_query_empty_genes(self, client: TestClient) -> None:
        response = client.post("/api/query", json={"genes": [], "options": {}})
        assert response.status_code == 200

    def test_query_missing_body_rejected(self, client: TestClient) -> None:
        response = client.post("/api/query", json={})
        assert response.status_code == 422

    def test_query_camel_case_fields(self, client: TestClient) -> None:
        """Verify API serializes as camelCase, not snake_case."""
        response = client.post("/api/query", json=self.VALID_PAYLOAD)
        data = response.json()
        assert "matched_screens" not in data
        assert "dark_genes" not in data
        assert "graph_elements" not in data


class TestExplorerGeneValidation:
    """Input validation for /api/gene — these short-circuit before any DB call,
    so they run in CI without a database."""

    def test_missing_symbol_rejected(self, client: TestClient) -> None:
        response = client.get("/api/gene")
        assert response.status_code == 422

    def test_empty_symbol_rejected(self, client: TestClient) -> None:
        response = client.get("/api/gene?symbol=")
        assert response.status_code == 422

    def test_injection_attempt_rejected(self, client: TestClient) -> None:
        response = client.get("/api/gene", params={"symbol": "TP53; DROP TABLE x"})
        assert response.status_code == 422

    def test_overlong_symbol_rejected(self, client: TestClient) -> None:
        response = client.get("/api/gene", params={"symbol": "A" * 50})
        assert response.status_code == 422


class TestGenes:
    def test_known_gene_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/genes/CCDC6")
        assert response.status_code == 200

    def test_known_gene_response_shape(self, client: TestClient) -> None:
        response = client.get("/api/genes/CCDC6")
        data = response.json()
        assert data["symbol"] == "CCDC6"
        assert "hypothesis" in data
        assert "mechanisticContext" in data
        assert "citations" in data
        assert "suggestedValidation" in data
        assert "darkScore" in data

    def test_known_gene_citations(self, client: TestClient) -> None:
        response = client.get("/api/genes/CCDC6")
        citations = response.json()["citations"]
        assert isinstance(citations, list)
        assert len(citations) > 0
        assert "pmid" in citations[0]
        assert "text" in citations[0]

    def test_known_gene_string_interactors(self, client: TestClient) -> None:
        response = client.get("/api/genes/CCDC6")
        interactors = response.json()["stringInteractors"]
        assert isinstance(interactors, list)
        assert len(interactors) > 0
        assert "symbol" in interactors[0]
        assert "combinedScore" in interactors[0]

    def test_second_rationale_gene(self, client: TestClient) -> None:
        response = client.get("/api/genes/FAM114A1")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "FAM114A1"
        assert data["hypothesis"]

    def test_gene_in_mock_set_no_rationale(self, client: TestClient) -> None:
        """Gene exists in dark set but has no curated rationale — still returns 200."""
        response = client.get("/api/genes/ULK1")
        assert response.status_code == 200
        assert response.json()["symbol"] == "ULK1"

    def test_gene_symbol_case_insensitive(self, client: TestClient) -> None:
        upper = client.get("/api/genes/CCDC6").json()
        lower = client.get("/api/genes/ccdc6").json()
        assert upper["symbol"] == lower["symbol"]

    def test_unknown_gene_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/genes/NOTAREALGENE")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_gene_camel_case_fields(self, client: TestClient) -> None:
        """Verify camelCase serialization on gene detail."""
        response = client.get("/api/genes/CCDC6")
        data = response.json()
        assert "mechanistic_context" not in data
        assert "dark_score" not in data
        assert "string_interactors" not in data
