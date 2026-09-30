"""
Tests for the Verifier's output reaching the Communicator and the
public response.

Before this change, extra_metadata.verification was written but never
surfaced to the caller — a human approving a fix from Slack or the
dashboard couldn't tell whether it passed tests. These tests pin the
three places it now appears:

  1. _build_response includes a verification block
  2. _stage_communicator's WebSocket broadcast includes it
  3. build_incident_blocks renders it as a Slack context block
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.incident_service import IncidentService


def _svc():
    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.get_rag_service"):
        return IncidentService()


def _context(**overrides):
    base = {
        "incident_id": "INC-TEST-1",
        "service_name": "payment-api",
        "service": {"name": "payment-api", "on_call": ["@marcus"]},
        "analysis": {
            "severity": "P1", "title": "t", "root_cause": "r",
            "suggested_fix": "f", "rollback_command": "k",
            "confidence": 0.8,
        },
        "blast_radius": {"affected": ["payment-api"], "count": 1,
                         "severity": "MEDIUM"},
        "rag_used": False,
        "auto_fix": {
            "status": "fix_generated",
            "fix": "--- a\n+++ b",
            "repo_name": "payment-service",
            "requires_approval": True,
        },
        "verification": {
            "passed": True,
            "reason": "tests_passed",
            "verifier": "hosted",
            "duration_ms": 1200,
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _build_response
# ---------------------------------------------------------------------------

def test_build_response_includes_verification():
    svc = _svc()
    response = svc._build_response(_context())
    assert "verification" in response
    assert response["verification"]["passed"] is True
    assert response["verification"]["reason"] == "tests_passed"
    assert response["verification"]["verifier"] == "hosted"


def test_build_response_includes_auto_fix():
    svc = _svc()
    response = svc._build_response(_context())
    assert "auto_fix" in response
    assert response["auto_fix"]["diff"] == "--- a\n+++ b"
    assert response["auto_fix"]["repo_name"] == "payment-service"
    assert response["auto_fix"]["requires_approval"] is True


def test_build_response_omits_verification_when_absent():
    svc = _svc()
    ctx = _context()
    del ctx["verification"]
    response = svc._build_response(ctx)
    assert "verification" not in response


def test_build_response_omits_auto_fix_when_absent():
    svc = _svc()
    ctx = _context(auto_fix={})
    response = svc._build_response(ctx)
    assert "auto_fix" not in response


# ---------------------------------------------------------------------------
# _stage_communicator — WebSocket broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_communicator_broadcast_includes_verification():
    svc = _svc()
    captured = {}

    async def fake_broadcast(payload):
        captured.update(payload)

    with patch("src.services.incident_service.manager") as ws, \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s:
        ws.broadcast = AsyncMock(side_effect=fake_broadcast)
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")

        await svc._stage_communicator(_context())

    assert captured["type"] == "new_incident"
    assert captured["data"]["verification"]["passed"] is True
    assert captured["data"]["verification"]["reason"] == "tests_passed"


@pytest.mark.asyncio
async def test_communicator_broadcast_omits_verification_when_absent():
    svc = _svc()
    captured = {}

    async def fake_broadcast(payload):
        captured.update(payload)

    with patch("src.services.incident_service.manager") as ws, \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s:
        ws.broadcast = AsyncMock(side_effect=fake_broadcast)
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")

        ctx = _context()
        del ctx["verification"]
        await svc._stage_communicator(ctx)

    assert "verification" not in captured["data"]


# ---------------------------------------------------------------------------
# Slack block builder
# ---------------------------------------------------------------------------

def test_build_incident_blocks_shows_verification_passed():
    from src.api.slack import build_incident_blocks

    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
        "verification": {"passed": True, "reason": "tests_passed"},
    })

    # Find the context block containing the verification text
    rendered = str(blocks)
    assert "Verification" in rendered
    assert "passed" in rendered


def test_build_incident_blocks_shows_verification_failed():
    from src.api.slack import build_incident_blocks

    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
        "verification": {"passed": False, "reason": "tests_failed"},
    })

    rendered = str(blocks)
    assert "Verification" in rendered
    assert "failed" in rendered


def test_build_incident_blocks_omits_verification_when_absent():
    from src.api.slack import build_incident_blocks

    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
    })

    assert "Verification" not in str(blocks)

# ---------------------------------------------------------------------------
# Slack block builder — proposed diff
# ---------------------------------------------------------------------------

def test_build_incident_blocks_shows_proposed_diff():
    from src.api.slack import build_incident_blocks

    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
        "auto_fix": {
            "diff": "-return x.y();\n+if (x != null) return x.y();",
            "repo_name": "payment-service",
        },
    })

    rendered = str(blocks)
    assert "Proposed Fix" in rendered
    assert "if (x != null)" in rendered
    assert "payment-service" in rendered


def test_build_incident_blocks_truncates_long_diff():
    from src.api.slack import build_incident_blocks

    long_diff = "-" + "x" * 2000 + "\n+" + "y" * 2000
    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
        "auto_fix": {"diff": long_diff},
    })

    rendered = str(blocks)
    assert "x" * 601 not in rendered
    assert "…" in rendered


def test_build_incident_blocks_omits_diff_when_absent():
    from src.api.slack import build_incident_blocks

    blocks = build_incident_blocks({
        "incident_id": "INC-1",
        "service": "payment-api",
        "severity": "P1",
        "confidence": 0.85,
        "on_call": ["@marcus"],
        "root_cause": "r",
        "suggested_fix": "f",
        "rollback_command": "k",
    })

    assert "Proposed Fix" not in str(blocks)


def test_build_detail_blocks_shows_proposed_diff_from_metadata():
    from src.api.slack import build_detail_blocks

    blocks = build_detail_blocks({
        "incident_id": "INC-1",
        "service_name": "payment-api",
        "severity": "P1",
        "status": "active",
        "confidence_score": 0.85,
        "title": "t",
        "root_cause": "r",
        "suggested_fix": "f",
        "extra_metadata": {
            "auto_fix": {"fix": "-old\n+new"},
        },
    })

    rendered = str(blocks)
    assert "Proposed Fix" in rendered
    assert "+new" in rendered


def test_build_response_preserves_all_verification_fields():
    """
    Regression guard: _build_response used to enumerate a fixed set
    of verification keys, silently dropping any field not in that
    set. `attempts` was the field that exposed it — the pipeline
    reported an empty attempts list even when the verifier had
    recorded attempts.

    Any field the stage returns must survive _build_response.
    """
    from unittest.mock import patch
    from src.services.incident_service import IncidentService

    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.get_rag_service"):
        svc = IncidentService()

    context = {
        "incident_id": "INC-TEST-1",
        "service_name": "payment-api",
        "service": {"name": "payment-api", "on_call": []},
        "analysis": {"severity": "P1", "title": "t", "root_cause": "r",
                     "suggested_fix": "f", "rollback_command": "k",
                     "confidence": 0.8},
        "blast_radius": {"affected": ["payment-api"], "count": 1,
                         "severity": "MEDIUM"},
        "verification": {
            "passed": False,
            "reason": "diff_does_not_apply",
            "verifier": "hosted",
            "duration_ms": 1234,
            "attempts": [
                {"attempt": 1, "passed": False, "output": "git apply failed"},
                {"attempt": 2, "passed": False, "output": "git apply failed"},
            ],
        },
    }

    response = svc._build_response(context)

    assert response["verification"]["attempts"] == context["verification"]["attempts"]
    assert response["verification"]["duration_ms"] == 1234
    assert response["verification"]["passed"] is False
    assert response["verification"]["reason"] == "diff_does_not_apply"
    assert response["verification"]["verifier"] == "hosted"
    
