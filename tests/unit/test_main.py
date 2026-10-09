"""Smoke tests for the assembled app: service identity and health routes.

The placeholder ``GET /items/{item_id}`` route was removed with M-2; ``GET /`` is
now the service-identity route and ``GET /health`` reports per-dependency status.
"""

from fastapi.testclient import TestClient

try:
    import src.main as main_mod
except Exception:
    import main as main_mod

app = main_mod.app
client = TestClient(app)


def test_service_identity_root():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "kognit-ai-hse-llm-api"
    assert "service_version" in body
    assert body["environment"] in {"local", "dev", "staging", "prod"}


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    # R1.19: a warehouse status value and a model-provider status value.
    assert "warehouse" in body
    assert "model_provider" in body
    assert body["overall"] in {"ok", "failed", "unknown"}


def test_items_route_removed():
    response = client.get("/items/42")
    assert response.status_code == 404
