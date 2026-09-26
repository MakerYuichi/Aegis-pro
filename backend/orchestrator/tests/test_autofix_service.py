"""
Tests for AutoFixService.

Real-DB tests use fixtures from conftest.py (db_session, make_incident,
db_error). Pure functions (parse_metadata, is_pending) stay as-is.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

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


def test_is_pending_status_case_insensitive(service):
    assert service._is_pending({"status": "FIX_GENERATED"}) is True
    assert service._is_pending({"status": "APPROVED"}) is False


def test_is_pending_none_status_defaults_to_empty(service):
    assert service._is_pending({"status": None}) is False


# ---------------------------------------------------------------------------
# get_pending_fixes — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_fixes_returns_only_pending(service, make_incident):
    """
    Real DB: three incidents, only two have pending fixes.
    """
    await make_incident({
        "incident_id": "INC-AUTOFIX-1",
        "extra_metadata": json.dumps({"auto_fix": {"requires_approval": True, "fix": "diff1"}}),
    })
    await make_incident({
        "incident_id": "INC-AUTOFIX-2",
        "extra_metadata": json.dumps({"auto_fix": {"status": "approved"}}),
    })
    await make_incident({
        "incident_id": "INC-AUTOFIX-3",
        "extra_metadata": json.dumps({"auto_fix": {"status": "pr_draft", "pr": {"fix_preview": "diff3"}}}),
    })

    result = await service.get_pending_fixes()
    ids = {r["incident_id"] for r in result}
    assert "INC-AUTOFIX-1" in ids
    assert "INC-AUTOFIX-3" in ids
    assert "INC-AUTOFIX-2" not in ids


@pytest.mark.asyncio
async def test_get_pending_fixes_shapes_entry(service, make_incident):
    """Real DB: pending fix with all fields, verify shaping."""
    await make_incident({
        "incident_id": "INC-AUTOFIX-SHAPE",
        "title": "Payment failure",
        "severity": "P0",
        "extra_metadata": json.dumps({
            "auto_fix": {
                "requires_approval": True,
                "fix": "the-diff",
                "file_path": "src/x.py",
                "line_number": 42,
            }
        }),
    })

    result = await service.get_pending_fixes()
    entry = next(r for r in result if r["incident_id"] == "INC-AUTOFIX-SHAPE")
    assert entry["title"] == "Payment failure"
    assert entry["severity"] == "P0"
    assert entry["file_path"] == "src/x.py"
    assert entry["line_number"] == 42
    assert entry["diff"] == "the-diff"
    assert entry["requires_approval"] is True


@pytest.mark.asyncio
async def test_get_pending_fixes_empty_returns_empty_list(service, db_session):
    """Real DB: no pending fixes."""
    await db_session.execute(text("DELETE FROM incidents"))
    await db_session.flush()
    assert await service.get_pending_fixes() == []


@pytest.mark.asyncio
async def test_get_pending_fixes_db_error_returns_empty(service, db_error):
    """db_error forces DB failure. get_pending_fixes lets it propagate."""
    with pytest.raises(RuntimeError, match="forced DB error"):
        await service.get_pending_fixes()


@pytest.mark.asyncio
async def test_get_pending_fixes_uses_code_context_fallback(service, make_incident):
    """Real DB: fix missing file_path/line_number; code_context has them."""
    await make_incident({
        "incident_id": "INC-AUTOFIX-CTX",
        "extra_metadata": json.dumps({
            "auto_fix": {"fix": "diff", "status": "fix_generated"},
            "code_context": {"file_path": "src/y.py", "line_number": 99},
        }),
    })

    result = await service.get_pending_fixes()
    entry = next(r for r in result if r["incident_id"] == "INC-AUTOFIX-CTX")
    assert entry["file_path"] == "src/y.py"
    assert entry["line_number"] == 99


@pytest.mark.asyncio
async def test_get_pending_fixes_defaults_unknown(service, make_incident):
    """Real DB: fix missing file_path/line_number entirely; defaults apply."""
    await make_incident({
        "incident_id": "INC-AUTOFIX-DEF",
        "extra_metadata": json.dumps({"auto_fix": {"fix": "diff", "status": "fix_generated"}}),
    })

    result = await service.get_pending_fixes()
    entry = next(r for r in result if r["incident_id"] == "INC-AUTOFIX-DEF")
    assert entry["file_path"] == "unknown"
    assert entry["line_number"] == 0


# ---------------------------------------------------------------------------
# approve_fix — mocked IncidentService for the error paths,
# real DB for the happy paths.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_fix_missing_incident_returns_error(service):
    """IncidentService returns None; service returns error."""
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
async def test_approve_fix_pr_draft_marks_approved(service, make_incident, db_session, monkeypatch):
    """
    Real DB: pending fix in pr_draft mode. approve_fix writes back
    status=fix_approved and auto_fix.approved=True.
    """
    from src.services import autofix_service as mod
    monkeypatch.setattr(mod.settings, "AUTO_FIX_MODE", "pr_draft")

    await make_incident({
        "incident_id": "INC-APPROVE-DRAFT",
        "file_path": "src/x.py",
        "line_number": 10,
        "extra_metadata": json.dumps({
            "auto_fix": {"fix": "the-diff", "status": "fix_generated"}
        }),
    })

    result = await service.approve_fix("INC-APPROVE-DRAFT")
    assert result["status"] == "approved"
    assert result["auto_fix"]["status"] == "approved"
    assert result["auto_fix"]["approved"] is True
    assert result["auto_fix"]["requires_approval"] is False

    # Verify DB state
    row = (await db_session.execute(
        text("SELECT status, extra_metadata FROM incidents WHERE incident_id = :iid"),
        {"iid": "INC-APPROVE-DRAFT"},
    )).fetchone()
    assert row[0] == "fix_approved"
    meta = row[1] if isinstance(row[1], dict) else json.loads(row[1])
    assert meta["auto_fix"]["approved"] is True


@pytest.mark.asyncio
async def test_approve_fix_read_only_message_notes_disabled(service, make_incident, db_session, monkeypatch):
    """Real DB: pending fix in read_only mode; message notes PR disabled."""
    from src.services import autofix_service as mod
    monkeypatch.setattr(mod.settings, "AUTO_FIX_MODE", "read_only")

    await make_incident({
        "incident_id": "INC-APPROVE-RO",
        "extra_metadata": json.dumps({
            "auto_fix": {"fix": "x", "status": "fix_generated"}
        }),
    })

    result = await service.approve_fix("INC-APPROVE-RO")
    assert result["status"] == "approved"
    assert "read_only" in result["message"]


@pytest.mark.asyncio
async def test_approve_fix_exception_returns_error_dict(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(side_effect=RuntimeError("db down"))
        result = await service.approve_fix("INC-1")
    assert "error" in result
    assert "db down" in result["error"]


@pytest.mark.asyncio
async def test_approve_fix_missing_file_path_fallback(service, make_incident, db_session, monkeypatch):
    """
    Real DB: incident.file_path is None; auto_fix.file_path is set.
    approve_fix falls back to the auto_fix value.
    """
    from src.services import autofix_service as mod
    monkeypatch.setattr(mod.settings, "AUTO_FIX_MODE", "read_only")

    await make_incident({
        "incident_id": "INC-APPROVE-FALLBACK",
        "file_path": None,
        "line_number": None,
        "extra_metadata": json.dumps({
            "auto_fix": {"fix": "diff", "file_path": "src/y.py", "line_number": 99}
        }),
    })

    result = await service.approve_fix("INC-APPROVE-FALLBACK")
    assert result["status"] == "approved"


# ---------------------------------------------------------------------------
# reject_fix — same split
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
async def test_reject_fix_marks_rejected_with_reason(service, make_incident, db_session):
    """Real DB: reject with reason; verify state written."""
    await make_incident({
        "incident_id": "INC-REJECT-1",
        "status": "active",
        "extra_metadata": json.dumps({
            "auto_fix": {
                "fix": "x",
                "status": "fix_generated",
                "pr": {"approval_required": True},
            }
        }),
    })

    result = await service.reject_fix("INC-REJECT-1", reason="wrong approach")
    assert result["status"] == "rejected"
    af = result["auto_fix"]
    assert af["rejected"] is True
    assert af["rejection_reason"] == "wrong approach"
    assert af["status"] == "rejected"
    assert af["pr"]["status"] == "rejected"
    assert af["pr"]["approval_required"] is False

    row = (await db_session.execute(
        text("SELECT extra_metadata FROM incidents WHERE incident_id = :iid"),
        {"iid": "INC-REJECT-1"},
    )).fetchone()
    meta = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    assert meta["auto_fix"]["rejected"] is True


@pytest.mark.asyncio
async def test_reject_fix_defaults_reason_to_none(service, make_incident):
    await make_incident({
        "incident_id": "INC-REJECT-2",
        "status": "active",
        "extra_metadata": json.dumps({"auto_fix": {"fix": "x"}}),
    })

    result = await service.reject_fix("INC-REJECT-2")
    assert result["auto_fix"]["rejection_reason"] is None


@pytest.mark.asyncio
async def test_reject_fix_exception_returns_error(service):
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(side_effect=RuntimeError("db down"))
        result = await service.reject_fix("INC-1")
    assert "error" in result
