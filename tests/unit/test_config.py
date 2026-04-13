import types

try:
    import src.config as config
except Exception:
    import config


class _FakeCursor:
    def execute(self, q):
        pass

    def fetchone(self):
        return ("PostgreSQL 16.13",)


class _CursorCtx:
    def __enter__(self):
        return _FakeCursor()

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def cursor(self):
        return _CursorCtx()

    def close(self):
        pass


def test_get_parameter(monkeypatch):
    class FakeSSM:
        def get_parameter(self, Name, WithDecryption=True):
            return {"Parameter": {"Value": "value-for-" + Name}}

    monkeypatch.setattr(
        config, "boto3", types.SimpleNamespace(client=lambda *a, **k: FakeSSM())
    )

    val = config.get_parameter("/kognit/db/POSTGRES_HOST")
    assert "value-for-" in val


def test_check_postgres_success(monkeypatch):
    # set required globals on the module (tests run outside AWS lambda)
    config.DB_HOST = "localhost"
    config.DB_PORT = "5432"
    config.DB_NAME = "testdb"
    config.DB_USER = "user"
    config.DB_PASS = "pass"

    monkeypatch.setattr(
        config, "psycopg", types.SimpleNamespace(connect=lambda **k: _FakeConn())
    )

    res = config.check_postgres()
    assert res["status"] == "ok"
    assert "postgres_version" in res


def test_check_postgres_failure(monkeypatch):
    # simulate connection error
    monkeypatch.setattr(
        config,
        "psycopg",
        types.SimpleNamespace(
            connect=lambda **k: (_ for _ in ()).throw(Exception("conn failed"))
        ),
    )

    res = config.check_postgres()
    assert res["status"] == "error"
    assert "conn failed" in res["detail"]
