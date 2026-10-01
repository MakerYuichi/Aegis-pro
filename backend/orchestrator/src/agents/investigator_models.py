"""
Dataclasses for the Investigator agent.

Three types:

    InvestigatorContext  — the input bundle the pipeline hands in. A
                           normalized view over the loose context dict
                           that declare_incident accumulates. Has
                           .to_prompt() so the decision prompt is
                           rendered in one place.

    InvestigatorAction   — the parsed output of one LLM turn. Either a
                           tool call (read_file / read_symbol /
                           search_codebase) or a terminal action
                           (diagnose / refuse).

    InvestigationResult  — the agent's terminal output. Five possible
                           statuses; only "diagnosed" carries a
                           null_source.

Design notes:

- InvestigatorAction.args is always a dict, even for single-argument
  tools. One shape, one parser.

- InvestigationResult.status has five values, and every one is honest:
  diagnosed / refused / timeout / decision_failed / iteration_limit.
  Only "diagnosed" is a success. The other four go to the Fixer as
  "skip auto-fix, report to human."

- InvestigatorContext.to_prompt() renders the input in a fixed order
  so the prompt is reproducible and diffable in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# The five terminal statuses. Exported so callers don't string-compare
# against typos.
STATUS_DIAGNOSED = "diagnosed"
STATUS_REFUSED = "refused"
STATUS_TIMEOUT = "timeout"
STATUS_DECISION_FAILED = "decision_failed"
STATUS_ITERATION_LIMIT = "iteration_limit"

ALL_STATUSES = (
    STATUS_DIAGNOSED,
    STATUS_REFUSED,
    STATUS_TIMEOUT,
    STATUS_DECISION_FAILED,
    STATUS_ITERATION_LIMIT,
)


# The three tool actions, plus the two terminals. Anything else is an
# invalid action and the parser rejects it.
TOOL_ACTIONS = frozenset({"read_file", "read_symbol", "search_codebase"})
TERMINAL_ACTIONS = frozenset({"diagnose", "refuse"})
VALID_ACTIONS = TOOL_ACTIONS | TERMINAL_ACTIONS


@dataclass
class InvestigatorContext:
    """
    Everything the agent knows before its first turn.

    Constructed by the pipeline (`_stage_investigator`) from the loose
    context dict. The agent never sees the raw dict — only this. That
    decoupling means the pipeline can add or rename context keys
    without touching the agent, as long as the translation in
    _stage_investigator keeps producing a valid InvestigatorContext.

    Fields:
        service_name       — "payment-api"
        message            — the alert text or incident description
        repo               — "owner/repo" or an absolute path. The
                             agent passes this verbatim to the tools.
        stack_trace        — the raw stack trace string, or None
        exception_type     — "AttributeError", "NullPointerException", ...
        file_path          — the file named in the stack trace
        line_number        — the line number named in the stack trace
        code_window        — {start_line, end_line, snippet} — the
                             pre-fetched code around the failing line
        blame              — {author, message, commit_hash, ...} or {}
        related_prs        — list of {number, title, url, reason, ...}
        rag_context        — pre-rendered string from RAGService
        fix_outcomes       — pre-rendered string from Curator few-shot
        blast_radius       — {root, affected, count, severity}
    """
    service_name: str
    message: str
    repo: str
    stack_trace: str | None = None
    exception_type: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    code_window: dict[str, Any] = field(default_factory=dict)
    blame: dict[str, Any] = field(default_factory=dict)
    related_prs: list[dict[str, Any]] = field(default_factory=list)
    rag_context: str = ""
    fix_outcomes: str = ""
    blast_radius: dict[str, Any] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """
        Render the context in a fixed order. Every section is present
        even when empty, so the prompt shape is stable across
        incidents and diffable in tests.

        Sections, in order:
            1. Service + message
            2. Stack trace (exception_type / file / line)
            3. Code window (numbered, around the failing line)
            4. Blame
            5. Related PRs (numbered)
            6. Blast radius
            7. RAG context (pre-rendered)
            8. Fix outcomes (pre-rendered)
        """
        parts: list[str] = []

        parts.append(f"Service: {self.service_name}")
        parts.append(f"Message: {self.message}")

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
        parts.append("## Code around the failing line")
        if self.code_window:
            start = self.code_window.get("start_line")
            end = self.code_window.get("end_line")
            snippet = self.code_window.get("snippet") or ""
            if start and end:
                parts.append(f"Lines {start}–{end}:")
            parts.append(snippet or "(empty)")
        else:
            parts.append("(no code window available)")

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

    Always carries `thought`. Carries `args` (a dict) for tool actions.
    For terminals, `args` carries the terminal's fields (null_source,
    evidence, confidence for diagnose; reason, candidates_considered
    for refuse).

    The parser guarantees:
        - action in VALID_ACTIONS
        - thought truncated to 200 characters
        - args is a dict (never a bare value)
        - for diagnose: confidence defaults to 0.7 if missing
    """
    action: str
    thought: str
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.action in TERMINAL_ACTIONS

    @property
    def is_tool(self) -> bool:
        return self.action in TOOL_ACTIONS


@dataclass
class InvestigationResult:
    """
    The agent's terminal output.

    `status` is one of the five STATUS_* constants. Only "diagnosed"
    produces a fix; the other four are honest declarations of what the
    agent could not do.

    Fields only populated for the relevant status:
        diagnosed     → null_source, evidence, confidence
        refused       → reason, candidates_considered
        timeout       → (history only)
        decision_failed → (history only)
        iteration_limit → (history only)

    `history` is the list of tool observations, in order. It is always
    populated, regardless of status. It is the raw record of what the
    agent looked at, and it is what the admin panel displays in
    session replay.
    """
    status: str
    null_source: str | None = None
    evidence: str = ""
    confidence: float = 0.0
    reason: str | None = None
    candidates_considered: list[str] = field(default_factory=list)
    thought: str = ""
    iterations: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in extra_metadata.investigation."""
        return {
            "status": self.status,
            "null_source": self.null_source,
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
        return self.status == STATUS_DIAGNOSED
