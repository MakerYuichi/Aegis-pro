"""Trace a suspicious symbol to its origin across files.

The core problem this solves: a crash at `payment_service.py:234`
(`amount = order.total`) is only a bug if `order` can be None. The
chain builder answers "can it be None" by finding where `order`
came from, which function returned it, where that function is
defined, what its return annotation says, and whether it calls
anything that could return None.

Multi-branch assignments produce a single flat chain with multiple
branches. `order = _cache(id) or _db(id)` traces both branches;
their terminal definitions appear in the same chain, each tagged
with a distinct `branch_id` so the Investigator can reason about
which branch was the risky one. The chain is flat — no tree — and
the per-branch detail lives on each link's `branch_id` field, with
a single worst-case rollup on `ChainResult.terminal_kind` for the
scorer to read.

Recursion stops when:
    - the terminal function has a concrete (non-Optional) return
      annotation
    - the branch reaches MAX_CHAIN_FILES unique files
    - a symbol is untraceable

Scope: Python-only. Non-.py files return
status="unsupported_language". Same discipline as NoOpVerifier
returning reason="disabled" — say what you do and don't cover.

The chain builder is *structural*, not *semantic*. It follows
explicit assignments and return statements. It does not reason
about `or` short-circuits, conditional returns through helper
functions, or overloaded names. When it can't trace a symbol, it
stops that branch and records the terminal where it stopped.
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


# How deep the chain can go. Each link is one file. A three-file
# chain is the expected case; five is the cap. The cap is per-path,
# not global: two branches of the same assignment can each walk up
# to MAX_CHAIN_FILES unique files independently.
MAX_CHAIN_FILES = 5


def build_chain(
    repo_dir: Path | str,
    file_path: str,
    line_number: int,
    symbol: str,
) -> ChainResult:
    """Trace `symbol` from (file_path, line_number) back to its origin.

    Args:
        repo_dir:    path to the repo root
        file_path:   repo-relative POSIX path to the crash site
        line_number: 1-indexed line of the crash site
        symbol:      the symbol to trace (e.g. "order", "self.rag")

    Returns:
        A ChainResult. `status` is one of:
            CHAIN_TRACED               — a chain was built
            CHAIN_UNTRACEABLE          — the symbol's origin couldn't
                                         be resolved
            CHAIN_UNSUPPORTED_LANGUAGE — non-.py file
            CHAIN_NO_SYMBOL            — symbol was empty
    """
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
    if len(chain) <= 1:
        return ChainResult(
            status=CHAIN_UNTRACEABLE,
            reason=(
                f"could not resolve an origin for {symbol!r} at "
                f"{file_path}:{line_number}"
            ),
        )

    terminal_kind = _rollup_terminal_kind(chain)
    # The terminal symbol is the last link's symbol — for the
    # multi-branch case that's whichever branch the DFS visited
    # last. The per-branch terminals are on the links themselves.
    terminal_symbol = chain[-1].symbol if chain else None

    return ChainResult(
        status=CHAIN_TRACED,
        chain=chain,
        terminal_symbol=terminal_symbol,
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
    """Build the chain via stack-based DFS.

    Returns the flat list of ChainLinks in DFS traversal order. The
    first element is always the crash site. Subsequent elements are
    origins found along the way, each tagged with a `branch_id` that
    identifies which top-level branch of a multi-source assignment
    they descend from (or 0 for pre-branch links).

    The DFS is needed because a single symbol can have multiple
    origins:

        order = _cache(id) or _db(id)

    The linear loop the previous implementation used could only
    follow one. The stack lets both branches walk independently to
    their terminals, appending to the same flat list.
    """
    crash_link = ChainLink(
        file=file_path,
        line=line_number,
        symbol=symbol,
        reason="usage",
        snippet="",
        terminal_kind="Unknown",
        branch_id=0,
    )
    links: list[ChainLink] = [crash_link]

    # Stack of pending work items. Each item:
    #   (file, line, symbol, branch_id, visited_files_for_this_path)
    #
    # `visited_files` is a frozenset per path, not shared across
    # branches. Two branches of the same assignment can each
    # legitimately visit the same file, and they should not block
    # each other.
    stack: list[tuple[str, int, str, int, frozenset[str]]] = [
        (file_path, line_number, symbol, 0, frozenset()),
    ]
    next_branch_id = 1  # 0 is reserved for pre-branch links

    while stack:
        cur_file, cur_line, cur_symbol, cur_branch_id, visited = stack.pop(0)

        # Per-path depth cap.
        if len(visited) >= MAX_CHAIN_FILES:
            continue

        origins = _find_origins(
            repo_path=repo_path,
            file_path=cur_file,
            symbol=cur_symbol,
            before_line=cur_line if not visited else None,
        )
        if not origins:
            continue

        # If more than one origin, this is a branch point. Assign a
        # fresh branch_id to each origin. If exactly one origin, it
        # inherits the current branch_id — a single-origin step
        # inside a branch stays in that branch.
        if len(origins) > 1:
            assigned_ids = list(
                range(next_branch_id, next_branch_id + len(origins))
            )
            next_branch_id += len(origins)
        else:
            assigned_ids = [cur_branch_id]

        for origin, assigned_id in zip(origins, assigned_ids):
            origin.branch_id = assigned_id
            links.append(origin)

            next_file, next_symbol = _next_trace_target(
                repo_path=repo_path,
                origin=origin,
            )
            if next_file is None or next_symbol is None:
                continue

            # Cycle guard for this specific path.
            if next_file in visited and next_symbol == cur_symbol:
                continue

            stack.append((
                next_file,
                origin.line,
                next_symbol,
                assigned_id,
                visited | {cur_file},
            ))

    return links


def _find_origins(
    *,
    repo_path: Path,
    file_path: str,
    symbol: str,
    before_line: int | None,
) -> list[ChainLink]:
    """Find where `symbol` came from in `file_path`.

    Returns a list of origins. A single assignment or definition
    yields a one-element list. A multi-source assignment
    (`x = a() or b()`) yields one link per source call.

    Search order:
        1. An assignment `symbol = ...` in this file. If the RHS
           contains multiple top-level calls, one link per call.
        2. A function definition `def symbol(...)` — the origin is
           its return statement.
        3. A function parameter named `symbol`.

    Returns [] when none of these produce a link.
    """
    full_path = (repo_path / file_path).resolve()
    try:
        full_path.relative_to(repo_path)
    except ValueError:
        return []
    if not full_path.is_file():
        return []

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines()
    bare_symbol = symbol.split(".")[-1]
    is_member = "." in symbol

    # Pass 1: assignment
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if _assign_targets_match(node.targets, bare_symbol, is_member):
                return _assignment_origins(
                    file_path=file_path,
                    symbol=symbol,
                    node=node,
                    lines=lines,
                )

        if isinstance(node, ast.AnnAssign):
            if _target_matches(node.target, bare_symbol, is_member):
                snippet = _snippet(lines, node.lineno)
                annotation = _annotation_name(node.annotation)
                return [ChainLink(
                    file=file_path,
                    line=node.lineno,
                    symbol=annotation or symbol,
                    reason="annotation",
                    snippet=snippet,
                    terminal_kind=_classify_terminal(annotation or symbol),
                )]

    # Pass 2: function definition
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != bare_symbol:
                continue
            return _definition_origins(
                file_path=file_path,
                node=node,
                lines=lines,
            )

    # Pass 3: parameter
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.arg == bare_symbol:
                    return [ChainLink(
                        file=file_path,
                        line=node.lineno,
                        symbol=bare_symbol,
                        reason="parameter",
                        snippet=_snippet(lines, node.lineno),
                        terminal_kind="Unknown",
                    )]

    return []


def _assignment_origins(
    *,
    file_path: str,
    symbol: str,
    node: ast.Assign,
    lines: list[str],
) -> list[ChainLink]:
    """Build origin links for an assignment node.

    If the RHS has no top-level calls, returns one link with the
    original symbol. If the RHS has one call, returns one link
    naming the call. If the RHS has multiple top-level calls
    (`a() or b()`, `a() if x else b()` is not a BoolOp so this does
    not apply, etc.), returns one link per call.

    The `multi_source_assignment` reason is no longer used here —
    each branch is a real origin with reason `"return"` (the call
    came from a function) or `"assignment"` (the call's target).
    The branch structure is preserved by `branch_id`, assigned by
    `_trace` at the call site, not by `_assignment_origins`.
    """
    snippet = _snippet(lines, node.lineno)
    calls = _all_calls_in(node.value)

    if not calls:
        return [ChainLink(
            file=file_path,
            line=node.lineno,
            symbol=symbol,
            reason="assignment",
            snippet=snippet,
            terminal_kind="Unknown",
        )]

    links: list[ChainLink] = []
    for call in calls:
        call_name = _call_name(call)
        links.append(ChainLink(
            file=file_path,
            line=node.lineno,
            symbol=call_name,
            reason="assignment",
            snippet=snippet,
            terminal_kind="Unknown",
        ))
    return links


def _definition_origins(
    *,
    file_path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
) -> list[ChainLink]:
    """Build origin links for a function definition.

    If the function has no return with a value, returns one link
    naming the def line. Otherwise, one link per call inside the
    first return statement's value. Multi-source returns produce
    multiple links.
    """
    returns = [
        child for child in ast.walk(node)
        if isinstance(child, ast.Return) and child.value is not None
    ]
    if not returns:
        return [ChainLink(
            file=file_path,
            line=node.lineno,
            symbol=node.name,
            reason="definition",
            snippet=_snippet(lines, node.lineno),
            terminal_kind="Unknown",
        )]

    first_return = returns[0]
    snippet = _snippet(lines, first_return.lineno)
    calls = _all_calls_in(first_return.value)
    annotation = _annotation_name(node.returns)

    if calls:
        links: list[ChainLink] = []
        for call in calls:
            links.append(ChainLink(
                file=file_path,
                line=first_return.lineno,
                symbol=_call_name(call),
                reason="return",
                snippet=snippet,
                terminal_kind="Unknown",
            ))
        return links

    # No call in the return — terminal.
    return [ChainLink(
        file=file_path,
        line=first_return.lineno,
        symbol=annotation or "<unknown>",
        reason="return",
        snippet=snippet,
        terminal_kind=_classify_terminal(annotation or ""),
    )]


def _next_trace_target(
    *, repo_path: Path, origin: ChainLink
) -> tuple[str | None, str | None]:
    """Given an origin link, decide whether to keep tracing.

    Rules:
        reason == "parameter"       → stop
        reason == "annotation"      → stop
        reason == "definition"      → stop
        reason == "return" with a
            call name               → continue in the defining file
        reason == "assignment" with
            a call name             → continue in the defining file
    """
    if origin.reason in ("parameter", "annotation", "definition"):
        return None, None

    symbol = origin.symbol
    if not symbol or "|" in symbol or "[" in symbol or "." in symbol:
        return None, None
    if not symbol.replace("_", "").isalnum():
        return None, None

    def_site = _find_definition(repo_path, symbol)
    if def_site is None:
        return None, None
    return def_site


def _find_definition(repo_path: Path, func_name: str) -> tuple[str, str] | None:
    """Search the repo for `def func_name(...)`."""
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

    "Top-level" means the call is a direct operand of the
    expression, not nested inside another call. `_cache(_db(id))`
    returns only `_cache` — `_db` is an argument, not a source.
    """
    calls: list[ast.Call] = []
    if isinstance(expr, ast.Call):
        calls.append(expr)
    elif isinstance(expr, ast.BoolOp):
        for value in expr.values:
            calls.extend(_all_calls_in(value))
    elif isinstance(expr, ast.Await):
        calls.extend(_all_calls_in(expr.value))
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


def _classify_terminal(symbol: str) -> str:
    """Classify a symbol or annotation as Optional / Concrete / Unknown."""
    if not symbol:
        return "Unknown"
    if "Optional" in symbol or "None" in symbol:
        return "Optional"
    if symbol and symbol[0].isupper():
        return "Concrete"
    if symbol in ("int", "str", "float", "bool", "list", "dict", "set", "tuple"):
        return "Concrete"
    return "Unknown"


def _rollup_terminal_kind(chain: list[ChainLink]) -> str:
    """Worst-case terminal_kind across all links.

    Option A of the design: if any link in the chain is Optional,
    the whole chain is Optional. Otherwise if all links with a known
    kind are Concrete, the chain is Concrete. Otherwise Unknown.

    This is the field the scorer reads. Per-branch detail is
    preserved on each ChainLink.terminal_kind.
    """
    kinds = {
        link.terminal_kind for link in chain
        if link.terminal_kind and link.terminal_kind != "Unknown"
    }
    if not kinds:
        return "Unknown"
    if "Optional" in kinds:
        return "Optional"
    if "Concrete" in kinds:
        return "Concrete"
    return "Unknown"


def _reason(chain: list[ChainLink], original_symbol: str) -> str:
    """One-sentence explanation of the chain.

    For single-branch chains, names the files involved. For
    multi-branch chains, names the branch count and the files.
    """
    files = list(dict.fromkeys(link.file for link in chain))
    file_list = ", ".join(files)
    terminal = chain[-1] if chain else None
    if terminal is None:
        return f"Could not trace {original_symbol}."

    branch_ids = {link.branch_id for link in chain if link.branch_id != 0}

    if len(files) == 1 and not branch_ids:
        return (
            f"{original_symbol} is used at {chain[0].file}:{chain[0].line} "
            f"and assigned at {terminal.file}:{terminal.line}. "
            f"Single-file chain."
        )

    if branch_ids:
        return (
            f"{original_symbol} is used at {chain[0].file}:{chain[0].line} "
            f"and traced across {len(files)} files ({file_list}) "
            f"through {len(branch_ids)} branches. "
            f"Worst-case terminal: {_rollup_terminal_kind(chain)}."
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
