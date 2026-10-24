"""
Investigator agent — bounded, tool-using diagnosis for incident
declarations.

The loop:

    for iteration in 1..max_iterations:
        if time budget exceeded: return timeout
        action = await self._decide(context, history, iteration)
        if action is terminal: return the terminal result
        observation = await self._execute_tool(action)
        history.append(observation)
    return iteration_limit

Design constraints (from docs/INVESTIGATOR_AGENT.md):

- Hard cap: 5 iterations. Soft cap: 30 seconds. Both enforced in
  code, not trusted to the prompt.

- Structured JSON, not native tool-calling. No provider in the chain
  implements tools=/function_call= today. Reuses the same
  response_format="json_object" pattern that analyze_incident uses.

- `_decide` is the only non-deterministic method. Tests mock it.
  Everything else is a pure function of its inputs.

- Prompt instructions are requests. Code enforces. Specifically:
  the 200-char cap on `thought` is applied in the parser, not the
  prompt. The 0.7 confidence fallback is applied in the parser, not
  the prompt.
"""
from __future__ import annotations

import json
import ast
import re
import time
from typing import Any

from loguru import logger

from src.agents.investigator_models import (
    ALL_STATUSES,
    STATUS_CONFIRMED,
    STATUS_DECISION_FAILED,
    STATUS_DIAGNOSED,
    STATUS_ITERATION_LIMIT,
    STATUS_REFUSED,
    STATUS_TIMEOUT,
    STATUS_UNVERIFIED,
    CONFIRMATION_PROBE_REPRODUCED,
    CONFIRMATION_REASONED_ONLY,
    ALL_CONFIRMATIONS,
    MODE_INCIDENT,
    MODE_SCAN,
    REFUSE_FALSE_POSITIVE,
    REFUSE_COULD_NOT_DETERMINE,
    ALL_REFUSE_REASONS,
    InvestigationResult,
    InvestigatorAction,
    InvestigatorContext,
    end_actions,
    tool_actions,
    valid_actions,
)
from src.agents.tools.repo_tools import (
    ToolResult,
    read_file,
    read_symbol,
    search_codebase,
)
from src.agents.tools.read_chain import read_chain
from src.agents.tools.probe import probe
from src.agents.cpython_builtins import format_note


# Caps. Enforced here, not requested in the prompt.
THOUGHT_MAX_CHARS = 200
DEFAULT_CONFIDENCE = 0.7

# Loop defaults. Overridable at call time.
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_TIME_BUDGET_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Post-hoc diagnosis validation
# ---------------------------------------------------------------------------

# Refusal reasons. Two distinct outcomes, two distinct strings, so a
# human reading the persisted incident knows which one happened.
#
#   _NOT_OBSERVED   — the agent never read the crash line. There is
#                     no evidence to check the diagnosis against.
#                     Refuse by construction.
#   _NOT_IN_STMT    — the agent read the crash line, but the named
#                     symbol does not appear in the crash statement.
#                     The diagnosis is ungrounded.
#
# Both are refusals. The distinction matters for telemetry: if most
# refusals are _NOT_OBSERVED, the agent is failing to investigate the
# right window. If most are _NOT_IN_STMT, the agent is naming wrong
# symbols. The fixes are different.
REFUSAL_REASON_NOT_OBSERVED = "crash_line_not_observed"
REFUSAL_REASON_NOT_IN_STATEMENT = "null_source_not_in_crash_statement"


def _validate_diagnosis(
    result: InvestigationResult,
    history: list[dict[str, Any]],
    *,
    crash_file: str | None,
    crash_line: int | None,
) -> InvestigationResult:
    """
    Verify that a diagnosed symbol is grounded in the agent's own
    tool-call history.

    Two checks, in order:

    1. Did the agent actually read the crash line? Look through the
       history for a read_file / read_symbol observation whose window
       contains the crash line. If none exists, the diagnosis has no
       evidence to check against — refuse with
       reason=REFUSAL_REASON_NOT_OBSERVED.

    2. Is the diagnosed symbol present in the crash statement? Parse
       the observation's text, find the narrowest AST statement
       enclosing the crash line, and check whether the symbol appears
       as a Name or Attribute node anywhere within that statement. If
       not, refuse with reason=REFUSAL_REASON_NOT_IN_STATEMENT.

    Why the agent's history and not a fresh file read: the claim we
    are checking is "the agent's own reasoning supports this
    diagnosis," not "this diagnosis is true of the file right now."
    A fresh read could use a different line window than what the
    agent actually saw and we would validate against evidence the
    agent never had. Same discipline as realigning a diff against
    the observation's own text rather than trusting what the LLM
    claimed.

    Why AST and not a line window: a fixed ±N window either misses
    legitimate diagnoses whose symbol is an argument to the failing
    call, or accepts nearby-but-wrong symbols. The enclosing
    statement is the correct scope — it is what the crash line
    *is*, not a neighborhood around it.

    Returns the same result on success. Returns a refusal on either
    failure mode.
    """
    if result.status != STATUS_DIAGNOSED:
        return result

    symbol = (result.null_source or "").strip()
    if not symbol:
        # The parser rejects a diagnose without a null_source; this
        # is belt-and-suspenders.
        return _refuse(result, history, REFUSAL_REASON_NOT_IN_STATEMENT, [])

    if not crash_file or not crash_line:
        # No crash site to validate against. Cannot verify, so refuse.
        # Same honest degradation as everywhere else in the pipeline.
        return _refuse(result, history, REFUSAL_REASON_NOT_OBSERVED, [symbol])

    # Step 1: does any observation cover the crash line?
    obs = _find_observation_at_crash(history, crash_line)
    if obs is None:
        logger.warning(
            f"Investigator: no observation covers {crash_file}:{crash_line}; "
            f"diagnosis {symbol!r} cannot be validated"
        )
        return _refuse(result, history, REFUSAL_REASON_NOT_OBSERVED, [symbol])

    # Step 2: is the symbol present in the crash statement?
    if not _symbol_in_crash_statement(obs, crash_line, symbol):
        logger.warning(
            f"Investigator: diagnosis {symbol!r} does not appear in the "
            f"crash statement at {crash_file}:{crash_line}; "
            f"rejecting as ungrounded"
        )
        return _refuse(
            result, history, REFUSAL_REASON_NOT_IN_STATEMENT, [symbol]
        )

    return result


