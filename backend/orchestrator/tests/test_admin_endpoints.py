"""
Tests for /api/v1/admin/* endpoints.

Real-DB tests. Uses httpx.AsyncClient with ASGITransport so the app runs
in the same event loop as the pytest-asyncio fixtures (TestClient runs the
app in a separate loop, which breaks engine session sharing).

Auth is overridden via app.dependency_overrides[require_admin].
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
import httpx
from httpx import ASGITransport

from src.main import app


@pytest_asyncio.fixture
async def admin_client(monkeypatch):
    """
    Async HTTP client that runs the ASGI app in this test's event loop.

    Does NOT run the app's lifespan — init_db and backfill are not needed
    for the admin endpoints (they operate on tables that already exist
    and are populated by migrations).
    """
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "admin@x.com")
    from src.auth import require_admin
    app.dependency_overrides[require_admin] = lambda: {"email": "admin@x.com"}

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client():
    """Async client with no admin override — for the 401 test."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── /admin/me ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_me_returns_is_admin(admin_client):
    resp = await admin_client.get("/api/v1/admin/me")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True
    assert resp.json()["email"] == "admin@x.com"


@pytest.mark.asyncio
async def test_admin_me_401_for_non_admin(anon_client):
    """No dependency override → real require_admin → 401 (no token)."""
    resp = await anon_client.get("/api/v1/admin/me")
    assert resp.status_code == 401


# ── /admin/demo-sessions (list) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_demo_sessions_returns_all_seeded(
    admin_client, seeded_demo_sessions, db_session
):
    # The admin endpoint queries the whole table. Committed rows from
    # manual browser testing are visible outside the test transaction,
    # so we delete them here — inside the transaction — to assert on
    # an exact count. Rolled back at teardown.
    await db_session.execute(
        text("DELETE FROM demo_sessions WHERE session_id NOT LIKE 'sess-%'")
    )
    await db_session.flush()

    resp = await admin_client.get("/api/v1/admin/demo-sessions?limit=50")
    assert resp.status_code == 200
    body = resp.json()

    assert body["count"] == 5
    assert body["limit"] == 50

    ids = [s["session_id"] for s in body["sessions"]]
    assert ids == ["sess-e", "sess-d", "sess-c", "sess-b", "sess-a"]


@pytest.mark.asyncio
async def test_list_demo_sessions_shapes_row(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-sessions?limit=10")
    s = next(
        s for s in resp.json()["sessions"] if s["session_id"] == "sess-a"
    )
    assert s["parsed_org"] == "stripe"
    assert s["parsed_repo"] == "connect"
    assert s["language_inferred"] == "Java"
    assert s["parse_ok"] is True
    assert s["error_reason"] is None
    assert s["incident_id"] == "INC-DEMO-1"
    assert s["created_at"] is not None
    assert s["last_seen_at"] is not None


@pytest.mark.asyncio
async def test_list_demo_sessions_clamps_limit(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-sessions?limit=9999")
    assert resp.json()["limit"] == 500


@pytest.mark.asyncio
async def test_list_demo_sessions_clamps_limit_floor(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-sessions?limit=0")
    assert resp.json()["limit"] == 1


@pytest.mark.asyncio
async def test_list_demo_sessions_empty(admin_client, db_session):
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM demo_sessions"))
    await db_session.flush()
    resp = await admin_client.get("/api/v1/admin/demo-sessions")
    body = resp.json()
    assert body["sessions"] == []
    assert body["count"] == 0


# ── /admin/demo-stats (aggregates) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_stats_shapes_aggregates(
    admin_client, seeded_demo_sessions, db_session
):
    # Same isolation as above.
    await db_session.execute(
        text("DELETE FROM demo_sessions WHERE session_id NOT LIKE 'sess-%'")
    )
    await db_session.flush()

    resp = await admin_client.get("/api/v1/admin/demo-stats?days=365")
    assert resp.status_code == 200
    body = resp.json()

    assert body["window_days"] == 365
    assert body["total_sessions"] == 5

    by_day = {row["date"]: row["count"] for row in body["sessions_by_day"]}
    assert by_day == {"2026-09-24": 1, "2026-09-23": 1, "2026-09-22": 3}

    top = {row["org"]: row["count"] for row in body["top_orgs"]}
    assert top == {"stripe": 2, "airbnb": 1}

    assert body["parse_failures"]["total"] == 2
    reasons = {
        row["reason"]: row["count"]
        for row in body["parse_failures"]["by_reason"]
    }
    assert reasons == {"unsupported_host": 1, "malformed": 1}


@pytest.mark.asyncio
async def test_demo_stats_empty_database(admin_client, db_session):
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM demo_sessions"))
    await db_session.flush()
    resp = await admin_client.get("/api/v1/admin/demo-stats")
    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["sessions_by_day"] == []
    assert body["top_orgs"] == []
    assert body["parse_failures"]["total"] == 0
    assert body["parse_failures"]["by_reason"] == []


@pytest.mark.asyncio
async def test_demo_stats_clamps_days_upper(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-stats?days=9999")
    assert resp.json()["window_days"] == 365


@pytest.mark.asyncio
async def test_demo_stats_clamps_days_lower(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-stats?days=0")
    assert resp.json()["window_days"] == 1


# ── /admin/demo-sessions/{id} (replay) ─────────────────────────────────

@pytest.mark.asyncio
async def test_demo_session_detail_returns_call(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-sessions/sess-a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-a"
    assert body["call_count"] == 1
    call = body["calls"][0]
    assert call["raw_input"] == "https://github.com/stripe/connect"
    assert call["parsed_org"] == "stripe"
    assert call["parse_ok"] is True
    assert call["incident_payload"] == {"incident_id": "INC-DEMO-1", "title": "t1"}


@pytest.mark.asyncio
async def test_demo_session_detail_404_when_missing(admin_client, seeded_demo_sessions):
    resp = await admin_client.get("/api/v1/admin/demo-sessions/does-not-exist")
    assert resp.status_code == 404
