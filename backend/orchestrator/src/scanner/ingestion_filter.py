"""Deterministic ingestion filter — drops provably-safe candidates.

This is the layer that runs BEFORE any LLM. It answers one question:
can this finding possibly be a runtime crash?

If the answer is "no, by construction," drop it. No LLM, no chain
builder, no score. Just an AST check on the source line.

Examples of provably-safe findings:

    x = "literal string"          # Pyright flags x + str, but x IS a str
    x = 42                        # Pyright flags x.foo, but 42 has no foo
    x = []                        # Pyright flags x[0], but [] is iterable
    x = {}                        # same
    x = True / False / None       # constants

If Pyright reports a finding on a line whose RHS is a literal or an
empty container constructor, the "Optional" type came from somewhere
else — Pyright's flow analysis is confused, or the finding is on a
different subexpression. Either way, the finding is noise.

This is the "metal detector" the design calls for. No thinking. No
tokens. Just `ast.parse(line)` and a set of node types.

Scope: Python-only. Non-.py findings pass through unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path

from loguru import logger

from src.scanner.candidate import PatternMatch


# AST node types that produce a non-Optional value by construction.
# If Pyright flags a finding on a line whose RHS is one of these,
# the finding is noise.
_SAFE_RHS_TYPES = (
    ast.Constant,      # "str", 42, True, False, None, b"bytes", 3.14
    ast.List,          # []
    ast.Dict,          # {}
    ast.Set,           # {1, 2}
    ast.Tuple,         # ()
    ast.JoinedStr,     # f"..." — a str, never None
)


def should_keep(
    match: PatternMatch, repo_dir: Path | str
) -> bool:
    """Return True to keep the candidate, False to drop it.

    Deterministic. No LLM. Sub-millisecond per call.

    Applies only to Pyright findings (confidence == "proven"). Pattern
    matcher findings are passed through unchanged — their false
    positive rate is already low, and the chain builder's terminal_kind
    gate handles the rest.

    Fails open: if the file can't be read or the line can't be parsed,
    the candidate is kept. A filter that drops findings because it
    couldn't inspect them is worse than no filter.
    """
    if match.confidence != "proven":
        # Pattern matcher findings: pass through. The chain gate
        # handles their false positives.
        return True

    source_line = _read_line(repo_dir, match.file, match.line)
    if source_line is None:
        return True  # fail open

    return not _rhs_is_literal(source_line)


def _read_line(
    repo_dir: Path | str, rel_path: str, line_number: int
) -> str | None:
    """Read the source line, or None if unreadable."""
    if not rel_path.endswith(".py"):
        return None
    full = Path(repo_dir) / rel_path
    if not full.is_file():
        return None
    try:
        lines = full.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1]
    return None


def _rhs_is_literal(source_line: str) -> bool:
    """True when the line is `x = <literal>` or `x = <empty container>`.

    Parses the line in isolation. A line that doesn't parse standalone
    (e.g. a continuation line) returns False — we don't drop findings
    on unparseable lines.

    The check is intentionally narrow: only assignments whose entire
    right-hand side is a literal or empty container. A line like
    `x = "a" + some_call()` doesn't qualify — the RHS isn't a literal,
    even though the LHS prefix is.
    """
    stripped = source_line.strip()
    if not stripped or stripped.startswith("#"):
        return False

    try:
        tree = ast.parse(stripped)
    except SyntaxError:
        return False

    if len(tree.body) != 1:
        return False

    node = tree.body[0]
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        return isinstance(node.value, _SAFE_RHS_TYPES)
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return isinstance(node.value, _SAFE_RHS_TYPES)

    return False
