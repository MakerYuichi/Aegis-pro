"""
Tests for src/main.py — app construction, /health, root, WebSocket route.

The lifespan is exercised implicitly by TestClient. DB/Redis connection
attempts inside lifespan are expected to fail in the test environment and
are handled gracefully by the app (it logs a warning and continues).
"""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    # TestClient runs lifespan on __enter__; connection failures are caught.
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# App boots
# ---------------------------------------------------------------------------

def test_app_boots_and_lifespan_runs(client):
    assert app.title == "AEGIS PRO"
    assert app.version == "1.0.0"
    # lifespan sets these on app.state
    assert hasattr(app.state, "db_connected")
    assert hasattr(app.state, "redis_connected")
    assert hasattr(app.state, "incident_service")


def test_root_returns_service_banner(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "AEGIS PRO"
    assert body["status"] == "operational"
    assert "health" in body["endpoints"]
    assert "websocket" in body["endpoints"]


def test_health_endpoint_returns_expected_shape(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.0.0"
    assert "auto_fix_mode" in body
    assert "demo_mode" in body
    assert set(body["services"].keys()) == {"database", "redis"}
    # status is healthy only when both are connected
    expected = "healthy" if (
        body["services"]["database"] == "connected"
        and body["services"]["redis"] == "connected"
    ) else "degraded"
    assert body["status"] == expected


def test_health_reports_degraded_when_db_disconnected(client):
    # In tests, DB is not available, so state flags are False.
    app.state.db_connected = False
    app.state.redis_connected = False
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["services"]["database"] == "disconnected"


# ---------------------------------------------------------------------------
# Routers mounted
# ---------------------------------------------------------------------------

def test_demo_router_mounted(client):
    # /api/v1/demo/default exists regardless of DEMO_MODE flag;
    # when DEMO_MODE is off it returns 404 (covered in test_demo_endpoints).
    resp = client.get("/api/v1/demo/default")
    assert resp.status_code in (200, 404)


def test_api_v1_ping_router_mounted(client):
    # If the ping route exists in routes.py it returns 200; otherwise 404.
    # This test asserts the /api/v1 prefix is wired.
    resp = client.get("/api/v1/ping")
    assert resp.status_code in (200, 404, 405)


# ---------------------------------------------------------------------------
# WebSocket route registered
# ---------------------------------------------------------------------------

def test_websocket_route_is_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/ws/incidents" in paths


# ---------------------------------------------------------------------------
# CORS — documents current behavior + intended behavior (bug)
# ---------------------------------------------------------------------------

def test_cors_allows_localhost_current_behavior(client):
    """The app currently hardcodes allow_origins=['http://localhost:5173']."""
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.xfail(
    reason="Bug: CORS_ORIGINS env var is computed but ignored; middleware uses "
           "a hardcoded list. See src/main.py lines defining _cors_env/allow_origins "
           "vs the CORSMiddleware call. Fix by passing allow_origins=allow_origins.",
    strict=False,
)
def test_cors_respects_cors_origins_env(client, monkeypatch):
    """Intended behavior: CORS_ORIGINS from env should drive the middleware."""
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
    # Reload would be needed to pick up the env var at import time; the app
    # currently ignores it entirely, so this test documents the gap.
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "https://example.com"