def _refuse(
    result: InvestigationResult,
    history: list[dict[str, Any]],
    reason: str,
    candidates: list[str],
) -> InvestigationResult:
    """Build a refusal that preserves the agent's audit trail.

    Applies the same reason→status mapping as _refuse_result: a
    refusal with reason=could_not_determine is not a verdict of
    "not a bug", it's an admission of undecidedness. Route it to
    STATUS_UNVERIFIED so downstream stages surface it under
    "Needs Review" rather than "Refused".
    """
    status = (
        STATUS_UNVERIFIED
        if reason == REFUSE_COULD_NOT_DETERMINE
        else STATUS_REFUSED
    )
    return InvestigationResult(
        status=status,
        reason=reason,
        candidates_considered=candidates,
        thought=result.thought,
        iterations=result.iterations,
        history=history,
    )
    
def _history_has_successful_probe(history: list[dict[str, Any]]) -> bool:
    """True when the history contains a probe that ran and reproduced."""
    for obs in history:
        if obs.get("tool") != "probe" or not obs.get("ok"):
            continue
        meta = obs.get("metadata") or {}
        if meta.get("ran") is True and meta.get("reproduced") is True:
            return True
    return False


def _validate_scan_confirmation(
    result: InvestigationResult,
    history: list[dict[str, Any]],
    *,
    chain: list[dict[str, Any]],
) -> InvestigationResult:
    if result.status != STATUS_CONFIRMED:
        return result

    chain_files = {link.get("file") for link in chain if link.get("file")}
    if chain_files and result.fix_location not in chain_files:
        logger.warning(
            f"Investigator: fix_location {result.fix_location!r} is not "
            f"in the chain ({sorted(chain_files)}); rejecting"
        )
        return _refuse(
            result, history, REFUSE_FALSE_POSITIVE,
            [result.fix_location or "<missing>"],
        )

    if result.confirmation == CONFIRMATION_PROBE_REPRODUCED:
        if not _history_has_successful_probe(history):
            logger.warning(
                "Investigator: probe_reproduced claimed without a "
                "successful probe observation; downgrading to "
                "reasoned_only"
            )
            result.confirmation = CONFIRMATION_REASONED_ONLY

    # NEW: reasoned_only confirmations must state why a probe was
    # not attempted. A finding that names a failure_mode but offers
    # no probe and no explanation is a guess dressed as a finding.
    if result.confirmation == CONFIRMATION_REASONED_ONLY:
        evidence = (result.evidence or "").lower()
        if not any(
            marker in evidence
            for marker in ("probe", "sandbox", "network", "external",
                           "cannot construct", "cannot reproduce",
                           "environment", "time-dependent")
        ):
            logger.warning(
                "Investigator: reasoned_only confirmation without a "
                "stated reason a probe was not attempted; rejecting"
            )
            return _refuse(
                result, history, REFUSE_COULD_NOT_DETERMINE,
                [result.failure_mode or "<no failure mode>"],
            )

    return result


def _find_observation_at_crash(
    history: list[dict[str, Any]], crash_line: int
) -> dict[str, Any] | None:
    """
    Find a read_file / read_symbol observation whose window contains
    the crash line.

    Observations carry `metadata.start_line` and `metadata.end_line`
    when they were produced by read_file or read_symbol. Both are
    1-indexed, inclusive — the same convention the crash line uses.

    Only successful observations qualify. A failed read_file
    ("not_a_file") has no window and cannot ground a diagnosis.

    Returns the first matching observation, or None.
    """
    for obs in history:
        if not obs.get("ok"):
            continue
        tool = obs.get("tool")
        if tool not in ("read_file", "read_symbol"):
            continue
        meta = obs.get("metadata") or {}
        start = meta.get("start_line")
        end = meta.get("end_line")
        if start is None or end is None:
            continue
        if start <= crash_line <= end:
            return obs
    return None


