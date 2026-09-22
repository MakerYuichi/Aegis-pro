"""Tests for /api/v1/admin/* endpoints."""
from datetime import datetime, timezone, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


def _mock_db(sequence=None):
    """
    Build a get_db replacement that returns responses in a fixed order.

    `sequence` is an ordered list of items, one per execute() call the
    endpoint under test makes:

      - a list  → this call returns fetchall() with that list
      - a scalar → this call returns scalar() with that value

    The endpoint runs its queries in a deterministic order (see src/api/admin.py).
    The test must provide items in that same order.
    """
    queue = list(sequence or [])

    session = MagicMock()

    async def _execute(*args, **kwargs):
        if not queue:
            raise AssertionError(
                "session.execute called more times than the test provided "
                "responses for (queue exhausted)"
            )
        item = queue.pop(0)
        m = MagicMock()
        if isinstance(item, list):
            m.fetchall.return_value = item
        else:
            m.scalar.return_value = item
        return m

    session.execute = AsyncMock(side_effect=_execute)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return session

    return _get_db, session


@pytest.fixture
def admin_client(monkeypatch):
    """A TestClient where require_admin always passes."""
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "admin@x.com")
    from src.auth import require_admin
    app.dependency_overrides[require_admin] = lambda: {"email": "admin@x.com"}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── /admin/me ──────────────────────────────────────────────────────────

def test_admin_me_returns_is_admin(admin_client):
    resp = admin_client.get("/api/v1/admin/me")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


def test_admin_me_403_for_non_admin():
    with TestClient(app) as c:
        resp = c.get("/api/v1/admin/me")
    assert resp.status_code == 401


# ── /admin/demo-sessions ───────────────────────────────────────────────

def test_list_demo_sessions_shapes_rows(admin_client):
    ts = datetime(2026, 9, 23, 14, 22, tzinfo=timezone.utc)
    rows = [
        (1, "sess-abc", "https://github.com/stripe/connect", "stripe",
         "connect", "Java", True, None, "INC-DEMO-1", ts, ts),
    ]
    get_db, _ = _mock_db(sequence=[rows])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-sessions?limit=10")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["limit"] == 10
    s = body["sessions"][0]
    assert s["session_id"] == "sess-abc"
    assert s["parsed_org"] == "stripe"
    assert s["parse_ok"] is True
    assert s["error_reason"] is None


def test_list_demo_sessions_clamps_limit(admin_client):
    get_db, _ = _mock_db(sequence=[[]])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-sessions?limit=9999")
    assert resp.json()["limit"] == 500


def test_list_demo_sessions_empty(admin_client):
    get_db, _ = _mock_db(sequence=[[]])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-sessions")
    body = resp.json()
    assert body["sessions"] == []
    assert body["count"] == 0


# ── /admin/demo-stats ──────────────────────────────────────────────────

def test_demo_stats_shapes_aggregates(admin_client):
    total = 42
    by_day = [(date(2026, 9, 22), 10), (date(2026, 9, 23), 32)]
    top_orgs = [("stripe", 9), ("airbnb", 6)]
    failures = [("unsupported_host", 18), ("malformed", 9)]

    get_db, _ = _mock_db(sequence=[total, by_day, top_orgs, failures])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-stats?days=7")

    body = resp.json()
    assert body["window_days"] == 7
    assert body["total_sessions"] == 42
    assert body["sessions_by_day"] == [
        {"date": "2026-09-22", "count": 10},
        {"date": "2026-09-23", "count": 32},
    ]
    assert body["top_orgs"] == [
        {"org": "stripe", "count": 9},
        {"org": "airbnb", "count": 6},
    ]
    assert body["parse_failures"]["total"] == 27
    assert body["parse_failures"]["by_reason"][0] == {
        "reason": "unsupported_host", "count": 18,
    }


def test_demo_stats_empty_database(admin_client):
    get_db, _ = _mock_db(sequence=[0, [], [], []])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-stats")
    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["parse_failures"]["total"] == 0


def test_demo_stats_clamps_days(admin_client):
    get_db, _ = _mock_db(sequence=[0, [], [], []])
    with patch("src.api.admin.get_db", get_db):
        assert admin_client.get(
            "/api/v1/admin/demo-stats?days=9999"
        ).json()["window_days"] == 365

    get_db, _ = _mock_db(sequence=[0, [], [], []])
    with patch("src.api.admin.get_db", get_db):
        assert admin_client.get(
            "/api/v1/admin/demo-stats?days=0"
        ).json()["window_days"] == 1


# ── /admin/demo-sessions/{id} ──────────────────────────────────────────

def test_demo_session_detail_returns_all_calls(admin_client):
    ts1 = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 9, 23, 14, 5, tzinfo=timezone.utc)
    payload = {"incident_id": "INC-1", "title": "test"}
    rows = [
        (1, "https://github.com/a/b", "a", "b", "Java", True, None, payload,
         "INC-1", ts1),
        (2, "https://github.com/a/b", "a", "b", "Java", False, "rate_limited",
         None, None, ts2),
    ]
    get_db, _ = _mock_db(sequence=[rows])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-sessions/sess-abc")

    body = resp.json()
    assert body["session_id"] == "sess-abc"
    assert body["call_count"] == 2
    assert body["calls"][0]["incident_payload"] == payload
    assert body["calls"][1]["parse_ok"] is False
    assert body["calls"][1]["error_reason"] == "rate_limited"


def test_demo_session_detail_404_when_missing(admin_client):
    get_db, _ = _mock_db(sequence=[[]])
    with patch("src.api.admin.get_db", get_db):
        resp = admin_client.get("/api/v1/admin/demo-sessions/does-not-exist")
    assert resp.status_code == 404
