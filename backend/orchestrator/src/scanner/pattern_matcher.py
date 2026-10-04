"""Find suspicious shapes in a Python file.

A "pattern match" is not a finding. It's a suspicion — a shape that
is *sometimes* a bug, depending on information the matcher cannot
see. `order.total` is suspicious if `order` came from a function
returning `Optional[Order]`; it's fine if `order` came from a
validated source.

The pattern matcher uses Python's `ast` module, not regex, because
regex fires on comments and strings. If a comment contains
`# TODO: fix order.total`, the regex matcher sees a bug. The AST
matcher sees a comment.

Patterns the matcher knows (Python-only):

    unchecked_optional_attr      `foo().bar` or `foo["x"].bar` — the
                                 result of a call or subscript is
                                 dereferenced. Whether it can be None
                                 depends on the call's return type.

    unchecked_dict_access        `d["key"]` where `d` came from a
                                 call. Whether the key exists
                                 depends on the callee.

    bare_except                  `except:` or `except Exception: pass`.
                                 This is a real smell on its own, not
                                 dependent on a chain. requires_chain
                                 is False.

    mutable_default_arg          `def foo(x=[])` or `def foo(x={})`.
                                 A real smell on its own.

    comparison_with_none_identity   `== None` or `!= None` instead of
                                    `is None`. Style smell, no chain.

Patterns that require a chain: unchecked_optional_attr and
unchecked_dict_access. Those are the ones whose danger depends on
what the symbol's origin was.

Scope: Python-only. Non-.py files are not matched.
"""

from __future__ import annotations

import ast
from pathlib import Path

from loguru import logger

from src.scanner.candidate import PatternMatch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_patterns(file_path: Path, rel_path: str) -> list[PatternMatch]:
    """Find all pattern matches in a single Python file.

    Returns a list of PatternMatch, ordered by line number.

    `file_path` is the absolute path to read. `rel_path` is the
    repo-relative POSIX path to record in the matches — the two are
    separated because the matcher is a leaf function that shouldn't
    need to know about repo roots.

    Returns [] for non-Python files, unreadable files, and files
    with syntax errors. All three cases are honest no-ops: the file
    has no patterns the AST can see.
    """
    if not rel_path.endswith(".py"):
        return []

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        logger.debug(f"pattern_matcher: syntax error in {rel_path}")
        return []

    lines = text.splitlines()
    matches: list[PatternMatch] = []

    for node in ast.walk(tree):
        matches.extend(_match_node(node, rel_path, lines))

    # Sort by line number for deterministic output.
    matches.sort(key=lambda m: (m.line, m.symbol, m.pattern))
    return matches


# ---------------------------------------------------------------------------
# Per-node matching
# ---------------------------------------------------------------------------

def _match_node(
    node: ast.AST, rel_path: str, lines: list[str]
) -> list[PatternMatch]:
    """Dispatch a single AST node to its matchers."""
    results: list[PatternMatch] = []

    if isinstance(node, ast.Attribute):
        results.extend(_match_attr(node, rel_path, lines))

    elif isinstance(node, ast.Subscript):
        results.extend(_match_subscript(node, rel_path, lines))

    elif isinstance(node, ast.ExceptHandler):
        results.extend(_match_except(node, rel_path, lines))

    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        results.extend(_match_defaults(node, rel_path, lines))

    elif isinstance(node, ast.Compare):
        results.extend(_match_none_comparison(node, rel_path, lines))

    return results


def _match_attr(
    node: ast.Attribute, rel_path: str, lines: list[str]
) -> list[PatternMatch]:
    """`foo().bar` or `foo["x"].bar` — attribute on a call or subscript."""
    # Only the *outer* Attribute is interesting. If the value is
    # another Attribute, this is `a.b.c` and the inner node will be
    # matched when the walk visits it.
    value = node.value
    if isinstance(value, ast.Call):
        symbol = _call_symbol(value)
        if symbol is None:
            return []
        return [PatternMatch(
            file=rel_path,
            line=node.lineno,
            symbol=symbol,
            pattern="unchecked_optional_attr",
            confidence="low",
            snippet=_snippet(lines, node.lineno),
            requires_chain=True,
        )]

    if isinstance(value, ast.Subscript):
        symbol = _subscript_symbol(value)
        if symbol is None:
            return []
        return [PatternMatch(
            file=rel_path,
            line=node.lineno,
            symbol=symbol,
            pattern="unchecked_optional_attr",
            confidence="low",
            snippet=_snippet(lines, node.lineno),
            requires_chain=True,
        )]

    return []


