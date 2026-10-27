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
import builtins as _py_builtins
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


# Every name the interpreter exposes at the top level of the
# `builtins` module. Not a curated allowlist — `dir(builtins)` at
# import time. If the interpreter adds a name in a future Python
# version, it appears here automatically. If a repo shadows a
# builtin with a local variable, this set still contains the
# builtin's name, which is correct: we're classifying the symbol
# as it appears unshadowed in the crash site.
_BUILTIN_NAMES: frozenset[str] = frozenset(dir(_py_builtins))

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

    # A chain of length 1 means "no origin found for this symbol in
    # this file." That's not necessarily a failure — it might mean
    # the symbol is a single-location construct (a CPython module
    # builtin, a Python builtin, an imported name, or an annotated
    # parameter/attribute). Those have a well-defined terminal_kind
    # even though there's no cross-file chain to trace.
    #
    # Only when the symbol is genuinely unresolvable — a bare name
    # with no assignment, no import, no annotation, and no builtin
    # — do we return CHAIN_UNTRACEABLE honestly. That case produces
    # read_chain's empty-chain error, which is the correct
    # degradation: the Investigator has no context to reason with,
    # so it refuses with could_not_determine.
    #
    # The classifier is structural — it asks `builtins` for the
    # full list of interpreter-provided names, walks the file's AST
    # for imports and annotations, and consults the CPython module
    # builtin table. No hardcoded name list.
    if len(chain) <= 1:
        terminal_kind = _classify_single_location_symbol(
            repo_path=repo_path,
            file_path=file_path,
            symbol=symbol,
        )
        if terminal_kind is not None:
            crash_link = chain[0] if chain else ChainLink(
                file=file_path,
                line=line_number,
                symbol=symbol,
                reason="usage",
                snippet="",
                terminal_kind=terminal_kind,
                branch_id=0,
            )
            crash_link.terminal_kind = terminal_kind
            return ChainResult(
                status=CHAIN_TRACED,
                chain=[crash_link],
                terminal_symbol=symbol,
                terminal_kind=terminal_kind,
                reason=(
                    f"{symbol!r} is a single-location symbol "
                    f"({terminal_kind}); no cross-file chain to trace."
                ),
            )
        return ChainResult(
            status=CHAIN_UNTRACEABLE,
            reason=(
                f"could not resolve an origin for {symbol!r} at "
                f"{file_path}:{line_number}"
            ),
        )

    terminal_kind = _rollup_terminal_kind(chain)

    # If the structural rollup is Unknown, ask the classifier.
    #
    # The chain builder produces structural chains — assignments,
    # definitions, parameters. Those are real links, but they don't
    # carry enough information to determine Optional-ness in every
    # case:
    #
    #   - `__doc__` at status_codes.py:116 — the chain link is the
    #     assignment AT the crash line, which is the crash itself.
    #     It tells us nothing about whether `__doc__` can be None.
    #     But the classifier knows from cpython_builtins that
    #     __doc__ is Optional under -OO.
    #
    #   - `self.headers` at cookies.py:470 — the chain link is a
    #     parameter `headers` at line 104 (a different function's
    #     parameter, spuriously matched). The structural rollup is
    #     Unknown. But the classifier resolves `self` to Concrete
    #     via the method-parameter convention.
    #
    # When the chain's structural answer is Unknown, the classifier
    # is a valid second opinion. It doesn't override definite
    # structural answers — those are more specific — but it fills
    # in for the cases where the chain builder had to guess.
    if terminal_kind == "Unknown":
        classifier_kind = _classify_single_location_symbol(
            repo_path=repo_path,
            file_path=file_path,
            symbol=symbol,
        )
        if classifier_kind is not None:
            terminal_kind = classifier_kind

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

    # The symbol's terminal_kind is determined by the ROOT of an
    # attribute chain, not the leaf, for the same reason
    # `self.X: Optional[T]` has its Optional-ness on X but
    # `chardet_version.split` has its Optional-ness on
    # `chardet_version` (the .split method is never None; the
    # object being split might be).
    #
    # Two cases:
    #
    #   1. `self.X` / `cls.X` — the root `self`/`cls` is a method
    #      parameter. Trace the attribute as a whole (`self.X`)
    #      so class-body annotations like `X: Optional[T]` are
    #      caught.
    #
    #   2. `X.Y` where X is anything else — trace the ROOT `X`.
    #      X might be a parameter, a module-level variable, or an
    #      import. Its terminal_kind determines whether X.Y is
    #      safe to access.
    #
    # For `X` (no dot), trace X directly.
    root = symbol.split(".")[0].strip()
    if root in ("self", "cls") or "." not in symbol:
        bare_symbol = symbol.split(".")[-1] if "." in symbol else symbol
        is_member = "." in symbol
    else:
        # `chardet_version.split` → trace `chardet_version`
        bare_symbol = root
        is_member = False

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
    naming the def line. If the first return contains calls, one
    link per call, classified by the function's return annotation.
    Otherwise one link naming the annotation directly.
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
    annotation_kind = _classify_terminal(annotation or "")

    if calls:
        # The function's return annotation is the stronger signal
        # than the shape of any single return statement. A function
        # declared `-> Optional[Order]` can return None from any
        # path, even if the return statement we're looking at
        # happens to return a concrete value.
        links: list[ChainLink] = []
        for call in calls:
            links.append(ChainLink(
                file=file_path,
                line=first_return.lineno,
                symbol=_call_name(call),
                reason="return",
                snippet=snippet,
                terminal_kind=annotation_kind,
            ))
        return links

    # No call in the return — this is a terminal. The link's
    # symbol is the annotation itself (so the rollup can classify
    # it) and its terminal_kind is the annotation's classification.
    return [ChainLink(
        file=file_path,
        line=first_return.lineno,
        symbol=annotation or "<unknown>",
        reason="return",
        snippet=snippet,
        terminal_kind=annotation_kind,
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

def _classify_single_location_symbol(
    *,
    repo_path: Path,
    file_path: str,
    symbol: str,
) -> str | None:
    """Classify a symbol that has no assignment origin in the file.

    Two passes. Pass 1 checks the crash-site file. Pass 2 (only
    entered when pass 1 finds nothing) walks the repo for a
    cross-file import or annotation.

    Pass 1, crash-site file — structural, no name list:

      1a. CPython module builtin (from cpython_builtins.py) → Optional.
      1b. Python builtin (`bare in dir(builtins)`) → Concrete.
      1c. Imported name in this file → Concrete, or Optional if
          under try/except ImportError.
      1d. Annotated parameter or class attribute in this file →
          Optional or Concrete from the annotation.

    Pass 2, whole repo — same structural checks, wider scope,
    only if pass 1 returned None:

      2a. Imported name anywhere in the repo → Concrete, or
          Optional if that import is under try/except ImportError.
      2b. Annotated parameter or class attribute in any file in
          the repo → Optional or Concrete from the annotation.

    Pass 2 exists because the crash-site file is not always the
    file where the symbol was imported or annotated. A function
    that takes `urlparse` as a parameter and receives it from a
    caller in a different module — the import is in the caller's
    module, not the callee's. Same for annotation.

    Both passes are `rglob("*.py")` walks with the same excludes
    as `_find_definition`. The cost is bounded by repo size and
    happens at most once per unresolved symbol. No curated name
    list anywhere.

    Returns Optional, Concrete, or None (unknown).
    """
    if not symbol:
        return None

    # Two views of the symbol:
    #
    #   `full` — the whole expression as it appears in the crash
    #            site. For `chardet_version.split`, full is
    #            "chardet_version.split". For `X`, full is "X".
    #
    #   `root` — the leftmost dotted segment. For
    #            `chardet_version.split`, root is
    #            "chardet_version". For `X`, root is "X". For
    #            `a.b.c`, root is "a".
    #
    # The distinction matters because:
    #   - Attribute access `X.Y` is Optional only if `X` is
    #     Optional (a non-None object's attribute access either
    #     returns a value or raises; it doesn't silently yield
    #     None). So the terminal_kind of the expression is the
    #     terminal_kind of X's root.
    #   - BUT class-body annotations can declare `X: Optional[T]`
    #     on an attribute, so for `self.X` we must check
    #     `_classify_annotated_member(symbol="self.X")` FIRST,
    #     before falling back to classifying `self`.
    #
    # The chain is:
    #   1. Full-symbol annotation (handles `self.X: Optional[T]`)
    #   2. Full-symbol dunder / builtin (handles `__doc__`, `super`)
    #   3. Full-symbol import (rare — `X.Y` isn't imported, but
    #      `from mod import X.Y` isn't valid Python; kept for safety)
    #   4. Root-symbol dunder / builtin / import / annotation
    #
    # `self` and `cls` are special: they're Python method parameter
    # conventions. The instance and the class are never None. This
    # isn't a hardcoded name list — it's the language invariant that
    # any Python method's `self` binding is the instance.
    full = symbol.strip()
    root = full.split(".")[0].strip().rstrip("()").split("[")[0]
    bare_full = full.rstrip("()").split("[")[0].rsplit(".", 1)[-1]

    # ══════════════════════════════════════════════════════════════
    # Pass 1a — Full-symbol annotation (`self.X: Optional[T]`)
    # ══════════════════════════════════════════════════════════════
    if "." in full:
        attr_kind = _classify_annotated_member(
            repo_path=repo_path,
            file_path=file_path,
            symbol=full,
        )
        if attr_kind is not None:
            return attr_kind

    # ══════════════════════════════════════════════════════════════
    # Pass 1b — Full-symbol CPython dunder (`__doc__`)
    # ══════════════════════════════════════════════════════════════
    try:
        from src.agents.cpython_builtins import lookup as _builtin_lookup
        if _builtin_lookup(full) is not None:
            return "Optional"
    except ImportError:
        pass

    # ══════════════════════════════════════════════════════════════
    # Pass 1c — Full-symbol Python builtin (`super`)
    # ══════════════════════════════════════════════════════════════
    if bare_full in _BUILTIN_NAMES:
        return "Concrete"

    # ══════════════════════════════════════════════════════════════
    # Pass 1d — Full-symbol import in crash-site file
    # ══════════════════════════════════════════════════════════════
    import_kind = _classify_import_binding(
        repo_path=repo_path,
        file_path=file_path,
        bare_symbol=bare_full,
    )
    if import_kind is not None:
        return import_kind

    # ══════════════════════════════════════════════════════════════
    # Pass 1e — Full-symbol annotation (bare, not dotted)
    # ══════════════════════════════════════════════════════════════
    if "." not in full:
        attr_kind = _classify_annotated_member(
            repo_path=repo_path,
            file_path=file_path,
            symbol=full,
        )
        if attr_kind is not None:
            return attr_kind

    # ══════════════════════════════════════════════════════════════
    # Pass 1f — self / cls method parameter convention
    # ══════════════════════════════════════════════════════════════
    # If the symbol is `self.X` or `cls.X` and there's no
    # annotation on X, `self`/`cls` are method parameters by
    # convention — the instance and the class, never None.
    if root in ("self", "cls"):
        return "Concrete"

    # ══════════════════════════════════════════════════════════════
    # Pass 2 — Attribute chain: classify the root
    # ══════════════════════════════════════════════════════════════
    # For `X.Y` where X is not self/cls and there's no annotation
    # on X.Y, classify X. If X resolves, X.Y inherits X's
    # terminal_kind (attribute access on non-None doesn't yield
    # None).
    if "." in full and root != full:
        # Root-level dunder
        try:
            if _builtin_lookup(root) is not None:
                return "Optional"
        except (NameError, ImportError):
            pass

        # Root-level Python builtin
        if root in _BUILTIN_NAMES:
            return "Concrete"

        # Root-level import in crash-site file
        root_import = _classify_import_binding(
            repo_path=repo_path,
            file_path=file_path,
            bare_symbol=root,
        )
        if root_import is not None:
            return root_import

        # Root-level annotation in crash-site file
        root_attr = _classify_annotated_member(
            repo_path=repo_path,
            file_path=file_path,
            symbol=root,
        )
        if root_attr is not None:
            return root_attr

        # Root-level cross-file resolution
        root_cross = _classify_across_repo(
            repo_path=repo_path,
            file_path=file_path,
            bare_symbol=root,
            symbol=root,
        )
        if root_cross is not None:
            return root_cross

    # ══════════════════════════════════════════════════════════════
    # Pass 3 — Cross-file resolution for the bare symbol
    # ══════════════════════════════════════════════════════════════
    cross_kind = _classify_across_repo(
        repo_path=repo_path,
        file_path=file_path,
        bare_symbol=bare_full,
        symbol=full,
    )
    if cross_kind is not None:
        return cross_kind

    # Unknown. Honest None.
    return None



def _classify_import_binding(
    *,
    repo_path: Path,
    file_path: str,
    bare_symbol: str,
) -> str | None:
    """Classify whether `bare_symbol` is bound by an import.

    Returns "Concrete" for unconditional imports, "Optional" for
    imports inside try/except ImportError, and None when the
    symbol isn't bound by any import in the file.

    Structural — walks the file's AST for `ast.Import` and
    `ast.ImportFrom` nodes, tracking which are inside try blocks
    with ImportError handlers.

    Does not descend into function bodies. Function-local imports
    are a different code path the chain builder doesn't follow
    yet; treating a function-local import as Concrete would
    overclaim.
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
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return None

    optional_imports: set[str] = set()
    concrete_imports: set[str] = set()

    def _bound_names(import_node: ast.AST) -> list[str]:
        names: list[str] = []
        if isinstance(import_node, ast.Import):
            for alias in import_node.names:
                names.append(alias.asname or alias.name.split(".")[0])
        elif isinstance(import_node, ast.ImportFrom):
            for alias in import_node.names:
                if alias.name == "*":
                    continue
                names.append(alias.asname or alias.name)
        return names

    def _walk_body(body: list[ast.stmt], optional: bool) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                target = optional_imports if optional else concrete_imports
                target.update(_bound_names(stmt))
            elif isinstance(stmt, ast.Try):
                has_import_error = any(
                    _handler_catches_import_error(h)
                    for h in stmt.handlers
                )
                _walk_body(stmt.body, optional or has_import_error)
                # Handlers and orelse/finalbody also contain imports,
                # but in a try/except ImportError shape, only the try
                # body is the import. Descend into other blocks with
                # optional=False for correctness.
                for h in stmt.handlers:
                    _walk_body(h.body, False)
                _walk_body(stmt.orelse, False)
                _walk_body(stmt.finalbody, False)

    _walk_body(tree.body, optional=False)

    if bare_symbol in optional_imports:
        return "Optional"
    if bare_symbol in concrete_imports:
        return "Concrete"
    return None


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    """True if the except clause catches ImportError or ModuleNotFoundError.

    A bare `except:` is treated as catching ImportError — it's
    broader and could hide an ImportError, so the Optional
    classification is the safe choice (the symbol might be None
    after the except branch runs).
    """
    if handler.type is None:
        return True
    names: list[str] = []
    if isinstance(handler.type, ast.Name):
        names.append(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
    return "ImportError" in names or "ModuleNotFoundError" in names


def _classify_annotated_member(
    *,
    repo_path: Path,
    file_path: str,
    symbol: str,
) -> str | None:
    """Classify `symbol` by matching it against annotations in the file.

    Two shapes handled structurally:

      Class attribute:
          class Foo:
              attr: Optional[Bar]    → Optional
              attr: Bar              → Concrete

      Function parameter (any function in the file):
          def f(x: Optional[Bar])    → Optional
          def f(x: Bar)              → Concrete

    For `self.X`, strips `self.` and matches `X` against class
    body annotations. For bare `X`, matches against function
    parameter annotations.

    Returns None when no matching annotation is found. That's the
    honest answer for names the file declares without a type.
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
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return None

    bare = symbol.strip().rstrip("()").split("[")[0].rsplit(".", 1)[-1]
    is_member = "." in symbol

    for node in ast.walk(tree):
        # Class-body attribute annotations. Only relevant when the
        # symbol is `X` or `self.X` — the class attribute X.
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                target = item.target
                if isinstance(target, ast.Name) and target.id == bare:
                    annotation = _annotation_name(item.annotation)
                    if annotation:
                        return _classify_terminal(annotation)

        # Function parameter annotations. Matches both bare
        # parameter names (`def f(x: Optional[T])` for symbol "x")
        # and self-member annotation patterns (`def f(self, x:
        # Optional[T])` for symbol "x"). For `self.X`, the class
        # body already covers it — but for `self.X` with no class
        # body annotation, `self` is a parameter and `X` is a
        # member, so this loop won't match either. That's fine:
        # unknown self-members are honestly Unknown.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in (node.args.args + node.args.kwonlyargs):
                if arg.arg != bare:
                    continue
                if arg.annotation is None:
                    continue
                annotation = _annotation_name(arg.annotation)
                if annotation:
                    return _classify_terminal(annotation)

    return None

def _classify_across_repo(
    *,
    repo_path: Path,
    file_path: str,
    bare_symbol: str,
    symbol: str,
) -> str | None:
    """Walk the repo for a cross-file import or annotation.

    Used when the crash-site file doesn't import or annotate the
    symbol. Two structural checks, both `rglob("*.py")` walks:

      1. Import — a `.py` file in the repo imports `bare_symbol`
         (either `import X` or `from Y import X`). If the import
         is inside try/except ImportError, classify Optional;
         else Concrete.

      2. Annotation — a `.py` file in the repo has a parameter or
         class body annotating `bare_symbol`. Classify by the
         annotation.

    Import wins over annotation. Rationale: an import at module
    scope is a stronger "this name resolves to X" signal than a
    parameter annotation, which only applies within one function
    body. If multiple files import the name, the first non-excluded
    match wins — the classification is the same regardless of
    which file, so first-match is deterministic and cheap.

    The excludes set matches `_find_definition`'s — the cost is
    bounded by repo size, and expensive directories are skipped.

    Returns Optional, Concrete, or None.
    """
    excludes = {
        ".git", "node_modules", "venv", ".venv", "dist", "build",
        "__pycache__", ".tox", ".eggs", "site-packages",
    }

    # Skip the crash-site file itself. Pass 1 already checked it,
    # and re-checking wastes a parse.
    crash_abs = (repo_path / file_path).resolve()

    # ── Cross-file import ─────────────────────────────────────────
    for py_file in repo_path.rglob("*.py"):
        if any(part in excludes for part in py_file.parts):
            continue
        try:
            if py_file.resolve() == crash_abs:
                continue
        except OSError:
            continue

        try:
            rel = py_file.relative_to(repo_path).as_posix()
        except ValueError:
            continue

        kind = _classify_import_binding(
            repo_path=repo_path,
            file_path=rel,
            bare_symbol=bare_symbol,
        )
        if kind is not None:
            return kind

    # ── Cross-file annotation ─────────────────────────────────────
    for py_file in repo_path.rglob("*.py"):
        if any(part in excludes for part in py_file.parts):
            continue
        try:
            if py_file.resolve() == crash_abs:
                continue
        except OSError:
            continue

        try:
            rel = py_file.relative_to(repo_path).as_posix()
        except ValueError:
            continue

        kind = _classify_annotated_member(
            repo_path=repo_path,
            file_path=rel,
            symbol=symbol,
        )
        if kind is not None:
            return kind

    return None



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
