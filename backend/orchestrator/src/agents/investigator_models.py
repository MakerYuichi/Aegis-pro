"""
Dataclasses for the Investigator agent.

Two modes, one shared loop:

    incident  — the classic case. A stack trace identifies a crash.
                The agent diagnoses the null source.
    scan      — a proactive finding. A pattern matcher flagged a
                shape. The agent decides whether it is a real defect.

The mode is a field on the run context, set at the entry point and
copied through by the pipeline. It is never inferred from data
shape — a scan run has both a stack_trace and a chain, so shape
alone cannot distinguish the two.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

# Incident mode
STATUS_DIAGNOSED = "diagnosed"
# Scan mode
STATUS_CONFIRMED = "confirmed"
# Shared
STATUS_REFUSED = "refused"
STATUS_TIMEOUT = "timeout"
STATUS_DECISION_FAILED = "decision_failed"
STATUS_ITERATION_LIMIT = "iteration_limit"

ALL_STATUSES = (
    STATUS_DIAGNOSED,
    STATUS_CONFIRMED,
    STATUS_REFUSED,
    STATUS_TIMEOUT,
    STATUS_DECISION_FAILED,
    STATUS_ITERATION_LIMIT,
)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

MODE_INCIDENT = "incident"
MODE_SCAN = "scan"

ALL_MODES = (MODE_INCIDENT, MODE_SCAN)


# ---------------------------------------------------------------------------
# Action vocabulary, split per mode
# ---------------------------------------------------------------------------

_TOOLS_BASE = frozenset({"read_file", "read_symbol", "search_codebase"})

# Incident mode
INCIDENT_TOOL_ACTIONS = _TOOLS_BASE
INCIDENT_END_ACTIONS = frozenset({"diagnose", "refuse"})

# Scan mode
SCAN_TOOL_ACTIONS = _TOOLS_BASE | frozenset({"read_chain", "probe"})
SCAN_END_ACTIONS = frozenset({"confirm", "refuse"})

# Back-compat aliases for imports that haven't migrated yet.
TOOL_ACTIONS = INCIDENT_TOOL_ACTIONS
END_ACTIONS = INCIDENT_END_ACTIONS
TERMINAL_ACTIONS = END_ACTIONS  # deprecated name; use END_ACTIONS
VALID_ACTIONS = INCIDENT_TOOL_ACTIONS | INCIDENT_END_ACTIONS


def valid_actions(mode: str) -> frozenset:
    """The full action vocabulary for a mode. Used by the parser."""
    if mode == MODE_SCAN:
        return SCAN_TOOL_ACTIONS | SCAN_END_ACTIONS
    return INCIDENT_TOOL_ACTIONS | INCIDENT_END_ACTIONS


def end_actions(mode: str) -> frozenset:
    """The terminal actions for a mode."""
    if mode == MODE_SCAN:
        return SCAN_END_ACTIONS
    return INCIDENT_END_ACTIONS


def tool_actions(mode: str) -> frozenset:
    """The tool actions for a mode."""
    if mode == MODE_SCAN:
        return SCAN_TOOL_ACTIONS
    return INCIDENT_TOOL_ACTIONS


# ---------------------------------------------------------------------------
# Refuse reasons — enumerated
# ---------------------------------------------------------------------------

REFUSE_FALSE_POSITIVE = "false_positive"
REFUSE_COULD_NOT_DETERMINE = "could_not_determine"

ALL_REFUSE_REASONS = (REFUSE_FALSE_POSITIVE, REFUSE_COULD_NOT_DETERMINE)


# ---------------------------------------------------------------------------
# Confirmation — how the finding was verified
# ---------------------------------------------------------------------------

CONFIRMATION_PROBE_REPRODUCED = "probe_reproduced"
CONFIRMATION_REASONED_ONLY = "reasoned_only"

ALL_CONFIRMATIONS = (
    CONFIRMATION_PROBE_REPRODUCED,
    CONFIRMATION_REASONED_ONLY,
)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class InvestigatorContext:
    """
    Everything the agent knows before its first turn.

    Constructed by the pipeline from the loose context dict. The
    agent never sees the raw dict — only this. That decoupling means
    the pipeline can add or rename context keys without touching
    the agent, as long as the translation keeps producing a valid
    InvestigatorContext.

    Fields shared by both modes:
        mode, service_name, message, repo, blame, related_prs,
        rag_context, fix_outcomes, blast_radius

    Incident-mode fields:
        stack_trace, exception_type, file_path, line_number

    Scan-mode fields:
        chain — list of {file, line, symbol, reason, terminal_kind,
                branch_id, snippet}, one per ChainLink in DFS order.
                The agent reads the whole chain before deciding.
    """
    # Run mode — set at the entry point, never inferred
    mode: str
    service_name: str
    message: str
    repo: str

    # Shared optional context
    blame: dict[str, Any] = field(default_factory=dict)
    related_prs: list[dict[str, Any]] = field(default_factory=list)
    rag_context: str = ""
    fix_outcomes: str = ""
    blast_radius: dict[str, Any] = field(default_factory=dict)

    # Incident-mode
    stack_trace: str | None = None
    exception_type: str | None = None
    file_path: str | None = None
    line_number: int | None = None

    # Scan-mode
    chain: list[dict[str, Any]] = field(default_factory=list)

    def to_prompt(self) -> str:
        """
        Render the context in a fixed order. The chain section is
        present only in scan mode; the stack-trace section only in
        incident mode. Everything else is present in both.
        """
        parts: list[str] = []

        parts.append(f"Mode: {self.mode}")
        parts.append(f"Service: {self.service_name}")
        parts.append(f"Message: {self.message}")

        if self.mode == MODE_SCAN:
            parts.append("")
            parts.append("## Chain")
            if self.chain:
                for i, link in enumerate(self.chain):
                    branch = link.get("branch_id", 0)
                    branch_note = (
                        "pre-branch" if branch == 0
                        else f"branch {branch}"
                    )
                    parts.append(
                        f"[{i}] {link.get('file', '?')}:{link.get('line', '?')}  "
                        f"symbol={link.get('symbol', '?')!r}  "
                        f"reason={link.get('reason', '?')}  "
                        f"terminal_kind={link.get('terminal_kind', 'Unknown')}  "
                        f"({branch_note})"
                    )
                    if link.get("snippet"):
                        parts.append(f"    {link['snippet'][:200]}")
            else:
                parts.append("(no chain provided)")

        if self.mode == MODE_INCIDENT:
            parts.append("")
            parts.append("## Stack trace")
            if self.stack_trace:
                parts.append(f"Exception: {self.exception_type or 'Unknown'}")
                parts.append(f"File: {self.file_path or 'unknown'}")
                parts.append(f"Line: {self.line_number or 'unknown'}")
                parts.append("Raw:")
                parts.append(self.stack_trace)
            else:
                parts.append("(no stack trace provided)")

        parts.append("")
        parts.append("## Blame")
        if self.blame:
            parts.append(
                f"Last modified by: {self.blame.get('author', 'unknown')}"
            )
            parts.append(
                f"Commit: {self.blame.get('commit_hash', 'unknown')}"
            )
            parts.append(
                f"Message: {self.blame.get('message', '')[:200]}"
            )
        else:
            parts.append("(no blame available)")

        parts.append("")
        parts.append("## Related PRs")
        if self.related_prs:
            for pr in self.related_prs[:5]:
                parts.append(
                    f"#{pr.get('number', '?')} {pr.get('title', '')[:120]}"
                )
                if pr.get("reason"):
                    parts.append(f"    reason: {pr['reason'][:200]}")
        else:
            parts.append("(no related PRs)")

        parts.append("")
        parts.append("## Blast radius")
        if self.blast_radius:
            parts.append(
                f"Affected: {', '.join(self.blast_radius.get('affected', []))}"
            )
            parts.append(f"Count: {self.blast_radius.get('count', 0)}")
        else:
            parts.append("(no blast radius computed)")

        if self.rag_context:
            parts.append("")
            parts.append("## Similar past incidents")
            parts.append(self.rag_context)

        if self.fix_outcomes:
            parts.append("")
            parts.append("## Past fix outcomes for this service")
            parts.append(self.fix_outcomes)

        return "\n".join(parts)


@dataclass
class InvestigatorAction:
    """
    One parsed turn from the LLM.

    For tool actions, `args` carries the tool's parameters.
    For end actions:
        diagnose  → null_source, evidence, confidence
        confirm   → failure_mode, fix_location, evidence, confidence,
                    confirmation
        refuse    → reason (false_positive|could_not_determine),
                    candidates_considered

    The parser guarantees:
        - action in valid_actions(mode)
        - thought truncated to THOUGHT_MAX_CHARS
        - args is a dict
        - confidence clamped to [0, 1]
    """
    action: str
    thought: str
    args: dict[str, Any] = field(default_factory=dict)
    mode: str = MODE_INCIDENT

    @property
    def is_end(self) -> bool:
        return self.action in end_actions(self.mode)

    @property
    def is_tool(self) -> bool:
        return self.action in tool_actions(self.mode)

    # Back-compat for callers using the old name.
    @property
    def is_terminal(self) -> bool:
        return self.is_end


@dataclass
class InvestigationResult:
    """
    The agent's end output.

    `status` is one of the STATUS_* constants. Incident mode produces
    "diagnosed"; scan mode produces "confirmed". The rest are honest
    declarations of what the agent could not do.

    Fields, by status:

      diagnosed (incident):
          null_source, evidence, confidence

      confirmed (scan):
          failure_mode, fix_location, evidence, confidence,
          confirmation

      refused:
          reason (enumerated), candidates_considered

      timeout / decision_failed / iteration_limit:
          (history only)

    `history` is the tool observations in order. Always populated.
    """
    status: str

    # Incident mode
    null_source: str | None = None

    # Scan mode
    failure_mode: str | None = None
    fix_location: str | None = None
    confirmation: str | None = None

    # Shared
    evidence: str = ""
    confidence: float = 0.0
    reason: str | None = None
    candidates_considered: list[str] = field(default_factory=list)

    # Meta
    thought: str = ""
    iterations: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in extra_metadata.investigation."""
        return {
            "status": self.status,
            "null_source": self.null_source,
            "failure_mode": self.failure_mode,
            "fix_location": self.fix_location,
            "confirmation": self.confirmation,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "reason": self.reason,
            "candidates_considered": self.candidates_considered,
            "thought": self.thought,
            "iterations": self.iterations,
            "history": self.history,
        }

    @property
    def is_success(self) -> bool:
        return self.status in (STATUS_DIAGNOSED, STATUS_CONFIRMED)
