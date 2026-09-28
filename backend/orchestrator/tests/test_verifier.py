"""
Tests for the Verifier interface and factory.

Scoped to the interface layer only. The Docker-based implementation
of HostedVerifier.verify() lands in the next commit and gets its own
test file (test_verifier_hosted.py) that mocks subprocess/docker.

These tests verify that:
  - VerificationResult is a dataclass with sane defaults
  - Verifier is abstract and cannot be instantiated directly
  - NoOpVerifier returns "disabled" without touching anything
  - get_verifier() selects correctly based on the feature flag
  - get_verifier(has_runner=True) raises, per the decision to fail
    at the selection point rather than returning an unimplemented stub
  - HostedVerifier.verify raises NotImplementedError until commit 5
    fills it in — documents the current scope, doesn't hide it
"""
import pytest

from src.agents.verifier import (
    HostedVerifier,
    NoOpVerifier,
    VerificationResult,
    Verifier,
    get_verifier,
)


# ---------------------------------------------------------------------------
# VerificationResult dataclass
# ---------------------------------------------------------------------------

def test_verification_result_defaults():
    result = VerificationResult(passed=True, reason="tests_passed")
    assert result.output == ""
    assert result.duration_ms == 0
    assert result.attempts == []
    assert result.verifier == ""


def test_verification_result_attempts_list_isolated():
    """
    Each VerificationResult gets its own attempts list. Shared mutable
    default would leak attempts between unrelated results.
    """
    a = VerificationResult(passed=True, reason="tests_passed")
    b = VerificationResult(passed=False, reason="tests_failed")
    a.attempts.append({"attempt": 1, "passed": True, "output": "x"})
    assert b.attempts == []


def test_verification_result_full_shape():
    result = VerificationResult(
        passed=False,
        reason="tests_failed",
        output="1 failed, 2 passed",
        duration_ms=4200,
        attempts=[
            {"attempt": 1, "passed": False, "output": "1 failed"},
            {"attempt": 2, "passed": False, "output": "1 failed"},
        ],
        verifier="hosted",
    )
    assert result.passed is False
    assert result.reason == "tests_failed"
    assert len(result.attempts) == 2
    assert result.verifier == "hosted"


# ---------------------------------------------------------------------------
# Verifier is abstract
# ---------------------------------------------------------------------------

def test_verifier_is_abstract():
    with pytest.raises(TypeError):
        Verifier()


# ---------------------------------------------------------------------------
# NoOpVerifier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_noop_verifier_returns_disabled():
    v = NoOpVerifier()
    result = await v.verify(
        repo_name="owner/repo",
        commit_sha="HEAD",
        diff="--- a\n+++ b\n",
        language="Python",
    )
    assert result.passed is True
    assert result.reason == "disabled"
    assert result.verifier == "disabled"
    assert result.output == ""
    assert result.attempts == []


@pytest.mark.asyncio
async def test_noop_verifier_ignores_context():
    """Passing context must not change NoOpVerifier's behavior."""
    v = NoOpVerifier()
    result = await v.verify(
        repo_name="owner/repo",
        commit_sha="HEAD",
        diff="d",
        language="Python",
        context={"anything": "here"},
    )
    assert result.reason == "disabled"


# ---------------------------------------------------------------------------
# get_verifier factory
# ---------------------------------------------------------------------------

def test_get_verifier_disabled_by_default():
    """Default settings have VERIFY_BEFORE_REPORT=False."""
    from src.config import settings
    assert settings.VERIFY_BEFORE_REPORT is False
    v = get_verifier()
    assert isinstance(v, NoOpVerifier)


def test_get_verifier_hosted_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "src.agents.verifier.settings.VERIFY_BEFORE_REPORT", True
    )
    v = get_verifier()
    assert isinstance(v, HostedVerifier)


def test_get_verifier_runner_raises(monkeypatch):
    """
    has_runner=True must fail loudly. The runner implementation does
    not exist; returning a stub would recreate the pattern that has
    burned this project twice (repo_name="fastapi", autofix stub).
    """
    with pytest.raises(ValueError, match="runner"):
        get_verifier(has_runner=True)


def test_get_verifier_runner_raises_even_when_disabled():
    """
    has_runner=True is checked before the feature flag. A caller who
    explicitly asks for a runner gets a hard error regardless of
    VERIFY_BEFORE_REPORT, because the runner is a separate concept
    from "should we verify at all."
    """
    from src.config import settings
    assert settings.VERIFY_BEFORE_REPORT is False
    with pytest.raises(ValueError):
        get_verifier(has_runner=True)