def _match_subscript(
    node: ast.Subscript, rel_path: str, lines: list[str]
) -> list[PatternMatch]:
    """`foo()["key"]` — subscript on a call result.

    Attribute access is handled by _match_attr. This handles the case
    where the result is subscripted directly, e.g. `get_config()["db"]`.
    """
    if not isinstance(node.value, ast.Call):
        return []
    symbol = _call_symbol(node.value)
    if symbol is None:
        return []
    return [PatternMatch(
        file=rel_path,
        line=node.lineno,
        symbol=symbol,
        pattern="unchecked_dict_access",
        confidence="low",
        snippet=_snippet(lines, node.lineno),
        requires_chain=True,
    )]


def _match_except(
    node: ast.ExceptHandler, rel_path: str, lines: list[str]
) -> list[PatternMatch]:
    """`except:` or `except Exception:` with a Pass body.

    A bare or broad except that swallows the error is a real smell on
    its own — no chain needed to know it's suspicious. requires_chain
    is False.
    """
    broad = node.type is None or _is_broad_exception(node.type)
    if not broad:
        return []
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
        return []
    return [PatternMatch(
        file=rel_path,
        line=node.lineno,
        symbol="except",
        pattern="bare_except",
        confidence="medium",
        snippet=_snippet(lines, node.lineno),
        requires_chain=False,
    )]


def _match_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    lines: list[str],
) -> list[PatternMatch]:
    """`def foo(x=[])` or `def foo(x={})` — mutable default argument."""
    results: list[PatternMatch] = []
    for default in node.args.defaults + node.args.kw_defaults:
        if isinstance(default, (ast.List, ast.Dict, ast.Set)):
            results.append(PatternMatch(
                file=rel_path,
                line=node.lineno,
                symbol=node.name,
                pattern="mutable_default_arg",
                confidence="medium",
                snippet=_snippet(lines, node.lineno),
                requires_chain=False,
            ))
            # One match per function, even with multiple mutable
            # defaults — the fix is the same.
            break
    return results


def _match_none_comparison(
    node: ast.Compare, rel_path: str, lines: list[str]
) -> list[PatternMatch]:
    """`x == None` or `x != None` — style smell.

    Low confidence, no chain. Included because it's cheap and it
    gives the matcher a signal that doesn't depend on types.
    """
    for op, comparator in zip(node.ops, node.comparators):
        if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant):
            if comparator.value is None:
                symbol = _expr_symbol(node.left) or "?"
                return [PatternMatch(
                    file=rel_path,
                    line=node.lineno,
                    symbol=symbol,
                    pattern="comparison_with_none_identity",
                    confidence="low",
                    snippet=_snippet(lines, node.lineno),
                    requires_chain=False,
                )]
    return []


# ---------------------------------------------------------------------------
# Symbol extraction helpers
# ---------------------------------------------------------------------------

def _call_symbol(call: ast.Call) -> str | None:
    """Human-readable name for a call expression.

    `get_rag_service()` → "get_rag_service"
    `self.rag.search()` → "self.rag.search"
    `obj.method()[0]` → None (we only name direct calls)
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return _attr_path(func)
    return None


def _subscript_symbol(sub: ast.Subscript) -> str | None:
    """Name for a subscript expression's value."""
    return _expr_symbol(sub.value)


def _expr_symbol(expr: ast.AST) -> str | None:
    """Human-readable name for an expression node, or None."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return _attr_path(expr)
    if isinstance(expr, ast.Call):
        return _call_symbol(expr)
    return None


def _attr_path(node: ast.Attribute) -> str:
    """Render `a.b.c` as "a.b.c"."""
    parts: list[str] = [node.attr]
    current = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _is_broad_exception(node: ast.AST) -> bool:
    """True when the except clause catches Exception or BaseException."""
    if isinstance(node, ast.Name):
        return node.id in ("Exception", "BaseException")
    if isinstance(node, ast.Attribute):
        return node.attr in ("Exception", "BaseException")
    if isinstance(node, ast.Tuple):
        return any(_is_broad_exception(elt) for elt in node.elts)
    return False


def _snippet(lines: list[str], line_number: int) -> str:
    """The source line, stripped. Empty when out of range."""
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()
    return ""
