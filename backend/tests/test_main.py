import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SNAPSHOT = {
    "row_count": 42,
    "created_at_range": ["2024-05-11 14:49", "2026-10-28 01:56"],
    "source_url": "https://example.test/d/abc",
}


@pytest.fixture
def client(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAPSHOT))
    settings = Settings(
        snapshot_path=snap,
        db_path=tmp_path / "missing.duckdb",
        allowed_origins=["https://app.example.test"],
    )
    return TestClient(create_app(settings))


def test_health_without_db(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_meta(client):
    r = client.get("/meta")
    assert r.status_code == 200
    assert r.json() == {
        "as_of": "2026-10-28",
        "row_count": 42,
        "created_at_range": SNAPSHOT["created_at_range"],
        "source_url": SNAPSHOT["source_url"],
    }


def test_meta_missing_snapshot(tmp_path):
    c = TestClient(create_app(Settings(snapshot_path=tmp_path / "nope.json")))
    r = c.get("/meta")
    assert r.status_code == 503 and r.json()["error"] == "meta_unavailable"


def _preflight(client, origin):
    return client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_cors_allowed_origin(client):
    r = _preflight(client, "https://app.example.test")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://app.example.test"


def test_cors_disallowed_origin(client):
    r = _preflight(client, "https://evil.example.test")
    assert "access-control-allow-origin" not in r.headers


def test_create_app_without_files(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "no.duckdb"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    s = Settings.from_env()
    assert s.anthropic_api_key is None and s.allowed_origins == []
    create_app()
