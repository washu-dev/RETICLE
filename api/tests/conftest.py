import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Provide TestClient for all tests."""
    return TestClient(app)
