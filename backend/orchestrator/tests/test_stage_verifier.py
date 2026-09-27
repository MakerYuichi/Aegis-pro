"""
Tests for _stage_verifier in isolation.

The stage is pure: given a context, it calls get_verifier() and
returns a structured verification dict. No DB, no coordinator, no
Communicator. This file pins that contract.

Feature-flag behavior and the get_verifier() selection logic are
covered in test_verifier.py. This file covers the *stage's* handling
of its inputs and the shape of what it returns.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.verifier import VerificationResult
from src.services.incident_service import IncidentService


def _svc():
    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.get_rag_service"):
        return IncidentService()


def _context(**overrides):
    base = {
        "incident_id": "INC-TEST-1",
        "service_name": "payment-api",
        "service": {"name": "payment-api", "repo_name": "payment-service"},
        "stack_analysis": {"file_path": "DBConnection.java", "line_number": 88},
        "auto_fix": {"status": "fix_generated", "fix": "--- a\n+++ b\n"},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_stage_verifier_no_diff_returns_no_diff():
    """No auto_fix.fix → no_diff without calling the verifier."""
    svc = _svc()
    ctx = _context(auto_fix=None)
    result = await svc._stage_verifier(ctx)
    assert result["verification"]["reason"] == "no_diff"
    assert result["verification"]["passed"] is False


@pytest.mark.asyncio
async def test_stage_verifier_no_auto_fix_key():
    """Absent auto_fix → same as no diff."""
    svc = _svc()
    ctx = _context()
    del ctx["auto_fix"]
    result = await svc._stage_verifier(ctx)
    assert result["verification"]["reason"] == "no_diff"


@pytest.mark.asyncio
async def test_stage_verifier_delegates_to_get_verifier():
    """When a diff is present, the stage asks get_verifier() and calls verify()."""
    svc = _svc()
    fake_verifier = MagicMock()
    fake_verifier.verify = AsyncMock(return_value=VerificationResult(
        passed=True,
        reason="tests_passed",
        output="3 passed",
        duration_ms=1200,
        attempts=[{"attempt": 1, "passed": True, "output": "3 passed"}],
        verifier="hosted",
    ))

    with patch("src.agents.verifier.get_verifier", return_value=fake_verifier):
        result = await svc._stage_verifier(_context())

    fake_verifier.verify.assert_awaited_once()
    call = fake_verifier.verify.await_args
    assert call.kwargs["diff"] == "--- a\n+++ b\n"
    assert call.kwargs["repo_name"] == "payment-service"
    assert result["verification"]["passed"] is True
    assert result["verification"]["reason"] == "tests_passed"
    assert result["verification"]["verifier"] == "hosted"


@pytest.mark.asyncio
async def test_stage_verifier_swallows_verifier_exception():
    """A raising verifier is caught, not propagated."""
    svc = _svc()
    fake_verifier = MagicMock()
    fake_verifier.verify = AsyncMock(side_effect=RuntimeError("docker unavailable"))

    with patch("src.agents.verifier.get_verifier", return_value=fake_verifier):
        result = await svc._stage_verifier(_context())

    assert result["verification"]["passed"] is False
    assert result["verification"]["reason"] == "verifier_exception"


@pytest.mark.asyncio
async def test_stage_verifier_infer_language_from_stack():
    """Language inference prefers stack-trace file extension."""
    svc = _svc()
    assert svc._infer_language({"file_path": "x.py"}, "any") == "Python"
    assert svc._infer_language({"file_path": "x.js"}, "any") == "Node"
    assert svc._infer_language({"file_path": "x.ts"}, "any") == "Node"


@pytest.mark.asyncio
async def test_stage_verifier_infer_language_from_repo_name():
    """Language inference falls back to repo-name hints."""
    svc = _svc()
    assert svc._infer_language({}, "py-worker") == "Python"
    assert svc._infer_language({}, "node-proxy") == "Node"
    assert svc._infer_language({}, "web-ts") == "Node"


@pytest.mark.asyncio
async def test_stage_verifier_infer_language_defaults_to_python():
    """Unrecognized inputs default to Python."""
    svc = _svc()
    assert svc._infer_language({}, "unrecognized-name") == "Python"
    assert svc._infer_language({}, "") == "Python"


@pytest.mark.asyncio
async def test_stage_verifier_noop_when_flag_disabled():
    """
    VERIFY_BEFORE_REPORT=false is the default. The real get_verifier()
    returns NoOpVerifier, whose result reason is "disabled". This test
    exercises the real path (not a mock) so the wiring is confirmed.
    """
    svc = _svc()
    # Default settings: VERIFY_BEFORE_REPORT=false
    result = await svc._stage_verifier(_context())
    assert result["verification"]["passed"] is True
    assert result["verification"]["reason"] == "disabled"
    assert result["verification"]["verifier"] == "disabled"
