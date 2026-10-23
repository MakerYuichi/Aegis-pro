"""Run Pyright as a subprocess and convert its diagnostics to PatternMatch.

Pyright is the language's type checker. It runs on the AST, does
type inference and flow narrowing, and emits diagnostics as JSON.
It does not execute the code being analyzed.

This module is a thin adapter: subprocess invocation, JSON parsing,
diagnostic-to-PatternMatch mapping. It does not decide which
diagnostics are relevant — that's the caller's job (scan_runner).

The five reportOptional* rules map directly to the null-safety
category:

    reportOptionalMemberAccess   `x.y` where x: Optional[T]
    reportOptionalSubscript      `x[k]` where x: Optional[T]
    reportOptionalCall           `x()` where x: Optional[T]
    reportOptionalIterable       `for _ in x` where x: Optional[T]
    reportOptionalOperand        `x + y` where x: Optional[T]

Every one of those reduces to "Optional value used as non-Optional."
The pattern name preserves the distinction so the report can name
the exact failure mode.

Scope: Python-only. Pyright handles no other language.

Not this module's job: producing a diff, running tests, deciding
which candidates are real. Those are downstream stages. Pyright is
a candidate generator.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from src.scanner.candidate import PatternMatch


# Pyright rule → internal pattern name. The mapping is 1:1 for
# reportOptional* rules because Pyright's names are already clear.
# A future version may want to merge some categories, but for now
# keeping them distinct is useful — the report names the exact kind
# of null-safety violation, and downstream code (Fixer prompts,
# report formatting) can specialize per pattern.
_RULE_TO_PATTERN: dict[str, str] = {
    "reportOptionalMemberAccess": "optional_member_access",
    "reportOptionalSubscript": "optional_subscript",
    "reportOptionalCall": "optional_call",
    "reportOptionalIterable": "optional_iterable",
    "reportOptionalOperand": "optional_operand",
}


# Timeout for a single-file Pyright run. Pyright is fast (0.1-1s
# for small files, up to ~10s for very large files with deep type
# resolution). 60s is generous; anything longer is a stuck
# subprocess.
_PYRIGHT_TIMEOUT_SECONDS = 60


def pyright_available() -> bool:
    """True when the pyright CLI is on PATH.

    A single source of truth for "can we run Pyright." The runner
    and any health check should both call this.
    """
    return shutil.which("pyright") is not None


def run_pyright(file_path: Path, rel_path: str) -> list[PatternMatch]:
    """Run Pyright on a single file and return its Optional findings.

    Returns [] on:
      - pyright not installed
      - pyright subprocess failed
      - malformed JSON
      - non-.py files (Pyright handles .py and .pyi only)

    Never raises. A Pyright failure must not break the scan —
    pattern matching continues to work, and the missing candidates
    are logged at debug level.

    Args:
        file_path: absolute path on disk to analyze
        rel_path:  repo-relative path to record in the PatternMatch
                   (so downstream stages see the same path the
                   pattern matcher produces)

    Returns:
        list[PatternMatch], one per reportOptional* diagnostic on
        this file. Empty when Pyright produced no relevant
        diagnostics.
    """
    if not rel_path.endswith(".py"):
        return []

    if not pyright_available():
        logger.debug("pyright_runner: pyright not on PATH, skipping")
        return []

    # Pyright supports being pointed at a directory, but per-file
    # invocation keeps the mapping between output and input clean
    # (no need to filter the diagnostic list by file).
    #
    # --level error: suppresses warnings. Pyright's warnings include
    # style issues (unused imports, invalid escape sequences) that
    # aren't null-safety. We only want errors.
    #
    # --project /dev/null: use Pyright's defaults, ignore any
    # pyrightconfig.json the repo might have. A repo-provided config
    # could disable reportOptional* rules or narrow the analysis in
    # ways that hide findings. We want the checkers on, unconditionally.
    try:
        proc = subprocess.run(
            [
                "pyright",
                "--outputjson",
                "--level", "error",
                "--project", "/dev/null",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=_PYRIGHT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"pyright_runner: subprocess failed on {rel_path}: {e}")
        return []

    if not proc.stdout:
        logger.warning(
            f"pyright_runner: no stdout for {rel_path}, "
            f"stderr={proc.stderr[:200]!r}"
        )
        return []

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        logger.warning(
            f"pyright_runner: bad JSON for {rel_path}: {e}; "
            f"head={proc.stdout[:200]!r}"
        )
        return []

    diagnostics = payload.get("generalDiagnostics") or []
    matches: list[PatternMatch] = []

    for diag in diagnostics:
        rule = diag.get("rule") or ""
        pattern_name = _RULE_TO_PATTERN.get(rule)
        if pattern_name is None:
            continue

        if diag.get("severity") != "error":
            continue

        rng = diag.get("range") or {}
        start = rng.get("start") or {}
        line0 = start.get("line")
        if line0 is None:
            continue

        message = diag.get("message") or rule
        char0 = start.get("character", 0)
        symbol = _extract_symbol(file_path, line0 + 1, char0) or "<expression>"
        matches.append(PatternMatch(
            file=rel_path,
            line=line0 + 1,
            symbol=symbol,
            pattern=pattern_name,
            confidence="proven",
            snippet="",
            requires_chain=True,
            metadata={
                "pyright_rule": rule,
                "pyright_message": message,
                "pyright_severity": "error",
            },
        ))

    return matches


def _extract_symbol(
    file_path: Path, line: int, char: int
) -> str | None:
    """Extract the symbol that starts at (line, char) in the file.

    Pyright reports diagnostics by range. The start of the range is
    the leftmost character of the offending expression. For
    `__doc__ + '\n'`, that's the `_` of `__doc__`. For `x.y.z() + None`,
    it's the `x`.

    We parse the file with the stdlib AST and find the Name or
    Attribute node that starts at exactly this position. If the node
    is a plain Name, return its id. If it's an Attribute, return the
    dotted path. If no node starts at this exact (line, char), return
    None — the caller substitutes "<expression>" and the chain builder
    fills in the real symbol.

    Args:
        file_path: absolute path to the source file
        line:      1-indexed line
        char:      0-indexed character offset on that line

    Returns:
        The symbol name, or None.
    """
    try:
        import ast
        text = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return None

    target_line = line
    target_col = char

    def _match_pos(node: ast.AST) -> bool:
        return (
            getattr(node, "lineno", -1) == target_line
            and getattr(node, "col_offset", -1) == target_col
        )

    for node in ast.walk(tree):
        if not _match_pos(node):
            continue
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts = [node.attr]
            cur = node.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))

    return None