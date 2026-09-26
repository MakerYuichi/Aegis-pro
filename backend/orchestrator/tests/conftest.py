"""
Shared test fixtures.

Two kinds of fixtures live here:

1. Real-DB fixtures (db_session, seeded_*, db_error, make_incident):
   Give tests a real Postgres session bound to a transaction that
   rolls back at teardown. Use these when the test is about SQL
   logic — queries, transactions, rollback behavior.

2. The autouse `_reset_settings` fixture reloads LLM/service factories
   between tests so cached provider chains don't leak. It deliberately
   does NOT reload src.config, because src.database captured
   settings.DATABASE_URL at import time and would then point at a
   stale engine.

Tests that use real-DB fixtures skip with a clear message if Postgres
isn't reachable. This lets mocked tests keep running on a machine
without docker-compose up.
"""
import os

# Set dummy Auth0 env vars BEFORE any module imports src.config
# so that src.auth can construct the Auth0FastAPI client without
# real credentials. Tests mock the actual auth behavior.
os.environ.setdefault("AUTH0_DOMAIN", "test-tenant.us.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://test-api")

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import text
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# ---------------------------------------------------------------------------
# Autouse settings reset
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """
    Reload LLM and service factories between tests so cached provider
    chains don't leak across tests.

    Deliberately does NOT reload src.config: src.database captured
    settings.DATABASE_URL at import time, and reloading config would
    leave the engine bound to a stale URL.
    """
    import importlib
    from src.llm import factory as llm_factory
    from src.services import factory as svc_factory

    importlib.reload(llm_factory)
    importlib.reload(svc_factory)

    yield


