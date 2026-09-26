"""
Tests for AlertService.

Real-DB tests use fixtures from conftest.py (db_session, seeded_alert_history,
db_error). Tests that don't care about the DB use db_error so that
alert_person's swallow-and-log path is exercised without a real DB.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from src.services.alert_service import AlertService


@pytest.fixture
def service():
    with patch("src.services.alert_service.get_slack_service") as slack_factory, \
         patch("src.services.alert_service.OnCallService") as oncall_cls:
        slack = MagicMock()
        slack.enabled = False
        slack.send_message = AsyncMock(return_value=True)
        slack_factory.return_value = slack
        svc = AlertService()
        svc._slack_mock = slack
        svc._oncall_mock = oncall_cls.return_value
    return svc


def _on_call():
    return {
        "primary": {"name": "Alice", "slack": "@alice"},
        "secondary": {"name": "Bob", "slack": "@bob"},
        "tertiary": None,
    }


# ---------------------------------------------------------------------------
# _engineer_list — unchanged (pure)
# ---------------------------------------------------------------------------

def test_engineer_list_empty_when_none(service):
    assert service._engineer_list(None) == []


def test_engineer_list_empty_when_error(service):
    assert service._engineer_list({"error": "not found"}) == []


def test_engineer_list_includes_roles(service):
    result = service._engineer_list(_on_call())
    assert [p["role"] for p in result] == ["primary", "secondary"]
    assert result[0]["name"] == "Alice"


def test_engineer_list_person_missing_slack(service):
    on_call = {"primary": {"name": "Alice"}, "secondary": None, "tertiary": None}
    result = service._engineer_list(on_call)
    assert len(result) == 1
    assert result[0].get("slack") is None


def test_engineer_list_person_missing_name(service):
    on_call = {"primary": {"slack": "@alice"}, "secondary": None, "tertiary": None}
    result = service._engineer_list(on_call)
    assert result[0]["slack"] == "@alice"
    assert result[0].get("name") is None


def test_engineer_list_empty_dict(service):
    assert service._engineer_list({}) == []


def test_engineer_list_unexpected_structure(service):
    on_call = {"primary": {"name": "Alice"}, "unexpected": {"name": "Bob"}}
    result = service._engineer_list(on_call)
    assert len(result) == 1
    assert result[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# send_alerts — dispatch logic only, DB is dead (db_error)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_alerts_pages_each_recipient(service, db_error):
    incident = {"incident_id": "INC-1", "title": "DB down",
                "severity": "P0", "service_name": "payments"}
    result = await service.send_alerts(incident, _on_call())
    assert result["status"] == "sent"
    assert set(result["recipients"]) == {"@alice", "@bob"}
    assert service._slack_mock.send_message.await_count == 2


@pytest.mark.asyncio
async def test_send_alerts_falls_back_to_incidents_channel(service, db_error):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}
    result = await service.send_alerts(incident, on_call=None)
    assert result["status"] == "sent"
    assert result["recipients"] == []
    assert service._slack_mock.send_message.await_count == 1
    call_payload = service._slack_mock.send_message.await_args.args[0]
    assert call_payload["channel"] == "#incidents"


@pytest.mark.asyncio
async def test_send_alerts_uses_escalation_when_no_oncall(service, db_error):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}
    escalation = [{"engineer": "Carol", "slack": "@carol", "level": 1}]
    result = await service.send_alerts(incident, on_call=None, escalation=escalation)
    assert result["recipients"] == ["@carol"]
    assert service._slack_mock.send_message.await_count == 1


@pytest.mark.asyncio
async def test_send_alerts_missing_fields(service, db_error):
    incident = {"incident_id": "INC-1"}
    result = await service.send_alerts(incident, on_call=None)
    assert result["status"] == "sent"
    assert service._slack_mock.send_message.await_count == 1


@pytest.mark.asyncio
async def test_send_alerts_escalation_missing_fields(service, db_error):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}
    escalation = [{"engineer": "Carol"}]
    result = await service.send_alerts(incident, on_call=None, escalation=escalation)
    assert result["recipients"] == ["Carol"]
    assert service._slack_mock.send_message.await_count == 1


@pytest.mark.asyncio
async def test_send_alerts_multiple_escalation_levels(service, db_error):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}
    escalation = [
        {"engineer": "Carol", "slack": "@carol", "level": 1},
        {"engineer": "Dave", "slack": "@dave", "level": 2},
    ]
    result = await service.send_alerts(incident, on_call=None, escalation=escalation)
    assert set(result["recipients"]) == {"@carol", "@dave"}
    assert service._slack_mock.send_message.await_count == 2


# ---------------------------------------------------------------------------
# alert_person — DB write is a side effect; use db_error for the ones that
# don't care about the write.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_person_success_records_history(service, db_session):
    """Real DB: alert_person inserts a row into alert_history."""
    await db_session.execute(text("DELETE FROM alert_history"))
    await db_session.flush()

    result = await service.alert_person("@alice", "hello", incident_id="INC-1")
    assert result["status"] == "sent"
    assert result["target"] == "@alice"
    assert result["incident_id"] == "INC-1"

    row = (await db_session.execute(
        text("""
            SELECT engineer_name, service_name, status
            FROM alert_history
            ORDER BY id DESC LIMIT 1
        """)
    )).fetchone()
    assert row is not None
    assert row[0] == "@alice"
    assert row[1] == "INC-1"
    assert row[2] == "sent"


@pytest.mark.asyncio
async def test_alert_person_failure_reports_failed(service, db_error):
    service._slack_mock.send_message = AsyncMock(return_value=False)
    result = await service.alert_person("@alice", "hello")
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_alert_person_db_failure_does_not_raise(service, db_error):
    """DB failure is swallowed by alert_person; result still reports sent."""
    result = await service.alert_person("@alice", "hello")
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_alert_person_mock_flag_reflects_slack_enabled(service, db_error):
    service._slack_mock.enabled = False
    result = await service.alert_person("@alice", "hello")
    assert result["mock"] is True


@pytest.mark.asyncio
async def test_alert_person_missing_slack_handle(service, db_error):
    result = await service.alert_person(None, "hello")
    assert result["target"] == "unknown"


@pytest.mark.asyncio
async def test_alert_person_long_message_truncated(service, db_session):
    """Real DB: alert_person truncates message to 500 chars in the DB write."""
    await db_session.execute(text("DELETE FROM alert_history"))
    await db_session.flush()

    long_msg = "x" * 1000
    await service.alert_person("@alice", long_msg, incident_id="INC-1")

    row = (await db_session.execute(
        text("SELECT message FROM alert_history ORDER BY id DESC LIMIT 1")
    )).fetchone()
    assert row is not None
    assert len(row[0]) == 500


@pytest.mark.asyncio
async def test_alert_person_missing_incident_id(service, db_session):
    """Real DB: incident_id=None writes 'unknown' to service_name."""
    await db_session.execute(text("DELETE FROM alert_history"))
    await db_session.flush()

    await service.alert_person("@alice", "hello", incident_id=None)

    row = (await db_session.execute(
        text("SELECT service_name FROM alert_history ORDER BY id DESC LIMIT 1")
    )).fetchone()
    assert row is not None
    assert row[0] == "unknown"


# ---------------------------------------------------------------------------
# alert_everyone — dispatch only, DB dead
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_everyone_dedupes_by_handle(service, db_error):
    service._oncall_mock.list_roster = AsyncMock(return_value=[
        {"name": "Alice", "slack_handle": "@alice"},
        {"name": "Alice (dup)", "slack_handle": "@alice"},
        {"name": "Bob", "slack_handle": "@bob"},
    ])
    result = await service.alert_everyone("all hands")
    assert result["count"] == 2
    assert set(result["targets"]) == {"@alice", "@bob"}


@pytest.mark.asyncio
async def test_alert_everyone_with_service_filter(service, db_error):
    service._oncall_mock.list_roster = AsyncMock(return_value=[
        {"name": "Alice", "slack_handle": "@alice"},
    ])
    result = await service.alert_everyone("alert", service_name="auth")
    service._oncall_mock.list_roster.assert_awaited_once_with("auth")
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_alert_everyone_empty_roster(service, db_error):
    service._oncall_mock.list_roster = AsyncMock(return_value=[])
    result = await service.alert_everyone("alert")
    assert result["count"] == 0
    assert result["targets"] == []


@pytest.mark.asyncio
async def test_alert_everyone_person_missing_slack_handle(service, db_error):
    service._oncall_mock.list_roster = AsyncMock(return_value=[
        {"name": "Alice", "slack_handle": None},
    ])
    result = await service.alert_everyone("alert")
    assert result["count"] == 1
    assert result["targets"] == ["Alice"]


# ---------------------------------------------------------------------------
# get_alert_history — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_alert_history_shapes_rows(service, seeded_alert_history, db_session):
    """Real DB: get_alert_history returns rows newest-first, shaped."""
    history = await service.get_alert_history(limit=10)
    assert len(history) == 3
    # Newest first
    assert history[0]["engineer"] == "@carol"
    assert history[1]["engineer"] == "@bob"
    assert history[2]["engineer"] == "@alice"
    # Shape
    for entry in history:
        assert set(entry.keys()) == {"id", "engineer", "service", "message", "status", "timestamp"}


@pytest.mark.asyncio
async def test_get_alert_history_db_error_returns_empty(service, db_error):
    """db_error forces DB failure; get_alert_history swallows and returns []."""
    assert await service.get_alert_history() == []


@pytest.mark.asyncio
async def test_get_alert_history_respects_limit(service, seeded_alert_history):
    """Real DB: limit parameter is honored."""
    history = await service.get_alert_history(limit=2)
    assert len(history) == 2


@pytest.mark.asyncio
async def test_get_alert_history_null_timestamp(service, db_session):
    """Real DB: row with NULL created_at returns timestamp=None."""
    await db_session.execute(text("DELETE FROM alert_history"))
    await db_session.execute(
        text("""
            INSERT INTO alert_history (engineer_name, service_name, message, status, created_at)
            VALUES ('@x', 'svc', 'msg', 'sent', NULL)
        """)
    )
    await db_session.flush()

    history = await service.get_alert_history(limit=10)
    assert len(history) == 1
    assert history[0]["timestamp"] is None


@pytest.mark.asyncio
async def test_get_alert_history_empty_result(service, db_session):
    """Real DB: no rows → empty list."""
    await db_session.execute(text("DELETE FROM alert_history"))
    await db_session.flush()
    assert await service.get_alert_history(limit=10) == []
