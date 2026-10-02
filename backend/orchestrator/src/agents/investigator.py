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
import re
import time
from typing import Any

from loguru import logger

from src.agents.investigator_models import (
    ALL_STATUSES,
    STATUS_DECISION_FAILED,
    STATUS_DIAGNOSED,
    STATUS_ITERATION_LIMIT,
    STATUS_REFUSED,
    STATUS_TIMEOUT,
    TERMINAL_ACTIONS,
    TOOL_ACTIONS,
    VALID_ACTIONS,
    InvestigationResult,
    InvestigatorAction,
    InvestigatorContext,
)
from src.agents.tools.repo_tools import (
    ToolResult,
    read_file,
    read_symbol,
    search_codebase,
)


# Caps. Enforced here, not requested in the prompt.
THOUGHT_MAX_CHARS = 200
DEFAULT_CONFIDENCE = 0.7

# Loop defaults. Overridable at call time.
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_TIME_BUDGET_SECONDS = 30.0


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

            if action.action == "diagnose":
                return self._diagnose_result(action, iteration, history)

            if action.action == "refuse":
                return self._refuse_result(action, iteration, history)

            if action.action not in TOOL_ACTIONS:
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
            system=self._system_prompt(),
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

        return self._parse_action(resp.content)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
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
            "source. Call diagnose immediately with null_source=X. Do "
            "not continue investigating. You have enough information.\n"
            "6. You have a maximum of 8 iterations. If you have used 5 "
            "iterations and have not diagnosed, use your next iteration "
            "to diagnose the best candidate you have identified. An "
            "answer with confidence 0.6 is better than no answer at 8 "
            "iterations.\n"
            "7. Do not propose a fix. Do not output a diff. Only "
            "diagnose the null source or refuse."
            
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

    def _parse_action(self, raw: str) -> InvestigatorAction | None:
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
        if not isinstance(action, str) or action not in VALID_ACTIONS:
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

        return InvestigatorAction(action=action, thought=thought, args=args)

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
    def _refuse_result(
        action: InvestigatorAction,
        iteration: int,
        history: list[dict[str, Any]],
    ) -> InvestigationResult:
        return InvestigationResult(
            status=STATUS_REFUSED,
            reason=action.args.get("reason", "unspecified"),
            candidates_considered=action.args.get(
                "candidates_considered", []
            ),
            thought=action.thought,
            iterations=iteration,
            history=history,
        )