# ---------------------------------------------------------------------------
# Real-DB fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """
    Yield a real AsyncSession bound to an outer transaction that is
    rolled back at teardown. Nothing the test writes persists.

    Also monkeypatches src.database.AsyncSessionLocal so that any code
    inside the test which calls `get_db_session()` shares this same
    connection and sees the test's uncommitted writes.

    If Postgres isn't reachable, skip the test with a clear message.
    If the engine is bound to a different event loop (which happens
    when TestClient is used elsewhere), raise — that's a real bug,
    not an environmental issue.
    """
    from src import database as db_module

    try:
        async with db_module.engine.connect() as probe:
            await probe.execute(text("SELECT 1"))
    except OSError as e:
        # Actual connection failure — Postgres likely not running.
        pytest.skip(f"Postgres not reachable — is docker-compose up? ({e})")
    except RuntimeError as e:
        # Loop-related error — do NOT skip. Surface the real problem.
        raise RuntimeError(
            "Engine is bound to a different event loop. This usually "
            "means TestClient was used in the same test, which runs "
            "the ASGI app in a separate loop. Switch to "
            "httpx.AsyncClient + ASGITransport for those tests. "
            f"Underlying error: {e}"
        )

    conn = await db_module.engine.connect()
    trans = await conn.begin()

    SessionLocal = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()

    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = SessionLocal

    try:
        yield session
    finally:
        await session.close()
        db_module.AsyncSessionLocal = original
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
def db_error(monkeypatch):
    """
    Force every get_db_session() call inside the test to raise
    RuntimeError. Use this to test exception-path behavior without
    mocking an entire session.
    """
    from src import database as db_module

    class ExplodingSession:
        async def __aenter__(self):
            raise RuntimeError("forced DB error")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(db_module, "AsyncSessionLocal", ExplodingSession)
    yield


@pytest_asyncio.fixture
async def seeded_services(db_session):
    """
    Insert the 8 known services inside the test transaction.
    Yields the list of names inserted. Rolled back at teardown.
    """
    rows = [
        ("payment-api", "Payment processing", "payment-service",
         '["@marcus", "@prisha"]', '["auth", "ledger", "fraud"]', True),
        ("auth", "Authentication and authorization", "auth-service",
         '["@dana", "@wei"]', '["user"]', True),
        ("ledger", "Transaction ledger and accounting", "ledger-service",
         '["@sofia", "@ade"]', '["database"]', True),
        ("refund", "Refund and reversal processing", "refund-service",
         '["@nina"]', '["payment-api", "auth"]', False),
        ("fraud", "Fraud detection and risk scoring", "fraud-service",
         '["@omar"]', '["payment-api", "auth"]', False),
        ("notification", "Email, SMS, and push notifications", "notification-service",
         '["@lila"]', '["user"]', False),
        ("user", "User profile and KYC management", "user-service",
         '["@kenji"]', '[]', False),
        ("database", "Database operations and migrations", "database-service",
         '["@rina", "@youssef"]', '[]', True),
    ]
    for r in rows:
        await db_session.execute(
            text("""
                INSERT INTO services
                    (name, description, repo_name, on_call, dependencies, is_critical)
                VALUES
                    (:name, :description, :repo_name,
                     CAST(:on_call AS jsonb), CAST(:dependencies AS jsonb),
                     :is_critical)
                ON CONFLICT (name) DO NOTHING
            """),
            {
                "name": r[0], "description": r[1], "repo_name": r[2],
                "on_call": r[3], "dependencies": r[4], "is_critical": r[5],
            },
        )
    await db_session.flush()
    yield [r[0] for r in rows]


@pytest_asyncio.fixture
async def seeded_incidents(db_session):
    """
    Insert two known incidents inside the test transaction.
    Yields the list of incident_ids inserted.
    """
    incidents = [
        {
            "incident_id": "INC-TEST-001",
            "service_name": "payment-api",
            "severity": "P1",
            "status": "active",
            "title": "Payment API 500s",
            "description": "Users cannot complete checkout",
            "root_cause": "Null deref in charge handler",
            "suggested_fix": "Guard against None",
            "rollback_command": "kubectl rollout undo deploy/payment-api",
            "confidence_score": 0.85,
            "extra_metadata": '{"rag_context_used": false}',
            "affected_services": '["payment-api", "auth"]',
        },
        {
            "incident_id": "INC-TEST-002",
            "service_name": "auth",
            "severity": "P2",
            "status": "active",
            "title": "Auth latency spike",
            "description": "Login times out for 5% of users",
            "root_cause": "Connection pool exhausted",
            "suggested_fix": "Raise pool size",
            "rollback_command": "kubectl rollout undo deploy/auth-service",
            "confidence_score": 0.72,
            "extra_metadata": '{"rag_context_used": true}',
            "affected_services": '["auth"]',
        },
    ]
    for i in incidents:
        await db_session.execute(
            text("""
                INSERT INTO incidents (
                    incident_id, service_name, severity, status,
                    title, description,
                    root_cause, suggested_fix, rollback_command, confidence_score,
                    declared_at, extra_metadata, affected_services
                ) VALUES (
                    :incident_id, :service_name, :severity, :status,
                    :title, :description,
                    :root_cause, :suggested_fix, :rollback_command, :confidence_score,
                    NOW(), CAST(:extra_metadata AS jsonb), CAST(:affected_services AS jsonb)
                )
                ON CONFLICT (incident_id) DO NOTHING
            """),
            i,
        )
    await db_session.flush()
    yield [i["incident_id"] for i in incidents]


@pytest_asyncio.fixture
def make_incident(db_session):
    """
    Factory: insert an incident with arbitrary fields inside the test
    transaction. Returns an async callable that takes a dict and
    returns the incident_id.

    Usage:
        async def test_x(make_incident):
            iid = await make_incident({
                "incident_id": "INC-CUSTOM-1",
                "extra_metadata": "{invalid json}",
            })
    """
    async def _make(overrides: dict) -> str:
        defaults = {
            "incident_id": "INC-FIXTURE-001",
            "service_name": "payment-api",
            "severity": "P1",
            "status": "active",
            "title": "Fixture incident",
            "description": "Fixture description",
            "root_cause": "Fixture root cause",
            "suggested_fix": "Fixture fix",
            "rollback_command": "kubectl rollout undo deploy/payment-api",
            "confidence_score": 0.5,
            "extra_metadata": '{}',
            "affected_services": '[]',
        }
        defaults.update(overrides)
        await db_session.execute(
            text("""
                INSERT INTO incidents (
                    incident_id, service_name, severity, status,
                    title, description,
                    root_cause, suggested_fix, rollback_command, confidence_score,
                    declared_at, extra_metadata, affected_services
                ) VALUES (
                    :incident_id, :service_name, :severity, :status,
                    :title, :description,
                    :root_cause, :suggested_fix, :rollback_command, :confidence_score,
                    NOW(), CAST(:extra_metadata AS jsonb), CAST(:affected_services AS jsonb)
                )
                ON CONFLICT (incident_id) DO NOTHING
            """),
            defaults,
        )
        await db_session.flush()
        return defaults["incident_id"]

    return _make


@pytest_asyncio.fixture
async def seeded_oncall(db_session):
    """
    Assert that migration 003 seeded at least 9 active on-call rows,
    and yield them. Tests that need on-call data use this fixture.

    The fixture does NOT insert data — the migration owns the seed.
    If the migration is missing (or was skipped), the assert fires
    with an actionable message.
    """
    result = await db_session.execute(
        text("""
            SELECT service_name, engineer_name, slack_handle, email, phone, role
            FROM oncall_rotations
            WHERE is_active = TRUE
            ORDER BY service_name, role
        """)
    )
    rows = [dict(r._mapping) for r in result.fetchall()]
    assert len(rows) >= 9, (
        f"Expected at least 9 active on-call rows from migration 003, found {len(rows)}. "
        "Did the migration run? If the DB volume is stale, try: "
        "docker-compose --env-file ci.env down -v && up -d"
    )
    yield rows

@pytest_asyncio.fixture
async def seeded_demo_sessions(db_session):
    """
    Insert 5 demo_sessions rows across 3 days with 2 orgs and 2 parse
    failures, inside the test transaction. Rolls back at teardown.

    Date anchors are fixed in the past so the /demo-stats endpoint's
    NOW() - make_interval(days => :days) window always includes them,
    regardless of when tests run.

    Yields the list of session_ids inserted.
    """
    sessions = [
        # 2026-09-22: 2 successes, 1 failure
        {"session_id": "sess-a",
         "raw_input": "https://github.com/stripe/connect",
         "parsed_org": "stripe", "parsed_repo": "connect",
         "language_inferred": "Java",
         "parse_ok": True, "error_reason": None,
         "incident_payload": '{"incident_id": "INC-DEMO-1", "title": "t1"}',
         "incident_id": "INC-DEMO-1",
         "created_at": datetime(2026, 9, 22, 10, 0, 0),
         "last_seen_at": datetime(2026, 9, 22, 10, 0, 0)},
        {"session_id": "sess-b",
         "raw_input": "https://github.com/airbnb/lottie",
         "parsed_org": "airbnb", "parsed_repo": "lottie",
         "language_inferred": "Node",
         "parse_ok": True, "error_reason": None,
         "incident_payload": '{"incident_id": "INC-DEMO-2", "title": "t2"}',
         "incident_id": "INC-DEMO-2",
         "created_at": datetime(2026, 9, 22, 11, 0, 0),
         "last_seen_at": datetime(2026, 9, 22, 11, 0, 0)},
        {"session_id": "sess-c",
         "raw_input": "https://gitea.com/foo/bar",
         "parsed_org": None, "parsed_repo": None,
         "language_inferred": None,
         "parse_ok": False, "error_reason": "unsupported_host",
         "incident_payload": None, "incident_id": None,
         "created_at": datetime(2026, 9, 22, 12, 0, 0),
         "last_seen_at": datetime(2026, 9, 22, 12, 0, 0)},

        # 2026-09-23: 1 success
        {"session_id": "sess-d",
         "raw_input": "https://github.com/stripe/charge",
         "parsed_org": "stripe", "parsed_repo": "charge",
         "language_inferred": "Java",
         "parse_ok": True, "error_reason": None,
         "incident_payload": '{"incident_id": "INC-DEMO-3", "title": "t3"}',
         "incident_id": "INC-DEMO-3",
         "created_at": datetime(2026, 9, 23, 9, 0, 0),
         "last_seen_at": datetime(2026, 9, 23, 9, 0, 0)},

        # 2026-09-24: 1 failure
        {"session_id": "sess-e",
         "raw_input": "has spaces in it",
         "parsed_org": None, "parsed_repo": None,
         "language_inferred": None,
         "parse_ok": False, "error_reason": "malformed",
         "incident_payload": None, "incident_id": None,
         "created_at": datetime(2026, 9, 24, 8, 0, 0),
         "last_seen_at": datetime(2026, 9, 24, 8, 0, 0)},
    ]
    for s in sessions:
        await db_session.execute(
            text("""
                INSERT INTO demo_sessions (
                    session_id, raw_input, parsed_org, parsed_repo,
                    language_inferred, parse_ok, error_reason,
                    incident_payload, incident_id,
                    created_at, last_seen_at
                ) VALUES (
                    :session_id, :raw_input, :parsed_org, :parsed_repo,
                    :language_inferred, :parse_ok, :error_reason,
                    CAST(:incident_payload AS jsonb), :incident_id,
                    CAST(:created_at AS timestamp), CAST(:last_seen_at AS timestamp)
                )
            """),
            s,
        )
    await db_session.flush()
    yield [s["session_id"] for s in sessions]
    
@pytest_asyncio.fixture
async def seeded_alert_history(db_session):
    """
    Insert 3 alert_history rows inside the test transaction.
    Yields the list of row IDs inserted.
    """
    from datetime import datetime
    rows = [
        {"engineer": "@alice", "service": "svc-a", "message": "msg-a", "status": "sent",
         "created_at": datetime(2026, 1, 1, 10, 0, 0)},
        {"engineer": "@bob",   "service": "svc-b", "message": "msg-b", "status": "failed",
         "created_at": datetime(2026, 1, 2, 11, 0, 0)},
        {"engineer": "@carol", "service": "svc-c", "message": "msg-c", "status": "sent",
         "created_at": datetime(2026, 1, 3, 12, 0, 0)},
    ]
    ids = []
    for r in rows:
        result = await db_session.execute(
            text("""
                INSERT INTO alert_history (engineer_name, service_name, message, status, created_at)
                VALUES (:engineer, :service, :message, :status, :created_at)
                RETURNING id
            """),
            r,
        )
        ids.append(result.scalar())
    await db_session.flush()
    yield ids
