"""
Tests for OnCallService.

Real-DB tests use fixtures from conftest.py (seeded_oncall,
seeded_services, seeded_inactive_oncall, db_error). Parsing-only
tests keep their mocks — they don't need a DB.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from src.services.oncall_service import OnCallService


@pytest.fixture
def service():
    return OnCallService()


def _row(id_, service_name, name, slack, email, phone, role, is_active=True):
    """8-column row for the parsing-only tests."""
    return (id_, service_name, name, slack, email, phone, role, is_active)


def _mock_db_session(rows=None, row_one=None, execute_side_effect=None):
    """Minimal get_db_session replacement for parsing-only tests."""
    from contextlib import asynccontextmanager

    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = row_one
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    if execute_side_effect is not None:
        session.execute = AsyncMock(side_effect=execute_side_effect)

    @asynccontextmanager
    async def _cm():
        yield session

    return lambda: _cm(), session


# ---------------------------------------------------------------------------
# _row_to_person — pure
# ---------------------------------------------------------------------------

def test_row_to_person_eight_columns(service):
    person = service._row_to_person(_row(1, "svc", "Alice", "@alice",
                                          "a@x.com", "555", "primary", True))
    assert person == {
        "id": 1, "service_name": "svc", "name": "Alice", "slack_handle": "@alice",
        "email": "a@x.com", "phone": "555", "role": "primary", "is_active": True,
    }


def test_row_to_person_seven_columns_defaults_active_true(service):
    row = (1, "svc", "Alice", "@alice", "a@x.com", "555", "primary")
    person = service._row_to_person(row)
    assert person["is_active"] is True


def test_row_to_person_null_fields(service):
    row = (1, "svc", "Alice", None, None, None, "primary", True)
    person = service._row_to_person(row)
    assert person["slack_handle"] is None
    assert person["email"] is None
    assert person["phone"] is None


def test_row_to_person_invalid_role(service):
    row = (1, "svc", "Alice", "@alice", "a@x.com", "555", "invalid_role", True)
    person = service._row_to_person(row)
    assert person["role"] == "invalid_role"


# ---------------------------------------------------------------------------
# get_on_call — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_on_call_returns_roles_in_order(service, seeded_oncall):
    """Real DB: payment-api has 3 seeded rotations (Marcus/p Prisha/Tomas)."""
    result = await service.get_on_call("payment-api")
    assert result["primary"]["name"] == "Marcus Chen"
    assert result["secondary"]["name"] == "prisha Raman"
    assert result["tertiary"]["name"] == "Tomas Alvarez"


@pytest.mark.asyncio
async def test_get_on_call_empty_rows_falls_back(service, seeded_services):
    """
    Real DB: service 'user' has no oncall_rotations rows, but
    services.on_call = '["@kenji"]'. get_on_call hits the fallback path
    and reads from the services table.
    """
    result = await service.get_on_call("user")
    # _fallback_from_service returns the seeded services.on_call handles
    assert result["primary"]["name"] == "@kenji"
    assert result["secondary"] is None
    assert result["tertiary"] is None


@pytest.mark.asyncio
async def test_get_on_call_db_error_falls_back(service, db_error):
    """db_error forces DB failure; get_on_call falls back to _fallback_from_service,
    which also fails and returns an error dict."""
    result = await service.get_on_call("payment-api")
    # Fallback also fails, so we get the error dict shape
    assert "error" in result


@pytest.mark.asyncio
async def test_get_on_call_filters_inactive(service, seeded_inactive_oncall, db_session):
    """
    Real DB: a service with only an inactive rotation row and no services
    entry falls through to the fallback, which also finds nothing.
    """
    # First confirm the inactive row is really in the table
    n = (await db_session.execute(
        text("SELECT COUNT(*) FROM oncall_rotations WHERE service_name = 'inactive-test-svc' AND is_active = FALSE")
    )).scalar()
    assert n == 1

    result = await service.get_on_call("inactive-test-svc")
    # Inactive row filtered out; services table has no entry; fallback errors
    assert "error" in result


@pytest.mark.asyncio
async def test_get_on_call_unexpected_role(service, db_session):
    """Real DB: insert a row with role='manager', verify it fills no slot."""
    await db_session.execute(text("DELETE FROM oncall_rotations WHERE service_name = 'weird-svc'"))
    await db_session.execute(
        text("""
            INSERT INTO oncall_rotations
                (service_name, engineer_name, slack_handle, role, is_active)
            VALUES ('weird-svc', 'Alice', '@alice', 'manager', TRUE)
        """)
    )
    await db_session.flush()

    result = await service.get_on_call("weird-svc")
    assert result["primary"] is None
    assert result["secondary"] is None
    assert result["tertiary"] is None


# ---------------------------------------------------------------------------
# _fallback_from_service — parsing tests, mocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_from_service_json_string_handles(service):
    get_db, _ = _mock_db_session(row_one=('["@alice", "@bob"]',))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@alice"
    assert result["secondary"]["name"] == "@bob"
    assert result["tertiary"] is None


@pytest.mark.asyncio
async def test_fallback_from_service_list_handles(service):
    get_db, _ = _mock_db_session(row_one=(["@alice"],))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@alice"
    assert result["primary"]["slack"] == "@alice"


@pytest.mark.asyncio
async def test_fallback_from_service_no_handles_returns_error(service):
    get_db, _ = _mock_db_session(row_one=(None,))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert "error" in result
    assert "No on-call schedule" in result["error"]


@pytest.mark.asyncio
async def test_fallback_from_service_empty_list_returns_error(service):
    get_db, _ = _mock_db_session(row_one=([],))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert "error" in result


@pytest.mark.asyncio
async def test_fallback_from_service_db_error_returns_error_dict(service, db_error):
    result = await service._fallback_from_service("svc")
    assert "error" in result


@pytest.mark.asyncio
async def test_fallback_from_service_caps_at_three(service):
    get_db, _ = _mock_db_session(row_one=(["@a", "@b", "@c", "@d"],))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@a"
    assert result["secondary"]["name"] == "@b"
    assert result["tertiary"]["name"] == "@c"


@pytest.mark.asyncio
async def test_fallback_from_service_malformed_json(service):
    get_db, _ = _mock_db_session(row_one=('{invalid json}',))
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._fallback_from_service("svc")

    assert "error" in result


# ---------------------------------------------------------------------------
# list_roster — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_roster_with_service_filter(service, seeded_oncall):
    """Real DB: filter to payment-api, get 3 seeded rows."""
    result = await service.list_roster("payment-api")
    assert len(result) == 3
    assert {p["role"] for p in result} == {"primary", "secondary", "tertiary"}
    assert {p["name"] for p in result} == {"Marcus Chen", "prisha Raman", "Tomas Alvarez"}


@pytest.mark.asyncio
async def test_list_roster_no_filter(service, seeded_oncall):
    """Real DB: no filter, get all seeded rows."""
    result = await service.list_roster()
    assert len(result) >= 9
    names = {p["name"] for p in result}
    assert "Marcus Chen" in names
    assert "Dana Okafor" in names
    assert "Sofia Marchetti" in names


@pytest.mark.asyncio
async def test_list_roster_empty_rows_falls_back_to_services(service, seeded_services, db_session):
    """
    Real DB: no oncall_rotations rows visible (delete inside the transaction),
    so list_roster falls through to _roster_from_services, which reads from
    services.on_call.
    """
    await db_session.execute(text("DELETE FROM oncall_rotations"))
    await db_session.flush()

    result = await service.list_roster()
    # Falls back to services.on_call handles
    assert len(result) > 0
    # The roster_from_services returns handles like @marcus, @dana, etc.
    handles = {p.get("slack_handle") for p in result}
    assert "@marcus" in handles or "@dana" in handles


@pytest.mark.asyncio
async def test_list_roster_db_error_falls_back(service, db_error):
    """db_error forces DB failure; list_roster falls back to _roster_from_services,
    which also fails and returns []."""
    result = await service.list_roster()
    assert result == []


@pytest.mark.asyncio
async def test_list_roster_filters_inactive(service, seeded_inactive_oncall, db_session):
    """Real DB: inactive row for inactive-test-svc is not returned."""
    result = await service.list_roster("inactive-test-svc")
    # The inactive row is filtered; if services table has no row either,
    # _roster_from_services returns []
    assert all(p.get("slack_handle") != "@ghost" for p in result)


# ---------------------------------------------------------------------------
# _roster_from_services — parsing tests, mocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roster_from_services_parses_json_string(service):
    rows = [("svc", '["@alice", "@bob"]')]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._roster_from_services()

    names = [p["name"] for p in result]
    assert names == ["Alice", "Bob"]
    assert result[0]["role"] == "primary"
    assert result[1]["role"] == "secondary"
    assert result[0]["id"] == "svc-@alice"


@pytest.mark.asyncio
async def test_roster_from_services_with_filter(service):
    rows = [("svc", ["@alice"])]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._roster_from_services("svc")

    assert len(result) == 1
    assert result[0]["service_name"] == "svc"


@pytest.mark.asyncio
async def test_roster_from_services_null_handles(service):
    rows = [("svc", None)]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._roster_from_services()

    assert result == []


@pytest.mark.asyncio
async def test_roster_from_services_role_overflow_defaults_secondary(service):
    rows = [("svc", ["@a", "@b", "@c", "@d"])]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._roster_from_services()

    assert result[3]["role"] == "secondary"


@pytest.mark.asyncio
async def test_roster_from_services_db_error_returns_empty(service, db_error):
    result = await service._roster_from_services()
    assert result == []


@pytest.mark.asyncio
async def test_roster_from_services_handle_without_at(service):
    rows = [("svc", ["alice"])]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db_session", get_db):
        result = await service._roster_from_services()

    assert result[0]["name"] == "Alice"
    assert result[0]["slack_handle"] == "alice"


# ---------------------------------------------------------------------------
# add_member — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_member_inserts_and_updates_services(service, seeded_services, db_session):
    """Real DB: add a member to payment-api, verify the rotation row and the
    services.on_call JSONB were both updated."""
    member = {
        "service_name": "payment-api",
        "name": "Test Engineer",
        "slack_handle": "@test-engineer",
        "email": "te@acme.com",
        "phone": "555-0100",
        "role": "secondary",
    }
    result = await service.add_member(member)
    assert result["status"] == "created"
    assert isinstance(result["id"], int)

    # Verify the oncall_rotations row exists
    row = (await db_session.execute(
        text("""
            SELECT engineer_name, role FROM oncall_rotations
            WHERE service_name = 'payment-api' AND slack_handle = '@test-engineer'
        """)
    )).fetchone()
    assert row is not None
    assert row[0] == "Test Engineer"
    assert row[1] == "secondary"

    # Verify services.on_call was updated (contains the new handle)
    svc_row = (await db_session.execute(
        text("SELECT on_call FROM services WHERE name = 'payment-api'")
    )).fetchone()
    on_call_json = svc_row[0] if isinstance(svc_row[0], list) else json.loads(svc_row[0])
    assert "@test-engineer" in on_call_json


@pytest.mark.asyncio
async def test_add_member_derives_slack_handle_when_missing(service, seeded_services, db_session):
    """Real DB: name-only member; derived handle lands in oncall_rotations."""
    member = {"service_name": "payment-api", "name": "Derived Person"}
    result = await service.add_member(member)
    assert result["status"] == "created"

    row = (await db_session.execute(
        text("""
            SELECT slack_handle FROM oncall_rotations
            WHERE service_name = 'payment-api' AND engineer_name = 'Derived Person'
        """)
    )).fetchone()
    assert row is not None
    assert row[0] == "@derived"


@pytest.mark.asyncio
async def test_add_member_defaults_role_to_secondary(service, seeded_services, db_session):
    """Real DB: no role provided; defaults to secondary."""
    member = {"service_name": "payment-api", "name": "No Role Person", "slack_handle": "@norole"}
    await service.add_member(member)

    row = (await db_session.execute(
        text("""
            SELECT role FROM oncall_rotations
            WHERE service_name = 'payment-api' AND slack_handle = '@norole'
        """)
    )).fetchone()
    assert row is not None
    assert row[0] == "secondary"


@pytest.mark.asyncio
async def test_add_member_db_error_propagates(service, db_error):
    """db_error forces add_member to raise."""
    member = {"service_name": "svc", "name": "Alice"}
    with pytest.raises(RuntimeError, match="forced DB error"):
        await service.add_member(member)


@pytest.mark.asyncio
async def test_add_member_name_with_multiple_words(service, seeded_services, db_session):
    """Real DB: name with multiple words; handle derived from first word."""
    member = {"service_name": "payment-api", "name": "Multi Word Name"}
    await service.add_member(member)

    row = (await db_session.execute(
        text("""
            SELECT slack_handle FROM oncall_rotations
            WHERE service_name = 'payment-api' AND engineer_name = 'Multi Word Name'
        """)
    )).fetchone()
    assert row is not None
    assert row[0] == "@multi"


# ---------------------------------------------------------------------------
# remove_member — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_member_soft_deletes(service, seeded_services, db_session):
    """Real DB: soft-delete a seeded oncall_rotations row."""
    # Insert a member we own, then remove it
    await db_session.execute(
        text("""
            INSERT INTO oncall_rotations
                (service_name, engineer_name, slack_handle, role, is_active)
            VALUES ('payment-api', 'To Remove', '@to-remove', 'tertiary', TRUE)
            RETURNING id
        """)
    )
    member_id = (await db_session.execute(
        text("SELECT id FROM oncall_rotations WHERE slack_handle = '@to-remove'")
    )).scalar()

    result = await service.remove_member(member_id)
    assert result == {"id": member_id, "status": "removed"}

    row = (await db_session.execute(
        text("SELECT is_active FROM oncall_rotations WHERE id = :id"),
        {"id": member_id},
    )).fetchone()
    assert row is not None
    assert row[0] is False


@pytest.mark.asyncio
async def test_remove_member_db_error_propagates(service, db_error):
    with pytest.raises(RuntimeError, match="forced DB error"):
        await service.remove_member(42)


# ---------------------------------------------------------------------------
# get_escalation_policy — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_escalation_policy_shapes_rows(service, seeded_oncall):
    """Real DB: payment-api P0 has 3 escalation levels seeded."""
    result = await service.get_escalation_policy("payment-api", "P0")
    assert len(result) == 3
    # Ordered by level ascending
    levels = [r["level"] for r in result]
    assert levels == [1, 2, 3]
    assert result[0]["engineer"] == "Marcus Chen"
    assert result[0]["wait_time"] == 5


@pytest.mark.asyncio
async def test_get_escalation_policy_empty_returns_empty_list(service, seeded_oncall):
    """Real DB: no policy for this service/severity combination."""
    result = await service.get_escalation_policy("nonexistent-svc", "P9")
    assert result == []


@pytest.mark.asyncio
async def test_get_escalation_policy_db_error_returns_empty(service, db_error):
    result = await service.get_escalation_policy("svc", "P1")
    assert result == []


@pytest.mark.asyncio
async def test_get_escalation_policy_null_optional_fields(service, db_session):
    """Real DB: policy row with NULL slack/email/phone preserved as None."""
    await db_session.execute(
        text("""
            INSERT INTO escalation_policies
                (service_name, severity, escalation_level, engineer_name,
                 slack_handle, email, phone, wait_time_minutes)
            VALUES ('null-test', 'P1', 1, 'Alice', NULL, NULL, NULL, 10)
        """)
    )
    await db_session.flush()

    result = await service.get_escalation_policy("null-test", "P1")
    assert len(result) == 1
    assert result[0]["slack"] is None
    assert result[0]["email"] is None
    assert result[0]["phone"] is None
