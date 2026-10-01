"""
Deterministic repo tools for the Investigator agent.

Three tools, no more for v1:
    read_file(repo, path, start_line?, end_line?)
    read_symbol(repo, path, symbol_name)
    search_codebase(repo, pattern, file_glob?)

Design notes:

- Every tool returns a ToolResult, never raises for a user-facing error.
  A missing file, a symbol that isn't found, a bad regex — all of these
  are observations the agent should see, not exceptions the pipeline
  has to catch. Exceptions are reserved for genuine bugs.

- Every tool caps its own output. The agent does not get to ask for
  "the whole file" and blow the context window. read_file caps at
  MAX_FILE_CHARS. search_codebase caps at MAX_MATCHES. read_symbol
  caps at MAX_SYMBOL_LINES. If the cap binds, the result carries a
  `truncated` flag so the agent knows what it's missing.

- read_symbol is the one tool with real logic. For Python, it uses the
  ast module to find the definition or assignment. For everything else,
  it uses a line-scan heuristic that looks for `def <name>`, `class
  <name>`, `<name> =`, `function <name>`, `const <name> =`, etc. The
  observation records which resolver ran so the agent knows how much
  to trust the result.

- No tool touches the network. No tool writes to disk. No tool calls
  an LLM. All three are pure functions of (repo, args).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Caps. These are the hard limits the design doc commits to in §9.
# ---------------------------------------------------------------------------

MAX_FILE_CHARS = 40_000        # ~10k tokens; roughly 800–1000 lines
MAX_SYMBOL_LINES = 60          # enclosing scope of a symbol
MAX_MATCHES = 50               # search_codebase results
MAX_MATCH_LINE_CHARS = 500     # per-line cap in search results
MAX_PATH_DEPTH = 12            # reject path traversal beyond this


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """
    Uniform return shape for every tool.

    The agent's observation is built from this. `ok` is False for
    user-facing failures (file not found, symbol not found, bad regex);
    the tool does not raise for those. `error` carries the reason when
    ok is False. `truncated` is True when the result was capped and
    the agent is seeing a partial answer.
    """
    ok: bool
    tool: str
    args: dict
    result: str = ""
    error: str | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_observation(self, iteration: int) -> dict:
        """Serialize to the shape the agent loop stores in its history."""
        return {
            "iteration": iteration,
            "tool": self.tool,
            "args": self.args,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "truncated": self.truncated,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_resolve(repo: str | Path, path: str) -> tuple[Path | None, str | None]:
    """
    Resolve `path` under `repo`, refusing traversal outside the repo
    and refusing paths deeper than MAX_PATH_DEPTH.

    Returns (resolved_path, None) on success, (None, reason) on refusal.
    """
    if not path:
        return None, "empty_path"

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return None, "repo_not_found"

    # Reject absolute paths and obvious traversal up front. Path.resolve
    # would catch these too, but the reason string is more useful if we
    # detect them by shape.
    candidate = Path(path)
    if candidate.is_absolute():
        return None, "absolute_path_rejected"

    if len(candidate.parts) > MAX_PATH_DEPTH:
        return None, "path_too_deep"

    try:
        resolved = (repo_path / candidate).resolve()
    except (OSError, RuntimeError) as e:
        return None, f"path_resolve_failed: {e}"

    # Confirm the resolved path is inside the repo. This catches
    # symlinks that escape, `..` traversal, and any other trickery.
    try:
        resolved.relative_to(repo_path)
    except ValueError:
        return None, "path_escapes_repo"

    return resolved, None


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

async def read_file(
    repo: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ToolResult:
    """
    Read a slice of a file. Line numbers are 1-indexed and inclusive.

    If start_line/end_line are omitted, reads the whole file (capped
    at MAX_FILE_CHARS). If only start_line is given, reads to EOF. If
    only end_line is given, reads from 1.

    The result includes line numbers so the agent can reference them
    in a subsequent diagnose turn.
    """
    args = {
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }

    resolved, reason = _safe_resolve(repo, path)
    if resolved is None:
        return ToolResult(ok=False, tool="read_file", args=args, error=reason)

    if not resolved.is_file():
        return ToolResult(
            ok=False, tool="read_file", args=args,
            error=f"not_a_file: {path}",
        )

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ToolResult(
            ok=False, tool="read_file", args=args,
            error=f"read_failed: {e}",
        )

    lines = text.splitlines()
    total = len(lines)

    # Apply the line window. Defaults preserve "read the whole file"
    # semantics but always bounded by the char cap below.
    start = max(1, start_line or 1)
    end = min(total, end_line or total)

    if start > total:
        return ToolResult(
            ok=False, tool="read_file", args=args,
            error=f"start_line {start} exceeds file length {total}",
            metadata={"total_lines": total},
        )

    if end < start:
        return ToolResult(
            ok=False, tool="read_file", args=args,
            error=f"end_line {end} < start_line {start}",
            metadata={"total_lines": total},
        )

    window = lines[start - 1 : end]
    numbered = "\n".join(
        f"{start + i:5d}  {line}" for i, line in enumerate(window)
    )

    truncated = False
    if len(numbered) > MAX_FILE_CHARS:
        numbered = numbered[:MAX_FILE_CHARS]
        truncated = True

    return ToolResult(
        ok=True,
        tool="read_file",
        args=args,
        result=numbered,
        truncated=truncated,
        metadata={
            "total_lines": total,
            "start_line": start,
            "end_line": end,
            "lines_returned": end - start + 1,
        },
    )


# ---------------------------------------------------------------------------
# read_symbol
# ---------------------------------------------------------------------------

# Language → file extensions. Used only for the search_codebase default
# glob and as a hint for the resolver. read_symbol itself is driven by
# the file extension of `path`.
_PY_EXT = {".py"}
_JS_TS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_GO_EXT = {".go"}
_JAVA_EXT = {".java"}
_RUST_EXT = {".rs"}


async def read_symbol(repo: str, path: str, symbol_name: str) -> ToolResult:
    """
    Find the definition or assignment of a symbol in a file.

    Python: uses ast for precision. Handles:
      - `def foo(...)`        → the function body
      - `class Foo`           → the class body (capped)
      - `self.rag = ...`      → the assignment statement
      - `NAME = ...`          → the module-level assignment
      - `import foo`          → the import line
    The enclosing scope of the symbol is returned, capped at
    MAX_SYMBOL_LINES. For nested members (self.x), the nearest
    assignment inside the class is returned.

    Non-Python: line-scan heuristic. Looks for lines matching the
    language's definition patterns and returns the matching line plus
    a window of context. Marked as best-effort in the result metadata.

    Returns ToolResult(ok=False, error="symbol_not_found") if nothing
    matches. That's an observation, not an error — the agent may try
    a different name or a different file.
    """
    args = {"path": path, "symbol_name": symbol_name}

    if not symbol_name:
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error="empty_symbol_name",
        )

    resolved, reason = _safe_resolve(repo, path)
    if resolved is None:
        return ToolResult(ok=False, tool="read_symbol", args=args, error=reason)

    if not resolved.is_file():
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error=f"not_a_file: {path}",
        )

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error=f"read_failed: {e}",
        )

    suffix = resolved.suffix.lower()

    if suffix in _PY_EXT:
        return _read_symbol_python(resolved, text, symbol_name, args)

    # Non-Python: line-scan.
    return _read_symbol_heuristic(resolved, text, symbol_name, args, suffix)


def _read_symbol_python(
    path: Path, text: str, symbol_name: str, args: dict
) -> ToolResult:
    """
    AST-based resolver for Python. Finds the definition or assignment
    of `symbol_name` and returns the enclosing node's source, capped.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error=f"syntax_error: {e}",
        )

    lines = text.splitlines()
    # Strip a leading `self.` so callers can pass either form.
    bare = symbol_name.split(".")[-1]
    is_member = symbol_name.startswith("self.") or "." in symbol_name

    matches: list[tuple[int, int, ast.AST, str]] = []
    # (start_line, end_line, node, kind)

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):
            if node.name == bare:
                matches.append((node.lineno, node.end_lineno or node.lineno, node, "def"))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            if node.name == bare:
                matches.append((node.lineno, node.end_lineno or node.lineno, node, "async_def"))
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef):
            if node.name == bare:
                matches.append((node.lineno, node.end_lineno or node.lineno, node, "class"))
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign):
            for target in node.targets:
                # Match either `NAME = ...` or `self.NAME = ...`
                if isinstance(target, ast.Name) and target.id == bare and not is_member:
                    matches.append((node.lineno, node.end_lineno or node.lineno, node, "assign"))
                elif (
                    isinstance(target, ast.Attribute)
                    and target.attr == bare
                    and is_member
                ):
                    matches.append((node.lineno, node.end_lineno or node.lineno, node, "assign_member"))
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == bare and not is_member:
                matches.append((node.lineno, node.end_lineno or node.lineno, node, "annassign"))
            elif (
                isinstance(target, ast.Attribute)
                and target.attr == bare
                and is_member
            ):
                matches.append((node.lineno, node.end_lineno or node.lineno, node, "annassign_member"))
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == bare or alias.asname == bare:
                    matches.append((node.lineno, node.lineno, node, "import"))
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            for alias in node.names:
                if alias.name == bare or alias.asname == bare:
                    matches.append((node.lineno, node.lineno, node, "import_from"))
            self.generic_visit(node)

    Visitor().visit(tree)

    if not matches:
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error=f"symbol_not_found: {symbol_name}",
            metadata={"resolver": "python_ast", "file": str(path.name)},
        )

    # Prefer an assignment for `self.x` queries — that's the "where is
    # this initialized" case from #105. For bare names, prefer def,
    # then class, then assign, then import.
    if is_member:
        priority = {"assign_member": 0, "annassign_member": 1}
    else:
        priority = {"def": 0, "async_def": 1, "class": 2, "assign": 3,
                    "annassign": 4, "import": 5, "import_from": 6}

    matches.sort(key=lambda m: (priority.get(m[3], 99), m[0]))
    start_line, end_line, _, kind = matches[0]

    # Cap the returned span.
    span = end_line - start_line + 1
    truncated = False
    if span > MAX_SYMBOL_LINES:
        end_line = start_line + MAX_SYMBOL_LINES - 1
        truncated = True

    window = lines[start_line - 1 : end_line]
    numbered = "\n".join(
        f"{start_line + i:5d}  {line}" for i, line in enumerate(window)
    )

    return ToolResult(
        ok=True,
        tool="read_symbol",
        args=args,
        result=numbered,
        truncated=truncated,
        metadata={
            "resolver": "python_ast",
            "kind": kind,
            "start_line": start_line,
            "end_line": end_line,
            "all_matches": [
                {"line": m[0], "kind": m[3]} for m in matches[:5]
            ],
        },
    )


