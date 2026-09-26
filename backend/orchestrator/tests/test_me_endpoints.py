"""
Tests for Phase 10 — demo-to-dashboard continuity.

Endpoints covered:
  - GET  /api/v1/me/demo-sessions
  - POST /api/v1/me/link-demo-session
  - POST /api/v1/me/onboarding-interest

The db_session fixture monkeypatches AsyncSessionLocal, so any
get_db_session() call inside the endpoints shares the test's
transaction. Rows written by the endpoint are visible to the test,
and everything rolls back at teardown.

Auth is overridden with a dependency that returns a canned claims
dict — we're testing the endpoint logic, not Auth0.
"""
import pytest
import pytest_asyncio
from datetime import datetime
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.main import app
from src.auth import require_auth


TEST_EMAIL = "buyer@example.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_as_buyer():
    """
    Override require_auth to return a canned claims dict for
    TEST_EMAIL. Cleaned up at teardown.

    The email key matches what _claim_email() looks for first.
    """
    def _override():
        return {"email": TEST_EMAIL, "sub": "auth0|test"}

    app.dependency_overrides[require_auth] = _override
    yield
    app.dependency_overrides.pop(require_auth, None)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def linked_sessions(db_session):
    """
    Insert three demo_sessions owned by TEST_EMAIL and one owned by
    someone else. Yields the owned session_ids (newest first).
    """
    rows = [
        {
            "session_id": "sess-mine-1",
            "raw_input": "https://github.com/stripe/charge",
            "parsed_org": "stripe", "parsed_repo": "charge",
            "language_inferred": "Java",
            "parse_ok": True, "error_reason": None,
            "incident_payload": None, "incident_id": "INC-1",
            "created_at": datetime(2026, 9, 20, 10, 0, 0),
            "last_seen_at": datetime(2026, 9, 20, 10, 0, 0),
            "user_email": TEST_EMAIL,
        },
        {
            "session_id": "sess-mine-2",
            "raw_input": "https://github.com/airbnb/lottie",
            "parsed_org": "airbnb", "parsed_repo": "lottie",
            "language_inferred": "Node",
            "parse_ok": True, "error_reason": None,
            "incident_payload": None, "incident_id": "INC-2",
            "created_at": datetime(2026, 9, 22, 10, 0, 0),
            "last_seen_at": datetime(2026, 9, 22, 10, 0, 0),
            "user_email": TEST_EMAIL,
        },
        {
            "session_id": "sess-mine-failed",
            "raw_input": "https://gitea.com/foo/bar",
            "parsed_org": None, "parsed_repo": None,
            "language_inferred": None,
            "parse_ok": False, "error_reason": "unsupported_host",
            "incident_payload": None, "incident_id": None,
            "created_at": datetime(2026, 9, 23, 10, 0, 0),
            "last_seen_at": datetime(2026, 9, 23, 10, 0, 0),
            "user_email": TEST_EMAIL,
        },
        {
            "session_id": "sess-someone-else",
            "raw_input": "https://github.com/other/repo",
            "parsed_org": "other", "parsed_repo": "repo",
            "language_inferred": "Go",
            "parse_ok": True, "error_reason": None,
            "incident_payload": None, "incident_id": "INC-OTHER",
            "created_at": datetime(2026, 9, 24, 10, 0, 0),
            "last_seen_at": datetime(2026, 9, 24, 10, 0, 0),
            "user_email": "someone-else@example.com",
        },
    ]
    for r in rows:
        await db_session.execute(
            text("""
                INSERT INTO demo_sessions (
                    session_id, raw_input, parsed_org, parsed_repo,
                    language_inferred, parse_ok, error_reason,
                    incident_payload, incident_id,
                    created_at, last_seen_at, user_email
                ) VALUES (
                    :session_id, :raw_input, :parsed_org, :parsed_repo,
                    :language_inferred, :parse_ok, :error_reason,
                    CAST(:incident_payload AS jsonb), :incident_id,
                    CAST(:created_at AS timestamp), CAST(:last_seen_at AS timestamp),
                    :user_email
                )
            """),
            r,
        )
    await db_session.flush()
    yield ["sess-mine-1", "sess-mine-2", "sess-mine-failed"]


# ---------------------------------------------------------------------------
# GET /api/v1/me/demo-sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_returns_only_my_sessions(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.get("/api/v1/me/demo-sessions")
    assert res.status_code == 200
    body = res.json()
    ids = {s["session_id"] for s in body["sessions"]}
    # Only the two parse_ok sessions owned by TEST_EMAIL
    assert ids == {"sess-mine-1", "sess-mine-2"}
    # The other user's session is not visible
    assert "sess-someone-else" not in ids
    # The failed parse is not visible
    assert "sess-mine-failed" not in ids


