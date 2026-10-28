"""
Translate the pipeline's loose context dict into InvestigatorContext.

The pipeline accumulates a context dict with a dozen keys of varying
shapes; the agent expects a normalized InvestigatorContext. If the
pipeline's dict changes shape, only this file changes.

Design notes:

- `mode` is copied from the pipeline context, never inferred. The
  pipeline sets it at the entry point (declare_incident sets
  "incident", scan_repo sets "scan"). Shape alone cannot distinguish
  the two modes — a scan run carries both a synthetic stack trace
  and a chain.

- No code window is passed in. The agent's first turn is a tool call
  that reads whatever it decides it needs.
"""
from __future__ import annotations

from typing import Any

from src.agents.investigator_models import (
    MODE_INCIDENT,
    InvestigatorContext,
)


def build_investigator_context(
    *,
    mode: str,
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
    chain: list[dict[str, Any]] | None = None,
    symbol: str = "",
    pyright_message: str = "",
) -> InvestigatorContext:
    """
    Build an InvestigatorContext from the pipeline's pieces.

    `mode` is required and is copied through unchanged. `chain` is
    only meaningful in scan mode; it is copied through verbatim and
    the prompt renders it only when mode == "scan".
    """
    stack_analysis = stack_analysis or {}
    github_context = github_context or {}
    blast_radius = blast_radius or {}

    return InvestigatorContext(
        mode=mode or MODE_INCIDENT,
        service_name=service_name or "unknown",
        message=message or "",
        repo=repo or service_name or "",
        blame=_extract_blame(github_context),
        related_prs=list(related_prs or []),
        rag_context=rag_context or "",
        fix_outcomes=fix_outcomes or "",
        blast_radius=blast_radius,
        stack_trace=stack_trace,
        exception_type=stack_analysis.get("exception_type"),
        file_path=stack_analysis.get("file_path"),
        line_number=_coerce_int(stack_analysis.get("line_number")),
        chain=list(chain or []),
        symbol=symbol or "",
        pyright_message=pyright_message or "",
    )


def _extract_blame(github_context: dict[str, Any]) -> dict[str, Any]:
    blame = github_context.get("blame")
    if isinstance(blame, dict):
        return blame
    return {}


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