# Patterns for the non-Python heuristic. Each is (regex, kind).
_DEF_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "js": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+{name}\b"), "function"),
        (re.compile(r"^\s*(?:export\s+)?class\s+{name}\b"), "class"),
        (re.compile(r"^\s*(?:export\s+)?const\s+{name}\s*="), "const"),
        (re.compile(r"^\s*(?:export\s+)?let\s+{name}\s*="), "let"),
        (re.compile(r"^\s*(?:export\s+)?var\s+{name}\s*="), "var"),
        (re.compile(r"^\s*(?:export\s+)?(?:type|interface)\s+{name}\b"), "type"),
    ],
    "go": [
        (re.compile(r"^\s*func\s+(?:\([^)]*\)\s+)?{name}\b"), "func"),
        (re.compile(r"^\s*type\s+{name}\b"), "type"),
        (re.compile(r"^\s*var\s+{name}\b"), "var"),
        (re.compile(r"^\s*const\s+{name}\b"), "const"),
    ],
    "java": [
        (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?[\w<>\[\],\s]+\s+{name}\s*\("), "method"),
        (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?class\s+{name}\b"), "class"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub\s+)?fn\s+{name}\b"), "fn"),
        (re.compile(r"^\s*(?:pub\s+)?struct\s+{name}\b"), "struct"),
        (re.compile(r"^\s*(?:pub\s+)?enum\s+{name}\b"), "enum"),
        (re.compile(r"^\s*(?:pub\s+)?const\s+{name}\b"), "const"),
        (re.compile(r"^\s*(?:pub\s+)?static\s+{name}\b"), "static"),
    ],
}


