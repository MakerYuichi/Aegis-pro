"""Trace a suspicious symbol to its origin across files.

[... full docstring unchanged ...]
"""

from __future__ import annotations

import ast
from pathlib import Path

from loguru import logger

from src.scanner.candidate import (
    CHAIN_NO_SYMBOL,
    CHAIN_TRACED,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_UNTRACEABLE,
    ChainLink,
    ChainResult,
)


MAX_CHAIN_FILES = 5


def build_chain(
    repo_dir: Path | str,
    file_path: str,
    line_number: int,
    symbol: str,
) -> ChainResult:
    """[... docstring unchanged ...]"""
    repo_path = Path(repo_dir).resolve()
    if not repo_path.is_dir():
        return ChainResult(
            status=CHAIN_UNTRACEABLE,
            reason=f"repo_not_found: {repo_path}",
        )

    if not symbol or not symbol.strip():
        return ChainResult(status=CHAIN_NO_SYMBOL, reason="empty symbol")

    if not file_path.endswith(".py"):
        return ChainResult(
            status=CHAIN_UNSUPPORTED_LANGUAGE,
            reason=(
                f"chain tracing is Python-only; got {file_path!r}. "
                f"Non-Python files are not silently skipped — this "
                f"result records the gap."
            ),
        )

    try:
        chain = _trace(
            repo_path=repo_path,
            file_path=file_path,
            line_number=line_number,
            symbol=symbol.strip(),
        )
    except Exception as e:
        logger.error(f"call_chain_builder: tracing failed: {e}")
        return ChainResult(
            status=CHAIN_UNTRACEABLE,
            reason=f"tracing_exception: {e}",
        )

    # A chain that is only the crash site (length 1) is not a trace.
    # The loop never found an origin for the symbol.
    if len(chain) <= 1:
        return ChainResult(
            status=CHAIN_UNTRACEABLE,
            reason=(
                f"could not resolve an origin for {symbol!r} at "
                f"{file_path}:{line_number}"
            ),
        )

    terminal_kind = _terminal_kind(chain[-1])
    return ChainResult(
        status=CHAIN_TRACED,
        chain=chain,
        terminal_symbol=chain[-1].symbol if chain else None,
        terminal_kind=terminal_kind,
        reason=_reason(chain, symbol),
    )


def _trace(
    *,
    repo_path: Path,
    file_path: str,
    line_number: int,
    symbol: str,
) -> list[ChainLink]:
    """Build the chain. Returns [] when the symbol can't be resolved.

    Returns a list whose first element is always the crash site and
    whose later elements are the traced origins. A returned list of
    length 1 means no origin was found — the caller treats that as
    untraceable.
    """
    links: list[ChainLink] = []

    # The front of the chain is always the crash site itself.
    links.append(ChainLink(
        file=file_path,
        line=line_number,
        symbol=symbol,
        reason="usage",
        snippet="",
    ))

    current_file = file_path
    current_symbol = symbol
    current_line = line_number
    visited_files: set[str] = set()

    while True:
        if len(visited_files) >= MAX_CHAIN_FILES:
            break

        origin = _find_origin(
            repo_path=repo_path,
            file_path=current_file,
            symbol=current_symbol,
            before_line=current_line if not visited_files else None,
        )
        if origin is None:
            break

        visited_files.add(current_file)
        links.append(origin)

        # Decide whether to keep tracing.
        next_file, next_symbol = _next_trace_target(
            repo_path=repo_path,
            origin=origin,
        )
        if next_file is None or next_symbol is None:
            break

        # Cycle guard.
        if next_file in visited_files and next_symbol == current_symbol:
            break

        current_file = next_file
        current_symbol = next_symbol
        current_line = origin.line

    return links


def _find_origin(
    *,
    repo_path: Path,
    file_path: str,
    symbol: str,
    before_line: int | None,
) -> ChainLink | None:
    """Find where `symbol` came from in `file_path`.

    Search order (first hit wins):
        1. An assignment `symbol = ...` in this file
        2. A function definition `def symbol(...)` — the origin is
           its return statement
        3. A function parameter named `symbol`

    Returns None when none of these produce a link.
    """
    full_path = (repo_path / file_path).resolve()
    try:
        full_path.relative_to(repo_path)
    except ValueError:
        return None
    if not full_path.is_file():
        return None

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    lines = text.splitlines()
    bare_symbol = symbol.split(".")[-1]
    is_member = "." in symbol

    # Pass 1: assignment
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if _assign_targets_match(node.targets, bare_symbol, is_member):
                snippet = _snippet(lines, node.lineno)
                calls = _all_calls_in(node.value)
                if calls:
                    symbol_name = " | ".join(_call_name(c) for c in calls)
                    reason = (
                        "assignment" if len(calls) == 1
                        else "multi_source_assignment"
                    )
                    return ChainLink(
                        file=file_path,
                        line=node.lineno,
                        symbol=symbol_name,
                        reason=reason,
                        snippet=snippet,
                    )
                return ChainLink(
                    file=file_path,
                    line=node.lineno,
                    symbol=symbol,
                    reason="assignment",
                    snippet=snippet,
                )

        if isinstance(node, ast.AnnAssign):
            if _target_matches(node.target, bare_symbol, is_member):
                snippet = _snippet(lines, node.lineno)
                annotation = _annotation_name(node.annotation)
                return ChainLink(
                    file=file_path,
                    line=node.lineno,
                    symbol=annotation or symbol,
                    reason="annotation",
                    snippet=snippet,
                )

    # Pass 2: function definition — origin is the return statement
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != bare_symbol:
                continue
            returns = [
                child for child in ast.walk(node)
                if isinstance(child, ast.Return) and child.value is not None
            ]
            if not returns:
                # Function with no return value — the origin is the
                # def line itself.
                return ChainLink(
                    file=file_path,
                    line=node.lineno,
                    symbol=bare_symbol,
                    reason="definition",
                    snippet=_snippet(lines, node.lineno),
                )
            first_return = returns[0]
            snippet = _snippet(lines, first_return.lineno)
            calls = _all_calls_in(first_return.value)
            annotation = _annotation_name(node.returns)
            if calls:
                symbol_name = " | ".join(_call_name(c) for c in calls)
                return ChainLink(
                    file=file_path,
                    line=first_return.lineno,
                    symbol=symbol_name,
                    reason="return",
                    snippet=snippet,
                )
            # No call in the return — this is the terminal.
            # Use the annotation as the symbol so _terminal_kind
            # can classify it.
            return ChainLink(
                file=file_path,
                line=first_return.lineno,
                symbol=annotation or "<unknown>",
                reason="return",
                snippet=snippet,
            )

    # Pass 3: parameter
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.arg == bare_symbol:
                    return ChainLink(
                        file=file_path,
                        line=node.lineno,
                        symbol=bare_symbol,
                        reason="parameter",
                        snippet=_snippet(lines, node.lineno),
                    )

    return None


