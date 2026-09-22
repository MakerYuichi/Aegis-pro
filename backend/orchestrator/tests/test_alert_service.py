"""
Tests for AlertService.

Covers the untested surface of src/services/alert_service.py:
  - _engineer_list (pure)
  - send_alerts fan-out and the no-recipients fallback to #incidents
  - alert_person success/failure + DB recording
  - alert_everyone dedup
  - get_alert_history shape + error path
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
# _engineer_list
# ---------------------------------------------------------------------------

def test_engineer_list_empty_when_none(service):
    assert service._engineer_list(None) == []


def test_engineer_list_empty_when_error(service):
    assert service._engineer_list({"error": "not found"}) == []


def test_engineer_list_includes_roles(service):
    result = service._engineer_list(_on_call())
    assert [p["role"] for p in result] == ["primary", "secondary"]
    assert result[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# send_alerts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_alerts_pages_each_recipient(service):
    incident = {"incident_id": "INC-1", "title": "DB down",
                "severity": "P0", "service_name": "payments"}

    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db in this test")
        result = await service.send_alerts(incident, _on_call())

    assert result["status"] == "sent"
    assert set(result["recipients"]) == {"@alice", "@bob"}
    assert service._slack_mock.send_message.await_count == 2


@pytest.mark.asyncio
async def test_send_alerts_falls_back_to_incidents_channel(service):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}

    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db")
        result = await service.send_alerts(incident, on_call=None)

    assert result["status"] == "sent"
    assert result["recipients"] == []
    # One send to #incidents
    assert service._slack_mock.send_message.await_count == 1
    call_payload = service._slack_mock.send_message.await_args.args[0]
    assert call_payload["channel"] == "#incidents"


@pytest.mark.asyncio
async def test_send_alerts_uses_escalation_when_no_oncall(service):
    incident = {"incident_id": "INC-1", "severity": "P1", "service_name": "svc"}
    escalation = [{"engineer": "Carol", "slack": "@carol", "level": 1}]

    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db")
        result = await service.send_alerts(incident, on_call=None, escalation=escalation)

    assert result["recipients"] == ["@carol"]
    assert service._slack_mock.send_message.await_count == 1


# ---------------------------------------------------------------------------
# alert_person
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_person_success_records_history(service):
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def get_db():
        return session

    with patch("src.services.alert_service.get_db", get_db):
        result = await service.alert_person("@alice", "hello", incident_id="INC-1")

    assert result["status"] == "sent"
    assert result["target"] == "@alice"
    assert result["incident_id"] == "INC-1"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_alert_person_failure_reports_failed(service):
    service._slack_mock.send_message = AsyncMock(return_value=False)

    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db")
        result = await service.alert_person("@alice", "hello")

    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_alert_person_db_failure_does_not_raise(service):
    with patch("src.services.alert_service.get_db") as get_db:
        get_db.side_effect = RuntimeError("db down")
        result = await service.alert_person("@alice", "hello")

    # Alert still reports sent; DB failure is logged, not raised
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_alert_person_mock_flag_reflects_slack_enabled(service):
    service._slack_mock.enabled = False
    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db")
        result = await service.alert_person("@alice", "hello")
    assert result["mock"] is True


# ---------------------------------------------------------------------------
# alert_everyone
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_everyone_dedupes_by_handle(service):
    service._oncall_mock.list_roster = AsyncMock(return_value=[
        {"name": "Alice", "slack_handle": "@alice"},
        {"name": "Alice (dup)", "slack_handle": "@alice"},
        {"name": "Bob", "slack_handle": "@bob"},
    ])

    with patch("src.services.alert_service.get_db") as _unused:
        _unused.side_effect = RuntimeError("no db")
        result = await service.alert_everyone("all hands")

    assert result["count"] == 2
    assert set(result["targets"]) == {"@alice", "@bob"}


# ---------------------------------------------------------------------------
# get_alert_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_alert_history_shapes_rows(service):
    from datetime import datetime, timezone
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [(1, "@alice", "svc", "msg", "sent", ts)]

    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def get_db():
        return session

    with patch("src.services.alert_service.get_db", get_db):
        history = await service.get_alert_history(limit=10)

    assert history == [{
        "id": 1, "engineer": "@alice", "service": "svc",
        "message": "msg", "status": "sent", "timestamp": ts.isoformat(),
    }]


@pytest.mark.asyncio
async def test_get_alert_history_db_error_returns_empty(service):
    with patch("src.services.alert_service.get_db") as get_db:
        get_db.side_effect = RuntimeError("db down")
        assert await service.get_alert_history() == []