@pytest.mark.asyncio
async def test_list_is_newest_first(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.get("/api/v1/me/demo-sessions")
    sessions = res.json()["sessions"]
    assert sessions[0]["session_id"] == "sess-mine-2"  # 2026-09-22
    assert sessions[1]["session_id"] == "sess-mine-1"  # 2026-09-20


@pytest.mark.asyncio
async def test_list_empty_for_user_with_no_sessions(client, auth_as_buyer, db_session):
    res = await client.get("/api/v1/me/demo-sessions")
    assert res.status_code == 200
    assert res.json() == {"sessions": [], "count": 0}


@pytest.mark.asyncio
async def test_list_respects_limit(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.get("/api/v1/me/demo-sessions?limit=1")
    assert len(res.json()["sessions"]) == 1


@pytest.mark.asyncio
async def test_list_clamps_absurd_limit(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.get("/api/v1/me/demo-sessions?limit=99999")
    # No error, just clamped. Body is well-formed.
    assert res.status_code == 200
    assert "sessions" in res.json()


@pytest.mark.asyncio
async def test_list_requires_auth(client, db_session):
    # No auth_as_buyer fixture — the real require_auth runs, no token present
    res = await client.get("/api/v1/me/demo-sessions")
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/v1/me/link-demo-session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_link_attaches_email_to_session(client, auth_as_buyer, db_session):
    await db_session.execute(
        text("""
            INSERT INTO demo_sessions (
                session_id, raw_input, parsed_org, parsed_repo,
                parse_ok, created_at, last_seen_at
            ) VALUES (
                'sess-new', 'https://github.com/x/y', 'x', 'y',
                true, NOW(), NOW()
            )
        """)
    )
    await db_session.flush()

    client.cookies.set("demo_session_id", "sess-new")
    res = await client.post("/api/v1/me/link-demo-session")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "linked"
    assert body["email"] == TEST_EMAIL

    row = await db_session.execute(
        text("SELECT user_email FROM demo_sessions WHERE session_id = 'sess-new'")
    )
    assert row.scalar() == TEST_EMAIL


@pytest.mark.asyncio
async def test_link_returns_no_cookie_when_absent(client, auth_as_buyer, db_session):
    # No cookie set
    res = await client.post("/api/v1/me/link-demo-session")
    assert res.status_code == 200
    assert res.json()["status"] == "no_cookie"


@pytest.mark.asyncio
async def test_link_returns_no_match_for_unknown_session(client, auth_as_buyer, db_session):
    client.cookies.set("demo_session_id", "sess-does-not-exist")
    res = await client.post("/api/v1/me/link-demo-session")
    assert res.status_code == 200
    assert res.json()["status"] == "no_match"


@pytest.mark.asyncio
async def test_link_accepts_when_cookie_matches(client, auth_as_buyer, db_session):
    await db_session.execute(
        text("""
            INSERT INTO demo_sessions (
                session_id, raw_input, parsed_org, parsed_repo,
                parse_ok, created_at, last_seen_at
            ) VALUES (
                'sess-cookie-match', 'https://github.com/x/y', 'x', 'y',
                true, NOW(), NOW()
            )
        """)
    )
    await db_session.flush()

    client.cookies.set("demo_session_id", "sess-cookie-match")
    res = await client.post("/api/v1/me/link-demo-session")
    assert res.status_code == 200
    assert res.json()["status"] == "linked"


@pytest.mark.asyncio
async def test_link_is_idempotent(client, auth_as_buyer, db_session):
    await db_session.execute(
        text("""
            INSERT INTO demo_sessions (
                session_id, raw_input, parsed_org, parsed_repo,
                parse_ok, created_at, last_seen_at
            ) VALUES (
                'sess-idem', 'https://github.com/x/y', 'x', 'y',
                true, NOW(), NOW()
            )
        """)
    )
    await db_session.flush()

    client.cookies.set("demo_session_id", "sess-idem")
    for _ in range(2):
        res = await client.post("/api/v1/me/link-demo-session")
        assert res.status_code == 200
        assert res.json()["status"] == "linked"

# ---------------------------------------------------------------------------
# POST /api/v1/me/onboarding-interest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_onboarding_interest_marks_specified_session(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.post(
        "/api/v1/me/onboarding-interest",
        json={"session_id": "sess-mine-1", "repo": "stripe/charge"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "recorded"

    row = await db_session.execute(
        text("""
            SELECT onboarding_clicked_at FROM demo_sessions
            WHERE session_id = 'sess-mine-1'
        """)
    )
    assert row.scalar() is not None


@pytest.mark.asyncio
async def test_onboarding_interest_marks_most_recent_when_unspecified(client, auth_as_buyer, linked_sessions, db_session):
    res = await client.post(
        "/api/v1/me/onboarding-interest",
        json={"repo": "airbnb/lottie"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "recorded"

    # sess-mine-2 is the newest parse_ok session for TEST_EMAIL
    row = await db_session.execute(
        text("""
            SELECT onboarding_clicked_at FROM demo_sessions
            WHERE session_id = 'sess-mine-2'
        """)
    )
    assert row.scalar() is not None


@pytest.mark.asyncio
async def test_onboarding_interest_rejects_other_users_session(client, auth_as_buyer, linked_sessions, db_session):
    """A user cannot mark interest in a session that isn't theirs."""
    res = await client.post(
        "/api/v1/me/onboarding-interest",
        json={"session_id": "sess-someone-else", "repo": "other/repo"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "no_match"

    # Verify nothing was written
    row = await db_session.execute(
        text("""
            SELECT onboarding_clicked_at FROM demo_sessions
            WHERE session_id = 'sess-someone-else'
        """)
    )
    assert row.scalar() is None


@pytest.mark.asyncio
async def test_onboarding_interest_returns_no_match_when_nothing_linked(client, auth_as_buyer, db_session):
    res = await client.post(
        "/api/v1/me/onboarding-interest",
        json={"repo": "foo/bar"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "no_match"