def _next_trace_target(
    *, repo_path: Path, origin: ChainLink
) -> tuple[str | None, str | None]:
    """Given an origin link, decide whether to keep tracing.

    Rules:
        reason == "parameter"       → stop (the type is the annotation)
        reason == "annotation"      → stop (terminal type is known)
        reason == "definition"      → stop (no return value to follow)
        reason == "return" with a
            concrete annotation     → stop (terminal type known)
        reason == "return" with a
            call name               → continue in the defining file
        reason == "assignment" with
            a call name             → continue in the defining file
        reason == "multi_source_assignment"
                                    → stop (DFS is a follow-up)
    """
    if origin.reason in ("parameter", "annotation", "definition"):
        return None, None
    if origin.reason == "multi_source_assignment":
        # The full branch-tracing DFS is a follow-up. Phase 1
        # records the multi-source link but stops tracing.
        return None, None

    symbol = origin.symbol
    if not symbol or "|" in symbol or "[" in symbol or "." in symbol:
        return None, None
    if not symbol.replace("_", "").isalnum():
        return None, None

    def_site = _find_definition(repo_path, symbol)
    if def_site is None:
        return None, None

    # def_site returns (file, function_name). The next _find_origin
    # call looks for that function's definition in that file, which
    # matches Pass 2.
    return def_site


def _find_definition(repo_path: Path, func_name: str) -> tuple[str, str] | None:
    """Search the repo for `def func_name(...)`.

    Returns (file_path, function_name). The next trace iteration
    looks for the function in that file, which hits `_find_origin`'s
    Pass 2 case.
    """
    for py_file in repo_path.rglob("*.py"):
        if not py_file.is_file():
            continue
        if any(part in {
            ".git", "node_modules", "venv", ".venv", "dist", "build",
            "__pycache__", ".tox", ".eggs", "site-packages",
        } for part in py_file.parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != func_name:
                continue
            rel = py_file.relative_to(repo_path).as_posix()
            return rel, func_name

    return None


def _assign_targets_match(
    targets: list[ast.AST], bare: str, is_member: bool
) -> bool:
    return any(_target_matches(t, bare, is_member) for t in targets)


def _target_matches(target: ast.AST, bare: str, is_member: bool) -> bool:
    if isinstance(target, ast.Name):
        return not is_member and target.id == bare
    if isinstance(target, ast.Attribute):
        return is_member and target.attr == bare
    return False


def _all_calls_in(expr: ast.AST) -> list[ast.Call]:
    """Find all top-level Call nodes in an expression.

    For `_cache(id) or _db(id)`, returns both calls.
    For `_cache(id)`, returns one.
    For `a + b`, returns [].
    """
    calls: list[ast.Call] = []
    if isinstance(expr, ast.Call):
        calls.append(expr)
    elif isinstance(expr, ast.BoolOp):
        for value in expr.values:
            calls.extend(_all_calls_in(value))
    elif isinstance(expr, ast.Await):
        calls.extend(_all_calls_in(expr.value))
    # Do not recurse into arbitrary nodes — we want top-level calls,
    # not every call nested inside an expression.
    return calls


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        current = func.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return "<call>"


def _annotation_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _terminal_kind(link: ChainLink) -> str:
    symbol = link.symbol or ""
    if "Optional" in symbol or "None" in symbol:
        return "Optional"
    if symbol and symbol[0].isupper():
        return "Concrete"
    if symbol in ("int", "str", "float", "bool", "list", "dict", "set", "tuple"):
        return "Concrete"
    return "Unknown"


def _reason(chain: list[ChainLink], original_symbol: str) -> str:
    files = list(dict.fromkeys(link.file for link in chain))
    file_list = ", ".join(files)
    terminal = chain[-1] if chain else None
    if terminal is None:
        return f"Could not trace {original_symbol}."

    if len(files) == 1:
        return (
            f"{original_symbol} is used at {chain[0].file}:{chain[0].line} "
            f"and assigned at {terminal.file}:{terminal.line}. "
            f"Single-file chain."
        )

    return (
        f"{original_symbol} is used at {chain[0].file}:{chain[0].line} "
        f"and traced across {len(files)} files ({file_list}). "
        f"Terminal: {terminal.symbol} ({terminal.reason}) at "
        f"{terminal.file}:{terminal.line}."
    )


def _snippet(lines: list[str], line_number: int) -> str:
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()
    return ""