def _symbol_in_crash_statement(
    obs: dict[str, Any], crash_line: int, symbol: str
) -> bool:
    """
    True when `symbol` appears as an identifier in the AST statement
    that encloses `crash_line` within the observation's text.

    The observation's `result` is tool-formatted: every line is
    prefixed with `f"{n:5d}  "` (five-char right-aligned number, two
    spaces). This function strips that prefix, re-parses the code,
    and walks the AST.

    On any failure to parse (an observation's window may cut through
    a block), the function falls back to a plain text match against
    the crash line itself. That fallback is honest: if we cannot
    parse, we cannot verify, and the caller treats an unparsed
    observation the same way it treats an absent one — as
    unverifiable.

    Returns False when the symbol is absent from the statement.
    """
    raw_lines = _strip_line_prefixes(obs.get("result") or "")
    if not raw_lines:
        return False

    meta = obs.get("metadata") or {}
    start_line = meta.get("start_line") or 1
    # The crash line is absolute; convert to a line index within the
    # observation's window.
    crash_index = crash_line - start_line
    if crash_index < 0 or crash_index >= len(raw_lines):
        return False

    source = "\n".join(raw_lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # The window doesn't parse standalone (a slice through a
        # block, an indentation cut, etc.). Fall back to a text
        # match on the crash line itself. This is weaker but honest.
        return _symbol_in_line(raw_lines[crash_index], symbol)

    statement = _narrowest_statement_at(tree, crash_index + 1)
    if statement is None:
        return _symbol_in_line(raw_lines[crash_index], symbol)

    return _symbol_in_ast(statement, symbol)


def _strip_line_prefixes(text: str) -> list[str]:
    """
    Remove the `NNNNN  ` prefix the tools add to each line.

    read_file and read_symbol render `f"{n:5d}  {line}"` for every
    line. This function returns just the source text of each line,
    preserving order. Blank lines are preserved as empty strings.
    """
    if not text:
        return []
    stripped: list[str] = []
    for line in text.split("\n"):
        # The prefix is 5 digits, 2 spaces. Regex tolerant of any
        # line-number width in case the tool changes format.
        m = re.match(r"^\s*\d+\s\s(.*)$", line)
        if m:
            stripped.append(m.group(1))
        else:
            # A line without a prefix — could be a continuation or a
            # trailing newline. Preserve as-is.
            stripped.append(line)
    return stripped


def _narrowest_statement_at(
    tree: ast.AST, line_number: int
) -> ast.stmt | None:
    
    candidates: list[ast.stmt] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        if lineno is None or end_lineno is None:
            continue
        if lineno <= line_number <= end_lineno:
            candidates.append(node)

    if not candidates:
        return None

    def span(n: ast.stmt) -> int:
        return getattr(n, "end_lineno", 0) - getattr(n, "lineno", 0)

    candidates.sort(key=span)
    return candidates[0]


def _symbol_in_ast(node: ast.AST, symbol: str) -> bool:
    """
    True when `symbol` appears as an identifier anywhere within the
    AST subtree rooted at `node`.

    Matches:
        - An `ast.Name` whose id equals the symbol's leaf
          (e.g. `query` for symbol "query", or for "self.query").
        - An `ast.Attribute` whose unparsed form equals the symbol
          (e.g. `self.rag` for symbol "self.rag").

    The leaf match handles the argument case: `search_similar_outcomes(query)`
    has `query` as a Name node in the call's argument list, and it
    counts even though it is never dot-accessed.
    """
    leaf = _symbol_leaf(symbol)
    if not leaf:
        return False

    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == leaf:
            return True
        if isinstance(child, ast.Attribute):
            try:
                if ast.unparse(child) == symbol:
                    return True
            except Exception:
                # ast.unparse can fail on unusual nodes; skip.
                pass
    return False


def _symbol_in_line(line: str, symbol: str) -> bool:
    """
    Text fallback: does `symbol` (or its leaf) appear in this line as
    a bare identifier?

    Used only when the observation's text will not parse. Weaker
    than the AST check — no scope awareness — but honest about its
    limits. The lookbehind rejects matches inside longer identifiers
    (`rag` does not match `storagerag`).
    """
    leaf = _symbol_leaf(symbol)
    if not leaf:
        return False
    pattern = re.compile(r"(?<!\w)" + re.escape(leaf) + r"(?!\w)")
    return bool(pattern.search(line))


def _symbol_leaf(symbol: str) -> str:
    """
    Extract the final segment of a symbol for AST Name matching.

    `self.rag`         → `rag`
    `get_rag_service`  → `get_rag_service`
    `get_rag_service()`→ `get_rag_service`
    `order.items[0]`   → `items`
    `x`                → `x`
    ``                 → ``
    """
    s = symbol.strip().rstrip("()")
    if not s:
        return ""
    s = s.split("[")[0]
    parts = s.split(".")
    return parts[-1].strip()


class InvestigatorAgent:
    """
    Bounded agent for diagnosis.

    Constructor takes the LLM service (so tests can inject a stub) and
    the repo root (so the tools can resolve paths). The repo root is
    the same string the pipeline passes to get_file_content today —
    either "owner/repo" for GitHub-backed incidents or an absolute
    path to a local checkout.
    """

    def __init__(self, llm_service, repo_root: str):
        self.llm = llm_service
        self.repo_root = repo_root
        self._current_chain: list[dict[str, Any]] = []

    async def investigate(
        self,
        context: InvestigatorContext,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    ) -> InvestigationResult:
        """
        Run the loop. Terminates on any of the five statuses.
        Never raises for a user-facing failure — a refusal, a timeout,
        or a bad action are all valid terminal states.
        """
        self._current_chain = list(context.chain or [])
        history: list[dict[str, Any]] = []
        start = time.monotonic()

        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - start
            if elapsed > time_budget_seconds:
                logger.info(
                    f"Investigator: timeout after {iteration - 1} "
                    f"iterations ({elapsed:.1f}s)"
                )
                return InvestigationResult(
                    status=STATUS_TIMEOUT,
                    iterations=iteration - 1,
                    history=history,
                )

            action = await self._decide(context, history, iteration)
            if action is None:
                logger.warning("Investigator: decision parse failed")
                return InvestigationResult(
                    status=STATUS_DECISION_FAILED,
                    iterations=iteration - 1,
                    history=history,
                )

            if action.action == "diagnose" and context.mode == MODE_INCIDENT:
                diagnosed = self._diagnose_result(action, iteration, history)
                return _validate_diagnosis(
                    diagnosed,
                    history,
                    crash_file=context.file_path,
                    crash_line=context.line_number,
                )

            if action.action == "confirm" and context.mode == MODE_SCAN:
                confirmed = self._confirm_result(action, iteration, history)
                return _validate_scan_confirmation(
                    confirmed, history, chain=context.chain,
                )

            if action.action == "refuse":
                return self._refuse_result(action, iteration, history)

            if action.action not in tool_actions(context.mode):
                # Parser should have caught this, but belt-and-suspenders:
                # an action that isn't a tool and isn't a terminal is
                # a decision failure.
                logger.warning(
                    f"Investigator: invalid action kind {action.action!r}"
                )
                return InvestigationResult(
                    status=STATUS_DECISION_FAILED,
                    iterations=iteration - 1,
                    history=history,
                )

            observation = await self._execute_tool(action, iteration)
            history.append(observation)

        logger.info(
            f"Investigator: iteration limit reached "
            f"({max_iterations} iterations)"
        )
        return InvestigationResult(
            status=STATUS_ITERATION_LIMIT,
            iterations=max_iterations,
            history=history,
        )

    # ------------------------------------------------------------------
    # Decision — the only non-deterministic step
    # ------------------------------------------------------------------

    async def _decide(
        self,
        context: InvestigatorContext,
        history: list[dict[str, Any]],
        iteration: int,
    ) -> InvestigatorAction | None:
        """
        Ask the LLM for the next action. Returns a parsed
        InvestigatorAction, or None if the response cannot be parsed.

        This is the only method the test suite mocks. Everything
        downstream of it is deterministic.
        """
        prompt = self._build_decision_prompt(context, history, iteration)

        resp = await self.llm.complete_raw_detailed(
            prompt=prompt,
            system=self._system_prompt(context.mode, context=context),
            temperature=0.2,
            max_tokens=800,
            response_format="json_object",
        )

        if not resp or not resp.content:
            logger.warning("Investigator: LLM returned no content")
            return None

        if resp.finish_reason in ("length", "MAX_TOKENS", "max_tokens"):
            logger.warning(
                "Investigator: LLM response was truncated by token limit"
            )
            return None

        return self._parse_action(resp.content, context.mode)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _system_prompt(
        self,
        mode: str = MODE_INCIDENT,
        context: InvestigatorContext | None = None,
    ) -> str:
        if mode == MODE_SCAN:
            base = self._scan_system_prompt()
            # Append a builtin-specific note when the finding's
            # symbol is a CPython module builtin with Optional type.
            # The note tells the Investigator exactly why the symbol
            # can be None (e.g. -OO mode strips __doc__), so it
            # doesn't have to guess at interpreter semantics.
            #
            # Only appended for scan mode. Incident mode diagnoses a
            # null source from a stack trace; the builtin table isn't
            # relevant there.
            if context is not None and context.symbol:
                note = format_note(context.symbol)
                if note:
                    logger.debug(
                        f"Investigator: injected builtin note for "
                        f"symbol {context.symbol!r}"
                    )
                    base = base + "\n\n## CPython module builtin\n" + note
            return base
        return self._incident_system_prompt()

    def _incident_system_prompt(self) -> str:
        return (
            "You are an SRE investigating a production incident. Your "
            "job is to identify the exact null source for a null "
            "dereference, using the tools provided.\n\n"
            "You MUST respond with a single JSON object. No prose "
            "before or after. No Markdown fences. The object describes "
            "your next step — it is NOT a function call.\n\n"
            "Schema:\n"
            "{\n"
            '  "thought": "one sentence, at most 200 characters",\n'
            '  "next_step": "read_file" | "read_symbol" | "search_codebase" '
            '| "diagnose" | "refuse",\n'
            '  "parameters": { ... }\n'
            "}\n\n"
            "Next-step parameters:\n"
            '  read_file       parameters: {"path": str, "start_line": int?, "end_line": int?}\n'
            '  read_symbol     parameters: {"path": str, "symbol_name": str}\n'
            '  search_codebase parameters: {"pattern": str, "file_glob": str?}\n\n'
            "Terminal next-steps:\n"
            '  diagnose parameters: {"null_source": str, "evidence": str, "confidence": float}\n'
            '  refuse   parameters: {"reason": str, "candidates_considered": [str]}\n\n'
            "Rules:\n"
            "1. Use read_symbol to find where a name is defined or "
            "assigned. Example: to check whether self.rag can be None, "
            'call read_symbol with symbol_name="self.rag".\n'
            "2. Only call diagnose when you can name the exact "
            "expression that is None. Include evidence: which line(s) "
            "show that this expression can be None.\n"
            "3. Do NOT refuse on your first attempt. A single failed "
            "tool call is not enough information to refuse. If a "
            'read_file call returns "not_a_file", the path from the '
            "stack trace likely does not match the repo layout — use "
            "search_codebase to find the file by name before giving up. "
            "You must either succeed at reading the failing code, or "
            "try at least three different paths to find it, before you "
            "may call refuse.\n"
            "4. A refusal after real investigation is a correct answer. "
            "A refusal on the first error is not.\n"
            "5. If you have identified an expression X such that "
            "X.something() is the failing call, and you have read the "
            "line where X is assigned, that assignment is your null "
            "source. Call diagnose with null_source=X. Do not continue "
            "investigating. You have enough information.\n"
            "6. You have a maximum of 8 iterations. If you have used 5 "
            "iterations and have not diagnosed, use your next iteration "
            "to diagnose the best candidate you have identified. An "
            "answer with confidence 0.6 is better than no answer at 8 "
            "iterations.\n"
            "7. Do not propose a fix. Do not output a diff. Only "
            "diagnose the null source or refuse.\n"
            "8. CRITICAL — what makes a valid null_source. The null "
            "source you name MUST be an expression that is actually "
            "dereferenced at or near the crash site. Concretely:\n"
            "     - The symbol must appear in the code you fetched, "
            "not just in a function signature or a docstring.\n"
            "     - If the expression is a function parameter, it can "
            "only be the null source if that parameter is itself "
            "dereferenced at the crash site (e.g. `param.attr` or "
            "`param[key]`). Naming a parameter that is only received "
            "and stored is not a diagnosis.\n"
            "     - Prefer the expression that appears on the line the "
            "stack trace names, or on a line very near it.\n"
            "     - If you cannot point to a specific line in the code "
            "you fetched where the named symbol is dereferenced, do "
            "NOT diagnose it. Call refuse instead, or keep "
            "investigating with a different tool.\n"
            "   The pipeline will verify your diagnosis against the "
            "code you fetched. A diagnosis that names a symbol the "
            "pipeline cannot find will be rejected and the incident "
            "will be reported as refused. Diagnose only what you can "
            "show."
        )
        
    def _scan_system_prompt(self) -> str:
        return (
            "You are reviewing a suspicious pattern in a codebase. A "
            "static analyzer flagged the shape at a specific (file, "
            "line) as potentially dangerous. Your job is to decide "
            "whether it is a real defect.\n\n"
            "IMPORTANT — most flags are benign. The analyzer is "
            "deliberately over-inclusive: it fires on any attribute "
            "access on a call result, any bare except, any mutable "
            "default argument. Refusing is a normal and correct "
            "outcome. The precision of this system depends on your "
            "refusal rate. Do not confirm a finding just because it " 
            "was flagged.\n\n"
            "You MUST respond with a single JSON object. No prose "
            "before or after. No Markdown fences. The object describes "
            "your next step — it is NOT a function call.\n\n"
            "Schema:\n"
            "{\n"
            '  "thought": "one sentence, at most 200 characters",\n'
            '  "next_step": "read_file" | "read_symbol" | '
            '"search_codebase" | "read_chain" | "probe" | "confirm" | '
            '"refuse",\n'
            '  "parameters": { ... }\n'
            "}\n\n"
            "Tool parameters:\n"
            '  read_file       {"path": str, "start_line": int?, "end_line": int?}\n'
            '  read_symbol     {"path": str, "symbol_name": str}\n'
            '  search_codebase {"pattern": str, "file_glob": str?}\n'
            '  read_chain      {}  — reads the full chain in one observation\n'
            '  probe           {"code": str, "language": "Python"?}  — '
            "runs the code in a sandbox. Use this to test your "
            "hypothesis.\n\n"
            "End parameters:\n"
            '  confirm {"failure_mode": str, "fix_location": str, '
            '"evidence": str, "confidence": float, '
            '"confirmation": "probe_reproduced" | "reasoned_only"}\n'
            '  refuse  {"reason": "false_positive" | "could_not_determine", '
            '"candidates_considered": [str]}\n\n'
            "## Two kinds of findings\n"
            "The finding you receive is one of two kinds.\n\n"
            "**Chain-based** (unchecked_optional_attr, unchecked_dict_access):\n"
            "The finding involves a symbol whose origin was traced. The "
            "chain shows where the symbol came from. Read the chain to "
            "decide whether the symbol can be None at the crash site.\n\n"
            "**Standalone** (bare_except, mutable_default_arg, "
            "comparison_with_none_identity):\n"
            "The finding has NO chain. The pattern is suspicious on its "
            "own, without needing to know where any symbol came from. "
            "Calling read_chain on a standalone finding returns an empty "
            "observation and wastes an iteration. For these, read the "
            "surrounding code directly with read_file and evaluate the "
            "pattern.\n\n"
            "The finding's pattern name tells you which kind it is. If "
            "the pattern is bare_except, mutable_default_arg, or "
            "comparison_with_none_identity, it is standalone. Everything "
            "else is chain-based.\n\n"
            "## How to read the chain (chain-based findings only)\n"
            "The chain is a list of links. Each link has:\n"
            "  - file, line: where this step happens\n"
            "  - symbol: the name involved at this step\n"
            "  - reason: why this link is in the chain "
            "(usage, assignment, return, parameter, definition)\n"
            "  - terminal_kind: Optional | Concrete | Unknown. "
            "Optional means the type says it can be None. Concrete "
            "means the type says it cannot.\n"
            "  - branch_id: 0 means the link is before any branch. "
            "Links sharing the same non-zero branch_id are one "
            "branch of a multi-source assignment (order = cache() or "
            "db()). The chain is flat; the branch structure lives in "
            "the branch_id tags.\n"
            "Rule for branches: if only one branch is unsafe, the "
            "fix belongs at that outlier branch, not at the crash "
            "site.\n\n"
            "## Rules for chain-based findings\n"
            "1. Start by calling read_chain. That gives you the "
            "whole chain in one observation. Read it before deciding.\n"
            "2. Look at the chain's terminal: does the type or "
            "contract say the symbol can be None (Optional) or not "
            "(Concrete)? Only Optional terminals support a real bug.\n"
            "3. fix_location must be one of the files listed in the "
            "chain. If the fix belongs at a branch, name that "
            "branch's file.\n\n"
            "## Rules for standalone findings\n"
"1. Do NOT call read_chain. There is no chain. Calling it "
"returns an empty observation and wastes an iteration.\n"
"2. Read the enclosing function first. Call read_symbol on "
"the function containing the flagged line to get its full "
"body in one observation. A bare_except inside a finally: "
"block means something different from one in a try: body, "
"and you cannot tell which from a 20-line window. You must "
"see the whole function before you evaluate the pattern.\n"
"3. For bare_except, read at least one caller. Use "
"search_codebase with the function name to find call sites, "
"then read_file on the first call site. You must see whether "
"the caller checks the return value, whether the caller is "
"itself in an error path, and whether the swallowed "
"exception would have propagated past the caller. A "
"swallowed exception that only affects a cleanup path is a "
"false positive. One that hides a data-corruption failure "
"is a real defect.\n"
"4. Evaluate the pattern with the full function and at "
"least one caller in view:\n"
"   - bare_except: is the exception swallowed silently? "
"Does the function's return value matter to its caller? "
"A bare `except: pass` that hides a real failure and whose "
"caller assumes success is a defect. A bare `except:` that "
"logs the error and continues, or that is deliberate cleanup "
"after a process kill, is not.\n"
"   - mutable_default_arg: does the function mutate the "
"default? A `def f(x=[])` that appends to x is a defect. "
"One that only reads x is not. You must see the full "
"function body to know which.\n"
"   - comparison_with_none_identity: almost always a style "
"issue, not a bug. Refuse with false_positive unless the "
"surrounding code makes the choice meaningful (e.g. the "
"object defines __eq__ with side effects).\n"
"5. fix_location must be the file containing the flagged "
"line. It does not need to be a chain file — there is no "
"chain. It is the file where the fix would land.\n\n"
"## Rules for both kinds\n"
"6. Every confirm must attempt a probe. If you name a "
"failure_mode, you must write a probe call that reproduces "
"it before calling confirm. The only exception is when the "
"failure mode requires external state you cannot construct "
"in a sandbox (network, time, filesystem, interpreter "
"flags like -OO, -c, -m, or specific Python versions) — in "
"that case, set confirmation=\"reasoned_only\" and state in "
"evidence which external factor makes a sandbox probe "
"impossible. A confirm with confirmation=\"reasoned_only\" "
"and no stated reason is incomplete and will be rejected by "
"the validator.\n"
"7. State a concrete failure mode. Not \"looks wrong\" — "
"\"crashes when order_id doesn't exist\". Name the input "
"shape that triggers it, and name the observable result.\n"
"8. Refuse when the pattern is a false positive or when "
"you cannot determine whether it is a real bug. "
"Enumerated reasons: false_positive, could_not_determine.\n"
"9. Do not propose a diff. Do not output a fix. The Fixer "
"receives fix_location and writes the diff.\n\n"
            "## Example — a chain-based real defect\n"
            "  Chain: order.total used at payment_service.py:234 → "
            "order assigned from fetch_order(id) → fetch_order "
            "returns Optional[Order] → unguarded.\n"
            "  This is a defect. Confirm with failure_mode=\"crashes "
            "when order is None\", fix_location=payment_service.py, "
            "confirmation based on whether a probe reproduced it.\n\n"
            "## Example — a chain-based false positive\n"
            "  Same chain, but with an early `if order is None: "
            "return` on the path between fetch_order and order.total.\n"
            "  Refuse with reason=\"false_positive\". The guard "
            "prevents the crash.\n\n"
            "## Example — a standalone real defect\n"
            "  Finding: bare_except at incident_service.py:1633.\n"
            "  Read the code: `except: pass` wraps a `json.loads(...)` "
            "call on `extra_metadata`. If the JSON is malformed, the "
            "exception is swallowed and downstream code receives a "
            "string where it expects a dict. That crashes later, in a "
            "place that is harder to debug.\n"
            "  This is a defect. Confirm with failure_mode=\"malformed "
            "extra_metadata silently becomes a string; downstream dict "
            "access crashes\", fix_location=incident_service.py, "
            "confirmation=\"reasoned_only\" (a probe would need to "
            "construct the exact failing input).\n\n"
            "## Example — a standalone false positive\n"
            "  Finding: bare_except at verifier.py:939.\n"
            "  Read the code: `except: pass` wraps `proc.wait()` after "
            "a `proc.kill()`. The exception is expected (the process "
            "may already be reaped), and swallowing it is the "
            "deliberate cleanup pattern.\n"
            "  Refuse with reason=\"false_positive\". The bare except "
            "is intentional.\n"
        )
    
    def _build_decision_prompt(
        self,
        context: InvestigatorContext,
        history: list[dict[str, Any]],
        iteration: int,
    ) -> str:
        parts: list[str] = []
        parts.append(context.to_prompt())

        parts.append("")
        parts.append(f"## Iteration {iteration}")

        if history:
            parts.append("## What you have already looked at")
            for obs in history:
                parts.append(self._render_observation(obs))
        else:
            parts.append("(no tool calls yet)")

        parts.append("")
        parts.append(
            "Respond with a single JSON object matching the schema. "
            "If you have enough information, call diagnose. If you "
            "cannot identify the null source, call refuse. Otherwise, "
            "call one tool."
        )
        return "\n".join(parts)

    @staticmethod
    def _render_observation(obs: dict[str, Any]) -> str:
        """Compact rendering of one tool observation for the prompt."""
        tool = obs.get("tool", "?")
        args = obs.get("args", {})
        ok = obs.get("ok", False)
        iteration = obs.get("iteration", "?")
        truncated = obs.get("truncated", False)

        header = f"--- iteration {iteration}: {tool}({args}) -> {'ok' if ok else 'error'}"
        if truncated:
            header += " [truncated]"

        lines = [header]
        if not ok:
            lines.append(f"error: {obs.get('error', 'unknown')}")
        else:
            result = obs.get("result", "")
            lines.append(result)

        # Cap the rendered observation. History can accumulate; if
        # every observation were unbounded, the prompt would blow up
        # by iteration 3.
        rendered = "\n".join(lines)
        max_chars = 3000
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars] + "\n[observation truncated]"
        return rendered

    # ------------------------------------------------------------------
    # Action parsing — where the code enforces what the prompt requests
    # ------------------------------------------------------------------

    def _parse_action(self, raw: str, mode: str = MODE_INCIDENT) -> InvestigatorAction | None:
        """
        Parse the LLM's JSON into an InvestigatorAction.

        Returns None when the response cannot be parsed or is
        structurally invalid. The caller treats None as
        decision_failed.

        Enforces (in code, not prompt):
            - action in VALID_ACTIONS
            - thought truncated to THOUGHT_MAX_CHARS
            - args is a dict
            - diagnose: confidence defaults to DEFAULT_CONFIDENCE
            - refuse: candidates_considered is a list
        """
        payload = self._extract_json(raw)
        if payload is None or not isinstance(payload, dict):
            return None

        action = payload.get("next_step")
        if not isinstance(action, str) or action not in valid_actions(mode):
            logger.warning(f"Investigator: invalid action {action!r}")
            return None

        thought = payload.get("thought", "") or ""
        if not isinstance(thought, str):
            thought = str(thought)
        thought = thought[:THOUGHT_MAX_CHARS]

        args = payload.get("parameters") or {}
        if not isinstance(args, dict):
            # Args must be an object. A bare value is a schema
            # violation, not something to coerce.
            logger.warning(
                f"Investigator: args is {type(args).__name__}, expected dict"
            )
            return None

        # Normalize per-action fields.
        if action == "diagnose":
            null_source = args.get("null_source")
            if not isinstance(null_source, str) or not null_source.strip():
                logger.warning(
                    "Investigator: diagnose without a null_source"
                )
                return None
            evidence = args.get("evidence", "") or ""
            if not isinstance(evidence, str):
                evidence = str(evidence)
            confidence = args.get("confidence", DEFAULT_CONFIDENCE)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = DEFAULT_CONFIDENCE
            # Clamp to [0.0, 1.0] — the prompt asks for it, the parser
            # enforces it.
            confidence = max(0.0, min(1.0, confidence))
            args = {
                "null_source": null_source.strip(),
                "evidence": evidence,
                "confidence": confidence,
            }

        elif action == "refuse":
            reason = args.get("reason", "unspecified")
            if not isinstance(reason, str):
                reason = str(reason)
            candidates = args.get("candidates_considered", [])
            if not isinstance(candidates, list):
                candidates = []
            # Every candidate must be a string; drop anything else.
            candidates = [c for c in candidates if isinstance(c, str)]
            args = {
                "reason": reason,
                "candidates_considered": candidates,
            }

        # Tool actions: leave args as-is. The tool layer validates its
        # own arguments and returns an error observation if they're
        # missing or wrong.

        elif action == "confirm":
            failure_mode = args.get("failure_mode")
            if not isinstance(failure_mode, str) or not failure_mode.strip():
                logger.warning("Investigator: confirm without failure_mode")
                return None
            fix_location = args.get("fix_location")
            if not isinstance(fix_location, str) or not fix_location.strip():
                logger.warning("Investigator: confirm without fix_location")
                return None
            evidence = args.get("evidence", "") or ""
            if not isinstance(evidence, str):
                evidence = str(evidence)
            confirmation = args.get("confirmation", CONFIRMATION_REASONED_ONLY)
            if confirmation not in ALL_CONFIRMATIONS:
                confirmation = CONFIRMATION_REASONED_ONLY
            confidence = args.get("confidence", DEFAULT_CONFIDENCE)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = DEFAULT_CONFIDENCE
            confidence = max(0.0, min(1.0, confidence))
            args = {
                "failure_mode": failure_mode.strip(),
                "fix_location": fix_location.strip(),
                "evidence": evidence,
                "confidence": confidence,
                "confirmation": confirmation,
            }

        elif action == "refuse":
            reason = args.get("reason", REFUSE_COULD_NOT_DETERMINE)
            if reason not in ALL_REFUSE_REASONS:
                reason = REFUSE_COULD_NOT_DETERMINE
            candidates = args.get("candidates_considered", [])
            if not isinstance(candidates, list):
                candidates = []
            candidates = [c for c in candidates if isinstance(c, str)]
            args = {"reason": reason, "candidates_considered": candidates}

        # Tool actions: leave args as-is. The tool layer validates its
        # own arguments and returns an error observation if they're
        # missing or wrong.

        return InvestigatorAction(
            action=action, thought=thought, args=args, mode=mode
        )

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        """
        Same pattern LLMService._extract_json uses: find the first
        {...} block, parse it, return None on failure.
        """
        if not raw:
            return None
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, action: InvestigatorAction, iteration: int
    ) -> dict[str, Any]:
        """
        Dispatch to the tool layer and return an observation dict.

        Every tool returns a ToolResult. This method converts it to
        the observation shape and ensures the observation carries the
        iteration number so history rendering can label it.
        """
        if action.action == "read_file":
            result = await read_file(
                repo=self.repo_root,
                path=action.args.get("path", ""),
                start_line=action.args.get("start_line"),
                end_line=action.args.get("end_line"),
            )
        elif action.action == "read_symbol":
            result = await read_symbol(
                repo=self.repo_root,
                path=action.args.get("path", ""),
                symbol_name=action.args.get("symbol_name", ""),
            )
        elif action.action == "search_codebase":
            result = await search_codebase(
                repo=self.repo_root,
                pattern=action.args.get("pattern", ""),
                file_glob=action.args.get("file_glob"),
            )
        elif action.action == "read_chain":
            result = await read_chain(
                repo=self.repo_root,
                chain=self._current_chain,
            )
        elif action.action == "probe":
            result = await probe(
                repo=self.repo_root,
                code=action.args.get("code", ""),
                language=action.args.get("language", "Python"),
            )
        else:
            # Should be unreachable — _parse_action rejects unknown
            # actions and the loop only calls _execute_tool for tool
            # actions. If we get here, it's a bug.
            result = ToolResult(
                ok=False,
                tool=action.action,
                args=action.args,
                error=f"unknown_tool: {action.action}",
            )

        return result.to_observation(iteration=iteration)

    # ------------------------------------------------------------------
    # Terminal result builders
    # ------------------------------------------------------------------

    @staticmethod
    def _diagnose_result(
        action: InvestigatorAction,
        iteration: int,
        history: list[dict[str, Any]],
    ) -> InvestigationResult:
        return InvestigationResult(
            status=STATUS_DIAGNOSED,
            null_source=action.args.get("null_source", ""),
            evidence=action.args.get("evidence", ""),
            confidence=action.args.get(
                "confidence", DEFAULT_CONFIDENCE
            ),
            thought=action.thought,
            iterations=iteration,
            history=history,
        )
        
    @staticmethod
    def _confirm_result(
        action: InvestigatorAction,
        iteration: int,
        history: list[dict[str, Any]],
    ) -> InvestigationResult:
        return InvestigationResult(
            status=STATUS_CONFIRMED,
            failure_mode=action.args.get("failure_mode"),
            fix_location=action.args.get("fix_location"),
            evidence=action.args.get("evidence", ""),
            confidence=action.args.get("confidence", DEFAULT_CONFIDENCE),
            confirmation=action.args.get(
                "confirmation", CONFIRMATION_REASONED_ONLY
            ),
            thought=action.thought,
            iterations=iteration,
            history=history,
        )

    @staticmethod
    def _refuse_result(
        action: InvestigatorAction,
        iteration: int,
        history: list[dict[str, Any]],
    ) -> InvestigationResult:
        reason = action.args.get("reason", "unspecified")
        # A refusal with reason="could_not_determine" is not a
        # verdict of "not a bug". It's the Investigator saying "I
        # looked at the code and I can't decide." That's a
        # different claim from "this is a false positive", and the
        # pipeline should present it differently. Map it to
        # status=unverified so downstream stages (the Fixer gate,
        # the CLI's classification) can surface it under "Needs
        # Review" rather than "Refused".
        #
        # A refusal with reason="false_positive" stays as
        # STATUS_REFUSED — the Investigator is confident the
        # finding is not a bug, and the report should say so.
        status = (
            STATUS_UNVERIFIED
            if reason == REFUSE_COULD_NOT_DETERMINE
            else STATUS_REFUSED
        )
        return InvestigationResult(
            status=status,
            reason=reason,
            candidates_considered=action.args.get(
                "candidates_considered", []
            ),
            thought=action.thought,
            iterations=iteration,
            history=history,
        )
        
    
