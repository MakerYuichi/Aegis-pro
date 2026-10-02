"""
Translate the pipeline's loose context dict into InvestigatorContext.

This module is the boundary between the pipeline and the agent. The
pipeline accumulates a context dict with a dozen keys of varying
shapes; the agent expects a normalized InvestigatorContext. If the
pipeline's dict changes shape, only this file changes.

Design notes:

- Every field on InvestigatorContext is populated from the pipeline
  context, or from a sensible default. The translation never raises
  for a missing key — a missing key becomes None or a default, and
  the agent handles the absence.

- No code window is passed in. The agent's first turn is a tool call
  that reads whatever it decides it needs. See
  docs/INVESTIGATOR_AGENT.md §9 for why: the whole point of the tools
  is to replace a fixed `context_lines=N` guess with an on-demand
  window sized by the agent's own reasoning. Passing a pre-fetched
  window would anchor the agent to the failing line before it has
  had a thought — the opposite of what the agent is for.
"""
from __future__ import annotations

from typing import Any

from src.agents.investigator_models import InvestigatorContext


def build_investigator_context(
    *,
    service_name: str,
    message: str,
    repo: str | None,
    stack_trace: str | None,
    stack_analysis: dict[str, Any] | None,
    github_context: dict[str, Any] | None,
    related_prs: list[dict[str, Any]] | None,
    rag_context: str,
    fix_outcomes: str,
    blast_radius: dict[str, Any] | None,
) -> InvestigatorContext:
    """
    Build an InvestigatorContext from the pipeline's pieces.

    Parameters match the pipeline's own names so the call site reads
    cleanly. `repo` falls back to `service_name` if empty, matching
    the Fixer and Verifier convention.

    No `code_context` parameter. The agent reads what it needs via
    its tools.
    """
    stack_analysis = stack_analysis or {}
    github_context = github_context or {}
    blast_radius = blast_radius or {}

    return InvestigatorContext(
        service_name=service_name or "unknown",
        message=message or "",
        repo=repo or service_name or "",
        stack_trace=stack_trace,
        exception_type=stack_analysis.get("exception_type"),
        file_path=stack_analysis.get("file_path"),
        line_number=_coerce_int(stack_analysis.get("line_number")),
        code_window={},  # always empty; the agent fetches its own
        blame=_extract_blame(github_context),
        related_prs=list(related_prs or []),
        rag_context=rag_context or "",
        fix_outcomes=fix_outcomes or "",
        blast_radius=blast_radius,
    )


def _extract_blame(github_context: dict[str, Any]) -> dict[str, Any]:
    """github_context["blame"] is already the shape we want. Pass through."""
    blame = github_context.get("blame")
    if isinstance(blame, dict):
        return blame
    return {}


def _coerce_int(value: Any) -> int | None:
    """Return int(value) if it parses, else None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