def _lang_bucket(suffix: str) -> str | None:
    if suffix in _JS_TS_EXT:
        return "js"
    if suffix in _GO_EXT:
        return "go"
    if suffix in _JAVA_EXT:
        return "java"
    if suffix in _RUST_EXT:
        return "rust"
    return None


def _read_symbol_heuristic(
    path: Path, text: str, symbol_name: str, args: dict, suffix: str
) -> ToolResult:
    """
    Line-scan resolver for non-Python languages. Best-effort. Returns
    the matching line plus a ±10-line window, capped.
    """
    bucket = _lang_bucket(suffix)
    if bucket is None:
        return ToolResult(
            ok=False, tool="read_symbol", args=args,
            error=f"unsupported_language: {suffix or 'no_extension'}",
            metadata={"resolver": "heuristic"},
        )

    bare = symbol_name.split(".")[-1]
    patterns = [
        (re.compile(p.pattern.replace("{name}", re.escape(bare))), kind)
        for p, kind in _DEF_PATTERNS[bucket]
    ]

    lines = text.splitlines()
    for i, line in enumerate(lines):
        for pattern, kind in patterns:
            if pattern.search(line):
                start = max(0, i - 5)
                end = min(len(lines), i + 11)
                window = lines[start:end]
                numbered = "\n".join(
                    f"{start + j + 1:5d}  {l}" for j, l in enumerate(window)
                )
                return ToolResult(
                    ok=True,
                    tool="read_symbol",
                    args=args,
                    result=numbered,
                    truncated=False,
                    metadata={
                        "resolver": "heuristic",
                        "language": bucket,
                        "kind": kind,
                        "start_line": start + 1,
                        "end_line": end,
                        "best_effort": True,
                    },
                )

    return ToolResult(
        ok=False, tool="read_symbol", args=args,
        error=f"symbol_not_found: {symbol_name}",
        metadata={"resolver": "heuristic", "language": bucket},
    )


