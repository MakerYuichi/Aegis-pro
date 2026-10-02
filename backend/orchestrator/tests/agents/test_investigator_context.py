"""
Tests for build_investigator_context — the boundary between the
pipeline's loose context dict and the agent's normalized shape.
"""
import pytest

from src.agents.investigator_context import build_investigator_context


def _baseline(**overrides):
    base = dict(
        service_name="payment-api",
        message="NullPointerException in charge handler",
        repo="payment-service",
        stack_trace="java.lang.NullPointerException\n    at Charge.java:42",
        stack_analysis={
            "exception_type": "NullPointerException",
            "file_path": "Charge.java",
            "line_number": 42,
        },
        github_context=None,
        related_prs=None,
        rag_context="",
        fix_outcomes="",
        blast_radius={"root": "payment-api", "affected": ["payment-api"], "count": 1},
    )
    base.update(overrides)
    return base


def test_baseline_produces_context():
    ctx = build_investigator_context(**_baseline())
    assert ctx.service_name == "payment-api"
    assert ctx.exception_type == "NullPointerException"
    assert ctx.file_path == "Charge.java"
    assert ctx.line_number == 42
    assert ctx.repo == "payment-service"


def test_missing_repo_falls_back_to_service_name():
    ctx = build_investigator_context(**_baseline(repo=None))
    assert ctx.repo == "payment-api"


def test_empty_stack_analysis_does_not_raise():
    ctx = build_investigator_context(**_baseline(stack_analysis=None))
    assert ctx.exception_type is None
    assert ctx.line_number is None


def test_line_number_coerced_from_string():
    ctx = build_investigator_context(
        **_baseline(stack_analysis={
            "exception_type": "NullPointerException",
            "file_path": "Charge.java",
            "line_number": "42",
        })
    )
    assert ctx.line_number == 42


def test_code_window_is_always_empty():
    """
    Load-bearing: the agent gets an empty window so its first turn is
    a tool call that reads what it decides it needs. If this test
    ever starts failing because someone added a window, that's the
    anchoring bug coming back.
    """
    ctx = build_investigator_context(**_baseline())
    assert ctx.code_window == {}


def test_blame_passed_through():
    ctx = build_investigator_context(
        **_baseline(github_context={"blame": {"author": "a@b.c"}})
    )
    assert ctx.blame == {"author": "a@b.c"}


def test_related_prs_default_empty():
    ctx = build_investigator_context(**_baseline(related_prs=None))
    assert ctx.related_prs == []


def test_to_prompt_renders_all_sections():
    ctx = build_investigator_context(**_baseline(
        rag_context="past incident summary",
        fix_outcomes="prior fix example",
    ))
    prompt = ctx.to_prompt()
    assert "## Stack trace" in prompt
    assert "## Code around the failing line" in prompt
    assert "(no code window available)" in prompt
    assert "## Blame" in prompt
    assert "## Related PRs" in prompt
    assert "## Blast radius" in prompt
    assert "## Similar past incidents" in prompt
    assert "## Past fix outcomes" in prompt
