"""
Tests for build_investigator_context — the boundary between the
pipeline's loose context dict and the agent's normalized shape.
"""
import pytest

from src.agents.investigator_context import build_investigator_context


def _baseline(**overrides):
    base = dict(
        mode="incident",
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


# test_code_window_is_always_empty was removed in the scan-mode PR.
#
# InvestigatorContext no longer has a code_window field. The
# "the agent doesn't get a pre-fetched window" invariant used to be
# checked at runtime — a test asserting the field was always empty.
# It's now enforced by the shape: there is no field to populate, so
# there is no way to accidentally anchor the agent to a pre-fetched
# line. The test was checking a property the type system now
# guarantees, which is strictly stronger.


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
    assert "Mode: incident" in prompt
    assert "## Stack trace" in prompt
    assert "## Blame" in prompt
    assert "## Related PRs" in prompt
    assert "## Blast radius" in prompt
    assert "## Similar past incidents" in prompt
    assert "## Past fix outcomes for this service" in prompt
    # The pre-fetched code window is deliberately absent. The agent's
    # first turn is a tool call that reads whatever it decides it
    # needs; a pre-fetched window would anchor it to the failing line.
    assert "## Code around the failing line" not in prompt
    assert "no code window available" not in prompt