# ---------------------------------------------------------------------------
# search_codebase
# ---------------------------------------------------------------------------

# Directory names we never want to search. Keeps the agent from wasting
# iterations on vendored code, build output, or test fixtures.
_SEARCH_EXCLUDES = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "target", "vendor", "coverage", "htmlcov",
    ".next", ".nuxt", ".turbo", ".parcel-cache",
}


async def search_codebase(
    repo: str, pattern: str, file_glob: str | None = None
) -> ToolResult:
    """
    Search the repo for a regex pattern. Returns up to MAX_MATCHES
    hits, each with path, line number, and the matching line (capped
    at MAX_MATCH_LINE_CHARS).

    `pattern` is a Python re pattern. Case-sensitive by default — the
    agent can prefix `(?i)` if it wants case-insensitive.

    `file_glob` is a fnmatch-style glob applied to the relative path
    (e.g. "*.py", "src/**/*.ts"). None means "all text files".
    """
    args = {"pattern": pattern, "file_glob": file_glob}

    if not pattern:
        return ToolResult(
            ok=False, tool="search_codebase", args=args, error="empty_pattern",
        )

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return ToolResult(
            ok=False, tool="search_codebase", args=args,
            error=f"invalid_regex: {e}",
        )

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return ToolResult(
            ok=False, tool="search_codebase", args=args, error="repo_not_found",
        )

    import fnmatch

    matches: list[dict] = []
    truncated = False

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue

        # Skip excluded directories.
        if any(part in _SEARCH_EXCLUDES for part in file_path.parts):
            continue

        rel = file_path.relative_to(repo_path).as_posix()

        if file_glob and not fnmatch.fnmatch(rel, file_glob):
            continue

        # Skip likely-binary files by extension. Best-effort; the
        # read below uses errors="replace" so a stray binary won't
        # crash the search, but it also won't be useful.
        if file_path.suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
            ".tar", ".gz", ".woff", ".woff2", ".ttf", ".otf", ".so",
            ".dylib", ".dll", ".exe", ".pyc", ".class", ".jar", ".wasm",
        }:
            continue

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                matches.append({
                    "path": rel,
                    "line_number": line_number,
                    "line": line[:MAX_MATCH_LINE_CHARS],
                })
                if len(matches) >= MAX_MATCHES:
                    truncated = True
                    break

        if truncated:
            break

    if not matches:
        return ToolResult(
            ok=True,
            tool="search_codebase",
            args=args,
            result="",
            metadata={"match_count": 0},
        )

    rendered = "\n".join(
        f"{m['path']}:{m['line_number']}: {m['line']}" for m in matches
    )

    return ToolResult(
        ok=True,
        tool="search_codebase",
        args=args,
        result=rendered,
        truncated=truncated,
        metadata={"match_count": len(matches)},
    )
