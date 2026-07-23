import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Tests run offline: never reach out to AWS Secrets Manager on import.
os.environ.setdefault("RETICLE_SKIP_AWS_SECRETS", "1")

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Provide TestClient for all tests."""
    return TestClient(app)
