"""
Tests for OnCallService.

Covers:
  - get_on_call: primary path, empty rows → fallback, DB error → fallback
  - _fallback_from_service: JSON string vs list, empty → error dict, DB error
  - list_roster: with/without service filter, rows → _row_to_person,
    empty rows → _roster_from_services, DB error → fallback
  - _roster_from_services: both queries, JSON/list handle parsing,
    role assignment, DB error → []
  - add_member: INSERT + UPDATE + commit, default slack handle derivation
  - remove_member: soft delete + commit
  - get_escalation_policy: rows → list, empty → [], DB error → []
  - _row_to_person: 8-column shape, 7-column backward compat
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.oncall_service import OnCallService


@pytest.fixture
def service():
    return OnCallService()


def _row(id_, service_name, name, slack, email, phone, role, is_active=True):
    """8-column row matching the SELECT in get_on_call and list_roster."""
    return (id_, service_name, name, slack, email, phone, role, is_active)


def _mock_db_session(rows=None, scalar=None, row_one=None, execute_side_effect=None):
    """
    Build a get_db replacement matching the real contract:
        session = await get_db()
        async with session:
            await session.execute(...)

    Returns (get_db_callable, session_mock, result_mock).
    """
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = row_one
    result.scalar.return_value = scalar
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    if execute_side_effect is not None:
        session.execute = AsyncMock(side_effect=execute_side_effect)

    async def _get_db():
        return session

    return _get_db, session, result


# ---------------------------------------------------------------------------
# _row_to_person
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


# ---------------------------------------------------------------------------
# get_on_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_on_call_returns_roles_in_order(service):
    rows = [
        _row(1, "svc", "Alice", "@alice", None, None, "secondary"),
        _row(2, "svc", "Bob", "@bob", None, None, "primary"),
    ]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.get_on_call("svc")

    assert result["primary"]["name"] == "Bob"
    assert result["secondary"]["name"] == "Alice"
    assert result["tertiary"] is None


@pytest.mark.asyncio
async def test_get_on_call_empty_rows_falls_back(service):
    get_db, _, _ = _mock_db_session(rows=[])
    with patch("src.services.oncall_service.get_db", get_db), \
         patch.object(service, "_fallback_from_service",
                      new=AsyncMock(return_value={"primary": {"name": "Carol"}})) as fb:
        result = await service.get_on_call("svc")

    fb.assert_awaited_once_with("svc")
    assert result["primary"]["name"] == "Carol"


@pytest.mark.asyncio
async def test_get_on_call_db_error_falls_back(service):
    get_db, _, _ = _mock_db_session(execute_side_effect=RuntimeError("db down"))
    with patch("src.services.oncall_service.get_db", get_db), \
         patch.object(service, "_fallback_from_service",
                      new=AsyncMock(return_value={"primary": None,
                                                   "secondary": None,
                                                   "tertiary": None})) as fb:
        result = await service.get_on_call("svc")

    fb.assert_awaited_once_with("svc")
    assert result["primary"] is None


# ---------------------------------------------------------------------------
# _fallback_from_service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_from_service_json_string_handles(service):
    get_db, _, _ = _mock_db_session(row_one=('["@alice", "@bob"]',))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@alice"
    assert result["secondary"]["name"] == "@bob"
    assert result["tertiary"] is None


@pytest.mark.asyncio
async def test_fallback_from_service_list_handles(service):
    get_db, _, _ = _mock_db_session(row_one=(["@alice"],))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@alice"
    assert result["primary"]["slack"] == "@alice"


@pytest.mark.asyncio
async def test_fallback_from_service_no_handles_returns_error(service):
    get_db, _, _ = _mock_db_session(row_one=(None,))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert "error" in result
    assert "No on-call schedule" in result["error"]


@pytest.mark.asyncio
async def test_fallback_from_service_empty_list_returns_error(service):
    get_db, _, _ = _mock_db_session(row_one=([],))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert "error" in result


@pytest.mark.asyncio
async def test_fallback_from_service_db_error_returns_error_dict(service):
    get_db, _, _ = _mock_db_session(execute_side_effect=RuntimeError("boom"))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert result == {"error": "boom"}


@pytest.mark.asyncio
async def test_fallback_from_service_caps_at_three(service):
    get_db, _, _ = _mock_db_session(row_one=(["@a", "@b", "@c", "@d"],))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._fallback_from_service("svc")

    assert result["primary"]["name"] == "@a"
    assert result["secondary"]["name"] == "@b"
    assert result["tertiary"]["name"] == "@c"


# ---------------------------------------------------------------------------
# list_roster
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_roster_with_service_filter(service):
    rows = [_row(1, "svc", "Alice", "@alice", None, None, "primary")]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.list_roster("svc")

    assert len(result) == 1
    assert result[0]["name"] == "Alice"
    assert result[0]["role"] == "primary"


@pytest.mark.asyncio
async def test_list_roster_no_filter(service):
    rows = [
        _row(1, "svc-a", "Alice", "@alice", None, None, "primary"),
        _row(2, "svc-b", "Bob", "@bob", None, None, "secondary"),
    ]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.list_roster()

    assert {p["name"] for p in result} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_list_roster_empty_rows_falls_back_to_services(service):
    get_db, _, _ = _mock_db_session(rows=[])
    fallback_roster = [{"name": "Carol", "service_name": "svc"}]
    with patch("src.services.oncall_service.get_db", get_db), \
         patch.object(service, "_roster_from_services",
                      new=AsyncMock(return_value=fallback_roster)) as fb:
        result = await service.list_roster("svc")

    fb.assert_awaited_once_with("svc")
    assert result == fallback_roster


@pytest.mark.asyncio
async def test_list_roster_db_error_falls_back(service):
    get_db, _, _ = _mock_db_session(execute_side_effect=RuntimeError("db down"))
    with patch("src.services.oncall_service.get_db", get_db), \
         patch.object(service, "_roster_from_services",
                      new=AsyncMock(return_value=[])) as fb:
        result = await service.list_roster()

    fb.assert_awaited_once_with(None)
    assert result == []


# ---------------------------------------------------------------------------
# _roster_from_services
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roster_from_services_parses_json_string(service):
    rows = [("svc", '["@alice", "@bob"]')]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._roster_from_services()

    names = [p["name"] for p in result]
    assert names == ["Alice", "Bob"]
    assert result[0]["role"] == "primary"
    assert result[1]["role"] == "secondary"
    assert result[0]["id"] == "svc-@alice"


@pytest.mark.asyncio
async def test_roster_from_services_with_filter(service):
    rows = [("svc", ["@alice"])]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._roster_from_services("svc")

    assert len(result) == 1
    assert result[0]["service_name"] == "svc"


@pytest.mark.asyncio
async def test_roster_from_services_null_handles(service):
    rows = [("svc", None)]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._roster_from_services()

    assert result == []


@pytest.mark.asyncio
async def test_roster_from_services_role_overflow_defaults_secondary(service):
    rows = [("svc", ["@a", "@b", "@c", "@d"])]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._roster_from_services()

    assert result[3]["role"] == "secondary"


@pytest.mark.asyncio
async def test_roster_from_services_db_error_returns_empty(service):
    get_db, _, _ = _mock_db_session(execute_side_effect=RuntimeError("boom"))
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service._roster_from_services()

    assert result == []


# ---------------------------------------------------------------------------
# add_member
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_member_inserts_and_updates_services(service):
    get_db, session, _ = _mock_db_session(scalar=42)
    member = {
        "service_name": "svc", "name": "Alice Smith",
        "slack_handle": "@alice", "email": "a@x.com",
        "phone": "555", "role": "primary",
    }
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.add_member(member)

    assert result == {"id": 42, "status": "created"}
    assert session.execute.await_count == 2  # INSERT + UPDATE
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_add_member_derives_slack_handle_when_missing(service):
    get_db, session, _ = _mock_db_session(scalar=7)
    member = {"service_name": "svc", "name": "Alice Smith", "role": "primary"}
    with patch("src.services.oncall_service.get_db", get_db):
        await service.add_member(member)

    # Second call is the UPDATE; check that derived handle is @alice
    update_call = session.execute.await_args_list[1]
    params = update_call.args[1]
    assert params["slack_handle"] == "@alice"


@pytest.mark.asyncio
async def test_add_member_defaults_role_to_secondary(service):
    get_db, session, _ = _mock_db_session(scalar=1)
    member = {"service_name": "svc", "name": "Bob Jones"}
    with patch("src.services.oncall_service.get_db", get_db):
        await service.add_member(member)

    insert_call = session.execute.await_args_list[0]
    assert insert_call.args[1]["role"] == "secondary"


# ---------------------------------------------------------------------------
# remove_member
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_member_soft_deletes(service):
    get_db, session, _ = _mock_db_session()
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.remove_member(42)

    assert result == {"id": 42, "status": "removed"}
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_escalation_policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_escalation_policy_shapes_rows(service):
    rows = [
        (1, "Alice", "@alice", "a@x.com", "555", 5),
        (2, "Bob", "@bob", None, None, 15),
    ]
    get_db, _, _ = _mock_db_session(rows=rows)
    with patch("src.services.oncall_service.get_db", get_db):
        result = await service.get_escalation_policy("svc", "P1")

    assert len(result) == 2
    assert result[0]["level"] == 1
    assert result[0]["engineer"] == "Alice"
    assert result[0]["wait_time"] == 5
    assert result[1]["level"] == 2


@pytest.mark.asyncio
async def test_get_escalation_policy_empty_returns_empty_list(service):
    get_db, _, _ = _mock_db_session(rows=[])
    with patch("src.services.oncall_service.get_db", get_db):
        assert await service.get_escalation_policy("svc", "P0") == []


@pytest.mark.asyncio
async def test_get_escalation_policy_db_error_returns_empty(service):
    get_db, _, _ = _mock_db_session(execute_side_effect=RuntimeError("boom"))
    with patch("src.services.oncall_service.get_db", get_db):
        assert await service.get_escalation_policy("svc", "P1") == []
