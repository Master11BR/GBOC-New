import os
import sys
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from agent_gboc import app
except ImportError:
    from agent_server import app

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code in (200, 302)
    # Auth middleware pode redirecionar para login dependendo da sessão
