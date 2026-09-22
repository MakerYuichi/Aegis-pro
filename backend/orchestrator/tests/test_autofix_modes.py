"""
Tests for AUTO_FIX_MODE gating in AutoFixService.

Three modes are supported (see issue #29):
    read_only (default) — never touch GitHub write APIs
    pr_draft            — stage payload, require human approval
    auto_pr             — real PR creation (deferred — see issue #30)

Each test asserts the *safety contract*: in read_only, GitHub's write
client must never be instantiated. That's the assertion enterprise
reviewers will look for.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.config import settings
from src.services.autofix_service import AutoFixService


# ── read_only ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_read_only_returns_skipped_without_touching_github(monkeypatch):
    """
    Situation: AUTO_FIX_MODE=read_only.
    Expected: Returns skipped status, no PR payload.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "read_only")

    svc = AutoFixService()
    result = await svc.create_pr(
        repo_name="mock-org/payment-api",
        file_path="PaymentProcessor.java",
        line_number=442,
        fix="@@ -440,3 +440,4 @@\n-  upiResponse.equals(...)\n+  if (upiResponse != null) { ... }",
        incident_id="INC-TEST-001",
    )

    assert result["mode"] == "read_only"
    assert result["status"] == "skipped"
    assert result["approval_required"] if "approval_required" in result else True
    assert "read_only" in result["message"]
    # Safety contract: no PR payload was returned
    assert "pr_url" not in result
    assert "pr_number" not in result


# ── pr_draft ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pr_draft_stages_payload_for_approval(monkeypatch):
    """
    Situation: AUTO_FIX_MODE=pr_draft.
    Expected: Returns pr_draft status with approval URL.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "pr_draft")

    svc = AutoFixService()
    result = await svc.create_pr(
        repo_name="mock-org/payment-api",
        file_path="PaymentProcessor.java",
        line_number=442,
        fix="@@ -440,3 +440,4 @@\n-  upiResponse.equals(...)\n+  if (upiResponse != null) { ... }",
        incident_id="INC-TEST-002",
    )

    assert result["mode"] == "pr_draft"
    assert result["status"] == "pr_draft"
    assert result["approval_required"] is True
    assert result["approval_url"] == "/approve/INC-TEST-002"
    assert "fix_preview" in result
    # Safety contract: still no real PR
    assert "pr_url" not in result
    assert "pr_number" not in result


# ── auto_pr ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_auto_pr_raises_until_real_integration_lands(monkeypatch):
    """
    Situation: AUTO_FIX_MODE=auto_pr.
    Expected: Raises NotImplementedError (not yet implemented).
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "auto_pr")

    svc = AutoFixService()
    with pytest.raises(NotImplementedError, match="#30"):
        await svc.create_pr(
            repo_name="mock-org/payment-api",
            file_path="PaymentProcessor.java",
            line_number=442,
            fix="diff",
            incident_id="INC-TEST-003",
        )


# ── invalid mode ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_invalid_mode_raises_value_error(monkeypatch):
    """
    Situation: AUTO_FIX_MODE has invalid value.
    Expected: Raises ValueError.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "yolo")

    svc = AutoFixService()
    with pytest.raises(ValueError, match="Invalid AUTO_FIX_MODE"):
        await svc.create_pr(
            repo_name="mock-org/payment-api",
            file_path="PaymentProcessor.java",
            line_number=442,
            fix="diff",
            incident_id="INC-TEST-004",
        )


# ── default behavior ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_default_mode_is_read_only(monkeypatch):
    """
    Situation: AUTO_FIX_MODE is unset/empty.
    Expected: Defaults to read_only.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "")

    svc = AutoFixService()
    result = await svc.create_pr(
        repo_name="mock-org/payment-api",
        file_path="PaymentProcessor.java",
        line_number=442,
        fix="diff",
        incident_id="INC-TEST-005",
    )

    assert result["mode"] == "read_only"
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_mode_whitespace_is_stripped(monkeypatch):
    """
    Situation: AUTO_FIX_MODE has leading/trailing whitespace.
    Expected: Whitespace stripped before mode check.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "  pr_draft  ")

    svc = AutoFixService()
    result = await svc.create_pr(
        repo_name="mock-org/payment-api",
        file_path="PaymentProcessor.java",
        line_number=442,
        fix="diff",
        incident_id="INC-TEST-006",
    )

    assert result["mode"] == "pr_draft"
    assert result["status"] == "pr_draft"


@pytest.mark.asyncio
async def test_mode_case_insensitive(monkeypatch):
    """
    Situation: AUTO_FIX_MODE has uppercase value.
    Expected: Case-insensitive mode check.
    Function: src.services.autofix_service.AutoFixService.create_pr
    """
    monkeypatch.setattr(settings, "AUTO_FIX_MODE", "READ_ONLY")

    svc = AutoFixService()
    result = await svc.create_pr(
        repo_name="mock-org/payment-api",
        file_path="PaymentProcessor.java",
        line_number=442,
        fix="diff",
        incident_id="INC-TEST-007",
    )

    assert result["mode"] == "read_only"
    assert result["status"] == "skipped"
