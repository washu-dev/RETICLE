import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=app)


class TestHealth:
    def test_health_check(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "wcs-api-server"
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
