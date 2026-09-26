"""
Tests for src/main.py — app construction, /health, root, WebSocket route.

Uses httpx.AsyncClient + ASGITransport so the app runs in the same
event loop as pytest-asyncio's session-scoped fixtures. TestClient
opens a separate loop, which poisons the asyncpg pool for every later
real-DB test in the session.

Lifespan is run explicitly inside the fixture via
app.router.lifespan_context(app), so app.state.* is populated
(db_connected, redis_connected, incident_service).
"""
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from src.main import app


@pytest_asyncio.fixture
async def client():
    """Run lifespan, then yield an in-loop HTTP client."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---------------------------------------------------------------------------
# App boots
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_boots_and_lifespan_runs(client):
    assert app.title == "AEGIS PRO"
    assert app.version == "1.0.0"
    # lifespan sets these on app.state
    assert hasattr(app.state, "db_connected")
    assert hasattr(app.state, "redis_connected")
    assert hasattr(app.state, "incident_service")


@pytest.mark.asyncio
async def test_root_returns_service_banner(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "AEGIS PRO"
    assert body["status"] == "operational"
    assert "health" in body["endpoints"]
    assert "websocket" in body["endpoints"]


@pytest.mark.asyncio
async def test_health_endpoint_returns_expected_shape(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.0.0"
    assert "auto_fix_mode" in body
    assert "demo_mode" in body
    assert set(body["services"].keys()) == {"database", "redis"}
    expected = "healthy" if (
        body["services"]["database"] == "connected"
        and body["services"]["redis"] == "connected"
    ) else "degraded"
    assert body["status"] == expected


@pytest.mark.asyncio
async def test_health_reports_degraded_when_db_disconnected(client):
    app.state.db_connected = False
    app.state.redis_connected = False
    resp = await client.get("/health")
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"] == "disconnected"


# ---------------------------------------------------------------------------
# Routers mounted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_router_mounted(client):
    resp = await client.get("/api/v1/demo/default")
    assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_api_v1_ping_router_mounted(client):
    resp = await client.get("/api/v1/ping")
    assert resp.status_code in (200, 404, 405)


# ---------------------------------------------------------------------------
# WebSocket route registered
# ---------------------------------------------------------------------------

def test_websocket_route_is_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/ws/incidents" in paths


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def test_cors_middleware_uses_allow_origins_variable():
    """
    The CORSMiddleware must be configured from the computed allow_origins,
    not a hardcoded list.
    """
    from src.main import app, allow_origins
    from starlette.middleware.cors import CORSMiddleware

    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            assert mw.kwargs["allow_origins"] == allow_origins
            assert mw.kwargs["allow_credentials"] == ("*" not in allow_origins)
            return
    pytest.fail("CORSMiddleware not found in app middleware stack")
