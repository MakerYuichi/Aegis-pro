"""
Tests for the Fixer's confirmation gate.

The Investigator produces findings at three certainty levels:

    refused              — not a bug. Skip silently.
    confirmed+probe      — proven. Generate a fix.
    confirmed+reasoned   — suspicious but unproven. Do NOT fix.
                          Surface as an unverified finding.

These tests assert the gate holds for each case.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.incident_service import IncidentService


def _context(*, inv_status, inv_confirmation, extra=None):
    ctx = {
        "service": {"repo_name": "owner/repo"},
        "service_name": "svc",
        "stack_analysis": {
            "file_path": "src/foo.py",
            "line_number": 10,
            "exception_type": "AttributeError",
        },
        "analysis": {"root_cause": "x", "suggested_fix": "y"},
        "incident_id": "INC-TEST",
        "investigation": {
            "status": inv_status,
            "confirmation": inv_confirmation,
            "failure_mode": "AttributeError when x is None",
            "fix_location": "src/foo.py",
            "confidence": 0.82,
        },
    }
    if extra:
        ctx.update(extra)
    return ctx


@pytest.fixture
def svc():
    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.get_rag_service"):
        return IncidentService()


# ── confirmed + reasoned_only → unverified finding, no fix ────────

@pytest.mark.asyncio
async def test_reasoned_only_skips_fix_and_flags_unverified(svc):
    ctx = _context(inv_status="confirmed", inv_confirmation="reasoned_only")

    with patch(
        "src.services.incident_service.AutoFixService"
    ) as mock_autofix_cls:
        result = await svc._stage_fixer(ctx)

    mock_autofix_cls.assert_not_called()
    assert result["auto_fix_skipped_reason"] == "investigator_unverified"
    assert result["unverified_finding"]["confirmation"] == "reasoned_only"
    assert result["unverified_finding"]["failure_mode"] == (
        "AttributeError when x is None"
    )
    assert "auto_fix" not in result


@pytest.mark.asyncio
async def test_reasoned_only_does_not_emit_diff(svc):
    ctx = _context(inv_status="confirmed", inv_confirmation="reasoned_only")

    with patch(
        "src.services.incident_service.AutoFixService"
    ) as mock_autofix_cls:
        result = await svc._stage_fixer(ctx)

    assert "auto_fix" not in result
    mock_autofix_cls.assert_not_called()


# ── confirmed + probe_reproduced → normal fix path ────────────────

@pytest.mark.asyncio
async def test_probe_reproduced_generates_fix(svc):
    ctx = _context(inv_status="confirmed", inv_confirmation="probe_reproduced")

    mock_fix = {"fix": "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y", "repo_name": "owner/repo"}
    with patch(
        "src.services.incident_service.AutoFixService"
    ) as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.generate_fix = AsyncMock(return_value=mock_fix)
        with patch.object(
            svc, "_read_code_context_from_clone",
            return_value={"file_path": "src/foo.py", "line_number": 10,
                          "code_snippet": "x", "raw_snippet": "x"},
        ):
            result = await svc._stage_fixer(ctx)

    assert "unverified_finding" not in result
    assert result.get("auto_fix") == mock_fix


# ── confirmed + probe_reproduced_realigned → normal fix path ─────

@pytest.mark.asyncio
async def test_probe_reproduced_realigned_generates_fix(svc):
    ctx = _context(
        inv_status="confirmed", inv_confirmation="probe_reproduced_realigned"
    )
    mock_fix = {"fix": "diff", "repo_name": "owner/repo"}

    with patch(
        "src.services.incident_service.AutoFixService"
    ) as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.generate_fix = AsyncMock(return_value=mock_fix)
        with patch.object(
            svc, "_read_code_context_from_clone",
            return_value={"file_path": "src/foo.py", "line_number": 10,
                          "code_snippet": "x", "raw_snippet": "x"},
        ):
            result = await svc._stage_fixer(ctx)

    assert "unverified_finding" not in result
    assert result.get("auto_fix") == mock_fix


# ── confirmed + no confirmation field → defensive refusal ─────────

@pytest.mark.asyncio
async def test_confirmed_without_confirmation_field_is_unverified(svc):
    # A missing confirmation field is treated as unverified. The gate
    # does not have a separate branch for it; None falls into the
    # general "not a known-good confirmation" case.
    ctx = _context(inv_status="confirmed", inv_confirmation=None)

    with patch(
        "src.services.incident_service.AutoFixService"
    ) as mock_autofix_cls:
        result = await svc._stage_fixer(ctx)

    mock_autofix_cls.assert_not_called()
    assert result["auto_fix_skipped_reason"] == "investigator_unverified"
    assert result["unverified_finding"]["confirmation"] is None


# ── refused → silent skip (existing behavior preserved) ───────────

@pytest.mark.asyncio
async def test_refused_skips_silently(svc):
    ctx = _context(inv_status="refused", inv_confirmation=None)
    ctx["auto_fix_skipped_reason"] = "investigator_refused"

    result = await svc._stage_fixer(ctx)

    # Refused uses the existing skip_reason path.
    assert result == {}
    