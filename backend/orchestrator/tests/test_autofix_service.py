"""
Tests for AutoFixService.

Coverage targets the untested surface of src/services/autofix_service.py:
  - _parse_metadata / _is_pending (pure functions, high leverage)
  - get_pending_fixes (DB read + filtering)
  - approve_fix / reject_fix (DB write + state transitions)
  - create_pr mode routing is covered in test_autofix_modes.py; not duplicated here.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.autofix_service import AutoFixService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    """AutoFixService with GitHub + LLM boundaries stubbed out."""
    with patch("src.services.autofix_service.get_github_service"), \
         patch("src.services.autofix_service.LLMService"):
        svc = AutoFixService()
    return svc


def _row(incident_id="INC-1", title="t", severity="P1", declared_at=None,
         metadata=None, status="active", service_name="svc"):
    """Build a tuple matching the SELECT in get_pending_fixes."""
    from datetime import datetime, timezone
    return (
        incident_id,
        title,
        severity,
        declared_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        json.dumps(metadata) if isinstance(metadata, dict) else metadata,
        status,
        service_name,
    )


def _mock_db_session(rows=None):
    """
    Build a get_db replacement that matches the real contract:

        session = await get_db()          # get_db() returns an awaitable
        async with session:               # the resolved object is an async CM
            await session.execute(...)

    Returns (get_db_callable, session_mock).
    """
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    # The object returned by awaiting get_db() must itself be an async CM.
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return session

    return _get_db, session


# ---------------------------------------------------------------------------
# _parse_metadata
# ---------------------------------------------------------------------------

def test_parse_metadata_none_returns_empty_dict(service):
    assert service._parse_metadata(None) == {}


def test_parse_metadata_empty_string_returns_empty_dict(service):
    assert service._parse_metadata("") == {}


def test_parse_metadata_valid_json_string_parses(service):
    assert service._parse_metadata('{"a": 1}') == {"a": 1}


def test_parse_metadata_invalid_json_returns_empty_dict(service):
    assert service._parse_metadata("{not json") == {}


def test_parse_metadata_dict_passthrough(service):
    d = {"auto_fix": {"status": "pending"}}
    assert service._parse_metadata(d) is d


# ---------------------------------------------------------------------------
# _is_pending
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("auto_fix,expected", [
    ({}, False),
    (None, False),
    ({"error": "boom"}, False),
    ({"status": "approved"}, False),
    ({"status": "rejected"}, False),
    ({"status": "pr_created"}, False),
    ({"approved": True}, False),
    ({"requires_approval": True}, True),
    ({"status": "fix_generated"}, True),
    ({"status": "pr_draft"}, True),
    ({"status": "pending"}, True),
    ({"pr": {"approval_required": True}}, True),
])
def test_is_pending(service, auto_fix, expected):
    assert service._is_pending(auto_fix) is expected


# ---------------------------------------------------------------------------
# get_pending_fixes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_fixes_returns_only_pending(service):
    rows = [
        _row("INC-1", metadata={"auto_fix": {"requires_approval": True, "fix": "diff1"}}),
        _row("INC-2", metadata={"auto_fix": {"status": "approved"}}),  # filtered
        _row("INC-3", metadata={"auto_fix": {"status": "pr_draft", "pr": {"fix_preview": "diff3"}}}),
    ]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.autofix_service.get_db", get_db):
        result = await service.get_pending_fixes()

    ids = [r["incident_id"] for r in result]
    assert ids == ["INC-1", "INC-3"]


@pytest.mark.asyncio
async def test_get_pending_fixes_shapes_entry(service):
    rows = [_row("INC-9", title="Payment failure", severity="P0",
                 metadata={"auto_fix": {"requires_approval": True, "fix": "the-diff",
                                        "file_path": "src/x.py", "line_number": 42}})]
    get_db, _ = _mock_db_session(rows=rows)
    with patch("src.services.autofix_service.get_db", get_db):
        result = await service.get_pending_fixes()

    entry = result[0]
    assert entry["incident_id"] == "INC-9"
    assert entry["title"] == "Payment failure"
    assert entry["severity"] == "P0"
    assert entry["file_path"] == "src/x.py"
    assert entry["line_number"] == 42
    assert entry["diff"] == "the-diff"
    assert entry["requires_approval"] is True


@pytest.mark.asyncio
async def test_get_pending_fixes_empty_returns_empty_list(service):
    get_db, _ = _mock_db_session(rows=[])
    with patch("src.services.autofix_service.get_db", get_db):
        assert await service.get_pending_fixes() == []


# ---------------------------------------------------------------------------
# approve_fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_fix_missing_incident_returns_error(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value=None)
        result = await service.approve_fix("INC-NOPE")
    assert result == {"error": "Incident not found"}


@pytest.mark.asyncio
async def test_approve_fix_no_auto_fix_returns_error(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": "INC-1",
            "extra_metadata": {},
        })
        result = await service.approve_fix("INC-1")
    assert result == {"error": "No fix found for this incident"}


@pytest.mark.asyncio
async def test_approve_fix_pr_draft_marks_approved(service):
    incident = {
        "incident_id": "INC-1",
        "file_path": "src/x.py",
        "line_number": 10,
        "extra_metadata": {"auto_fix": {"fix": "the-diff", "status": "fix_generated"}},
        "status": "active",
    }
    get_db, session = _mock_db_session(rows=[])

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch("src.services.autofix_service.get_db", get_db), \
         patch("src.services.autofix_service.settings") as cfg:
        cfg.AUTO_FIX_MODE = "pr_draft"
        IncSvc.return_value.get_incident = AsyncMock(return_value=incident)
        result = await service.approve_fix("INC-1")

    assert result["status"] == "approved"
    assert result["auto_fix"]["status"] == "approved"
    assert result["auto_fix"]["approved"] is True
    assert result["auto_fix"]["requires_approval"] is False
    assert "pr_draft" in result["message"] or "pending" in result["message"].lower()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_fix_read_only_message_notes_disabled(service):
    incident = {
        "incident_id": "INC-2",
        "extra_metadata": {"auto_fix": {"fix": "x", "status": "fix_generated"}},
        "status": "active",
    }
    get_db, _ = _mock_db_session(rows=[])

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch("src.services.autofix_service.get_db", get_db), \
         patch("src.services.autofix_service.settings") as cfg:
        cfg.AUTO_FIX_MODE = "read_only"
        IncSvc.return_value.get_incident = AsyncMock(return_value=incident)
        result = await service.approve_fix("INC-2")

    assert result["status"] == "approved"
    assert "read_only" in result["message"]


@pytest.mark.asyncio
async def test_approve_fix_exception_returns_error_dict(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(side_effect=RuntimeError("db down"))
        result = await service.approve_fix("INC-1")
    assert "error" in result
    assert "db down" in result["error"]


# ---------------------------------------------------------------------------
# reject_fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_fix_missing_incident_returns_error(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value=None)
        assert await service.reject_fix("INC-NOPE") == {"error": "Incident not found"}


@pytest.mark.asyncio
async def test_reject_fix_no_auto_fix_returns_error(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": "INC-1", "extra_metadata": {},
        })
        assert await service.reject_fix("INC-1") == {"error": "No fix found for this incident"}


@pytest.mark.asyncio
async def test_reject_fix_marks_rejected_with_reason(service):
    incident = {
        "incident_id": "INC-1",
        "status": "active",
        "extra_metadata": {"auto_fix": {"fix": "x", "status": "fix_generated",
                                        "pr": {"approval_required": True}}},
    }
    get_db, session = _mock_db_session(rows=[])

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch("src.services.autofix_service.get_db", get_db):
        IncSvc.return_value.get_incident = AsyncMock(return_value=incident)
        result = await service.reject_fix("INC-1", reason="wrong approach")

    assert result["status"] == "rejected"
    af = result["auto_fix"]
    assert af["rejected"] is True
    assert af["rejection_reason"] == "wrong approach"
    assert af["status"] == "rejected"
    assert af["pr"]["status"] == "rejected"
    assert af["pr"]["approval_required"] is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_fix_defaults_reason_to_none(service):
    incident = {
        "incident_id": "INC-1", "status": "active",
        "extra_metadata": {"auto_fix": {"fix": "x"}},
    }
    get_db, _ = _mock_db_session(rows=[])

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch("src.services.autofix_service.get_db", get_db):
        IncSvc.return_value.get_incident = AsyncMock(return_value=incident)
        result = await service.reject_fix("INC-1")

    assert result["auto_fix"]["rejection_reason"] is None
