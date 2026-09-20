import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import settings
from src.demo.endpoints import router as demo_router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(demo_router)
    return app


@pytest.fixture
def client_demo_on(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    return TestClient(_make_app())


@pytest.fixture
def client_demo_off(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    return TestClient(_make_app())


# ── DEMO_MODE=false → 404 on every route ────────────────────────────────

def test_default_404_when_demo_off(client_demo_off):
    assert client_demo_off.get("/api/v1/demo/default").status_code == 404


def test_generate_404_when_demo_off(client_demo_off):
    r = client_demo_off.post("/api/v1/demo/generate", json={"repo_url": "github.com/a/b"})
    assert r.status_code == 404


def test_reset_404_when_demo_off(client_demo_off):
    assert client_demo_off.post("/api/v1/demo/reset").status_code == 404


# ── DEMO_MODE=true → working routes ─────────────────────────────────────

def test_default_returns_aegis_incident(client_demo_on):
    r = client_demo_on.get("/api/v1/demo/default")
    assert r.status_code == 200
    data = r.json()
    assert data["incident_id"] == "INC-DEMO-AEGIS-0001"
    assert data["extra_metadata"]["demo_default"] is True
    assert data["extra_metadata"]["simulated"] is True


def test_generate_valid_url_returns_incident_and_parsed(client_demo_on):
    r = client_demo_on.post(
        "/api/v1/demo/generate", json={"repo_url": "github.com/uber/ride-dispatch"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "incident" in body
    assert "parsed" in body
    assert body["parsed"]["org"] == "uber"
    assert body["parsed"]["repo"] == "ride-dispatch"
    assert body["incident"]["service_name"] == "ride-dispatch"


def test_generate_empty_url_returns_error_payload(client_demo_on):
    r = client_demo_on.post("/api/v1/demo/generate", json={"repo_url": ""})
    assert r.status_code == 200
    body = r.json()
    assert "error" in body
    assert body["reason"] == "empty"
    assert "supported_shapes" in body
    assert len(body["supported_shapes"]) == 7


def test_generate_malformed_url_returns_error_payload(client_demo_on):
    r = client_demo_on.post(
        "/api/v1/demo/generate", json={"repo_url": "gitea.com/org/repo"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reason"] == "unsupported_host"


def test_reset_clears_session(client_demo_on):
    r = client_demo_on.post("/api/v1/demo/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "reset"
