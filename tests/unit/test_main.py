from fastapi.testclient import TestClient

# Import the app module in a way that works both when tests are run with
# `PYTHONPATH=src` (local dev) and in CI where modules are packaged under src.
try:
    import src.main as main_mod
except Exception:
    import main as main_mod


app = main_mod.app
client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"Hello": "LLM API from GitHub Actions!"}


def test_read_item():
    response = client.get("/items/42?q=test")
    assert response.status_code == 200
    assert response.json() == {"item_id": 42, "q": "test"}

    response = client.get("/items/7")
    assert response.status_code == 200
    assert response.json() == {"item_id": 7, "q": None}


def test_health_endpoint(monkeypatch):
    """Mock `check_postgres` so health endpoint can be exercised without real DB."""
    mocked = {"status": "ok", "postgres_version": "PostgreSQL 16.13"}

    # Try to patch both possible config module locations depending on how main was
    #  imported
    try:
        import src.config as src_config

        monkeypatch.setattr(src_config, "check_postgres", lambda: mocked)
    except Exception:
        pass

    try:
        import config as root_config

        monkeypatch.setattr(root_config, "check_postgres", lambda: mocked)
    except Exception:
        pass

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["postgres"]["status"] == "ok"
    assert body["postgres"]["postgres_version"] == "PostgreSQL 16.13"
    assert body["overall"]["status"] == "ok"
