"""
Tests for the Curator's prompt injection path.

Covers:
  - LLMService._build_prompt accepts and renders fix_outcomes_context
  - RAGService.format_outcomes_for_prompt renders approved/rejected
    outcomes with the right labels
  - _stage_investigator retrieves outcomes and passes them when the
    flag is on, skips when off, survives retrieval failure

No real DB or LLM needed for the prompt-shape tests. The stage-level
tests use mocks for the retrieval call.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.llm_service import LLMService  
from src.services.incident_service import IncidentService
from src.services.rag_service import RAGService


# ---------------------------------------------------------------------------
# LLMService._build_prompt
# ---------------------------------------------------------------------------

def _llm():
    with patch("src.services.llm_service.get_provider_chain"):
        return LLMService()


def test_build_prompt_without_outcomes_unchanged():
    """No fix_outcomes_context → prompt unchanged from the old shape."""
    llm = _llm()
    prompt = llm._build_prompt(
        "payment-api", "boom", {"file_path": "x.py", "line_number": 1},
        {"affected": ["payment-api"], "count": 1},
        "past incidents here",
    )
    assert "past incidents here" in prompt
    assert "FEW-SHOT" not in prompt


def test_build_prompt_includes_fix_outcomes():
    llm = _llm()
    prompt = llm._build_prompt(
        "payment-api", "boom", None, None, "",
        "=== FEW-SHOT EXAMPLES ===\n[APPROVED, tests passed]",
    )
    assert "FEW-SHOT EXAMPLES" in prompt
    assert "APPROVED, tests passed" in prompt


def test_build_prompt_with_both_contexts():
    """Both rag_context and fix_outcomes_context can appear together."""
    llm = _llm()
    prompt = llm._build_prompt(
        "svc", "msg", None, None,
        "similar incidents text",
        "few-shot text",
    )
    assert "similar incidents text" in prompt
    assert "few-shot text" in prompt
    # Order: rag_context before fix_outcomes
    assert prompt.index("similar incidents text") < prompt.index("few-shot text")


# ---------------------------------------------------------------------------
# RAGService.format_outcomes_for_prompt
# ---------------------------------------------------------------------------

def _rag():
    return RAGService.__new__(RAGService)


def test_format_empty_list_returns_empty_string():
    rag = _rag()
    assert rag.format_outcomes_for_prompt([]) == ""


def test_format_approved_verified():
    rag = _rag()
    out = rag.format_outcomes_for_prompt([
        {
            "human_decision": "approved",
            "verification_passed": True,
            "root_cause": "Null deref",
            "suggested_fix": "Add guard",
            "fix_diff": "--- a\n+++ b",
        },
    ])
    assert "APPROVED, tests passed" in out
    assert "Null deref" in out
    assert "Add guard" in out


def test_format_rejected_includes_reason():
    rag = _rag()
    out = rag.format_outcomes_for_prompt([
        {
            "human_decision": "rejected",
            "verification_passed": True,
            "root_cause": "Wrong root cause",
            "suggested_fix": "Tweak",
            "fix_diff": "--- a\n+++ b",
            "human_reason": "addresses symptom not cause",
        },
    ])
    assert "REJECTED by human" in out
    assert "avoid this pattern" in out
    assert "addresses symptom not cause" in out


def test_format_truncates_long_diff():
    rag = _rag()
    huge = "x" * 5000
    out = rag.format_outcomes_for_prompt([
        {"human_decision": "approved", "verification_passed": True,
         "fix_diff": huge},
    ])
    # The 500-char truncated diff should appear, not the full 5000
    assert "x" * 500 in out
    assert "x" * 501 not in out


# ---------------------------------------------------------------------------
# _stage_investigator wiring
# ---------------------------------------------------------------------------

def _svc():
    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.get_rag_service"):
        return IncidentService()


@pytest.mark.asyncio
async def test_stage_investigator_skips_when_flag_off(monkeypatch):
    svc = _svc()
    monkeypatch.setattr("src.services.incident_service.settings.CURATOR_FEW_SHOT", False)

    svc.rag.generate_context_prompt = AsyncMock(return_value="")
    svc.rag.search_similar_outcomes = AsyncMock(return_value=[])
    svc.llm.analyze_incident = AsyncMock(return_value={
        "severity": "P1", "title": "t", "root_cause": "r",
        "suggested_fix": "f", "rollback_command": "k", "confidence": 0.5,
    })

    with patch("src.services.incident_service.get_github_service"):
        await svc._stage_investigator({
            "service_name": "payment-api",
            "message": "boom",
            "service": {"repo_name": "payment-service"},
            "stack_analysis": None,
            "blast_radius": {"affected": ["payment-api"], "count": 1},
            "incident_id": "INC-1",
        })

    svc.rag.search_similar_outcomes.assert_not_awaited()
    kwargs = svc.llm.analyze_incident.await_args.kwargs
    assert kwargs["fix_outcomes_context"] == ""


@pytest.mark.asyncio
async def test_stage_investigator_injects_when_flag_on(monkeypatch):
    svc = _svc()
    monkeypatch.setattr("src.services.incident_service.settings.CURATOR_FEW_SHOT", True)
    monkeypatch.setattr("src.services.incident_service.settings.CURATOR_MAX_OUTCOMES", 3)

    svc.rag.generate_context_prompt = AsyncMock(return_value="")
    svc.rag.search_similar_outcomes = AsyncMock(return_value=[
        {"human_decision": "approved", "verification_passed": True,
         "root_cause": "rc", "suggested_fix": "sf", "fix_diff": "d"},
    ])
    svc.rag.format_outcomes_for_prompt = MagicMock(return_value="FORMATTED")
    svc.llm.analyze_incident = AsyncMock(return_value={
        "severity": "P1", "title": "t", "root_cause": "r",
        "suggested_fix": "f", "rollback_command": "k", "confidence": 0.5,
    })

    with patch("src.services.incident_service.get_github_service"):
        await svc._stage_investigator({
            "service_name": "payment-api",
            "message": "boom",
            "service": {"repo_name": "payment-service"},
            "stack_analysis": None,
            "blast_radius": {"affected": ["payment-api"], "count": 1},
            "incident_id": "INC-1",
        })

    svc.rag.search_similar_outcomes.assert_awaited_once()
    kwargs = svc.llm.analyze_incident.await_args.kwargs
    assert kwargs["fix_outcomes_context"] == "FORMATTED"


@pytest.mark.asyncio
async def test_stage_investigator_survives_retrieval_failure(monkeypatch):
    svc = _svc()
    monkeypatch.setattr("src.services.incident_service.settings.CURATOR_FEW_SHOT", True)

    svc.rag.generate_context_prompt = AsyncMock(return_value="")
    svc.rag.search_similar_outcomes = AsyncMock(side_effect=RuntimeError("db down"))
    svc.llm.analyze_incident = AsyncMock(return_value={
        "severity": "P1", "title": "t", "root_cause": "r",
        "suggested_fix": "f", "rollback_command": "k", "confidence": 0.5,
    })

    with patch("src.services.incident_service.get_github_service"):
        result = await svc._stage_investigator({
            "service_name": "payment-api",
            "message": "boom",
            "service": {"repo_name": "payment-service"},
            "stack_analysis": None,
            "blast_radius": {"affected": ["payment-api"], "count": 1},
            "incident_id": "INC-1",
        })

    # Stage returns successfully, but no outcomes injected
    kwargs = svc.llm.analyze_incident.await_args.kwargs
    assert kwargs["fix_outcomes_context"] == ""
    assert "analysis" in result
