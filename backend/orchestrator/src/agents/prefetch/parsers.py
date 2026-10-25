"""
Manifest parsers. Extract pip-installable requirement strings from
any of the manifest kinds `manifest_finder` may return.

This module is imported by BOTH the orchestrator (for tests and
fallback path) and, via a copy, the prefetch container. It must be
stdlib-only and side-effect-free. No imports from `src.*`.

Design:

    parse_manifest(kind: str, text: str) -> list[str] | None

Returns a list of requirement strings pip can install (the same
shape that appears in `requirements.txt`), or None when the manifest
kind is recognized but contains no extractable deps (e.g. a
`setup.cfg` with `[metadata]` only, no `[options] install_requires`).

Raises `ManifestParseError` on genuinely malformed input — a
`setup.py` that's not valid Python, a `pyproject.toml` that isn't
valid TOML, etc. The caller treats that as a prefetch failure.

Four kinds supported:

  - requirements:  one line per requirement, current behavior
  - setup_py:      AST parse, extract `setup(install_requires=...)`
  - setup_cfg:     INI parse, extract `[options] install_requires`
  - pyproject:     TOML parse, extract `[project].dependencies` or
                   `[build-system].requires`

The parsers do NOT resolve version specifiers or hit the network.
That's `prefetch_entrypoint.py`'s job — it groups the returned
strings by index, runs `pip download`, and reports a receipt.
"""
from __future__ import annotations

import ast
import configparser
import io
import re
from pathlib import Path


class ManifestParseError(Exception):
    """Raised when a manifest is recognized but cannot be parsed."""

    def __init__(self, kind: str, reason: str, detail: str = ""):
        self.kind = kind
        self.reason = reason
        self.detail = detail
        msg = f"{kind}: {reason}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


# ── Public dispatch ──────────────────────────────────────────────

def parse_manifest(kind: str, text: str) -> list[str] | None:
    """
    Extract requirement strings from a manifest of the given kind.

    Returns:
      list[str] — pip-installable requirement lines, possibly empty
      None      — manifest recognized, no deps to install (skip)
    Raises:
      ManifestParseError — manifest is malformed
    """
    if kind == "requirements":
        return _parse_requirements(text)
    if kind == "setup_py":
        return _parse_setup_py(text)
    if kind == "setup_cfg":
        return _parse_setup_cfg(text)
    if kind == "pyproject":
        return _parse_pyproject(text)
    # Unknown kind — no parse. Caller decides what to do.
    return None


# ── requirements.txt ─────────────────────────────────────────────

def _parse_requirements(text: str) -> list[str]:
    """
    One non-comment line per requirement. Blank lines skipped.
    Continuation lines (`\\`) are unsupported — we don't see them
    in practice, and the sanitizer in the prefetcher will reject
    them explicitly if they appear.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Reject continuation and options lines. The prefetcher's
        # own sanitize() will double-check this — defense in depth.
        if line.startswith(("\\", "-")):
            raise ManifestParseError(
                "requirements",
                "unsupported_directive",
                f"line: {raw!r}",
            )
        out.append(line)
    return out


# ── setup.py ─────────────────────────────────────────────────────

def _parse_setup_py(text: str) -> list[str] | None:
    """
    AST parse. Walk the module looking for a call to `setup(...)`
    that has an `install_requires=` keyword. Evaluate that keyword's
    value as a literal, or resolve it from module-level assignments.

    Handles:
      setup(install_requires=["a", "b"])
      setup(install_requires=REQUIRES)
      REQUIRES = ["a", "b"]
      setup(install_requires=REQUIRES + ["c"])

    Refuses (returns None):
      setup(install_requires=open("requirements.txt").read().split())
      setup(install_requires=get_requirements())  # any call, not a literal

    Returns None if there's no `setup(...)` call or no
    `install_requires=` keyword.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise ManifestParseError(
            "setup_py", "syntax_error", str(e),
        ) from e

    # First pass: collect module-level literal assignments. Used to
    # resolve `setup(install_requires=REQUIRES)` where REQUIRES is
    # defined above.
    literals: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            # `REQUIRES = [...]` — single target
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                value = _eval_literal(node.value, literals)
                if value is not None:
                    literals[name] = value

    # Second pass: find setup(...) call and its install_requires.
    install_requires_node = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # setup(...) — bare name
        if isinstance(func, ast.Name) and func.id == "setup":
            install_requires_node = _find_kwarg(node, "install_requires")
            if install_requires_node is not None:
                break
        # setuptools.setup(...) — attribute
        elif isinstance(func, ast.Attribute) and func.attr == "setup":
            install_requires_node = _find_kwarg(node, "install_requires")
            if install_requires_node is not None:
                break

    # Find both install_requires and tests_require if present.
    install_requires_node = None
    tests_require_node = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_setup = (
            (isinstance(func, ast.Name) and func.id == "setup")
            or (isinstance(func, ast.Attribute) and func.attr == "setup")
        )
        if not is_setup:
            continue
        if install_requires_node is None:
            install_requires_node = _find_kwarg(node, "install_requires")
        if tests_require_node is None:
            tests_require_node = _find_kwarg(node, "tests_require")

    install_deps = _extract_requires_list(
        install_requires_node, literals, "install_requires",
    )
    test_deps = _extract_requires_list(
        tests_require_node, literals, "tests_require",
    )

    # Merge both lists. The caller (prefetcher) uses the merged
    # list — it needs to know about test deps too, so pytest can
    # import from the repo. The distinction between runtime and
    # test deps is preserved in the parse receipt for telemetry.
    combined: list[str] = []
    seen: set[str] = set()
    for dep in install_deps + test_deps:
        key = dep.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        combined.append(dep)
    return combined


def _extract_requires_list(
    node: ast.AST | None,
    literals: dict[str, object],
    label: str,
) -> list[str]:
    """
    Extract a list of requirement strings from a setup() kwarg.
    Returns [] when the kwarg is absent or not statically evaluable.
    Raises ManifestParseError when the value is present but not a list.
    """
    if node is None:
        return []
    value = _eval_literal(node, literals)
    if value is None or value is _UNRESOLVED:
        # Computed value (function call, dynamic). Return empty —
        # the prefetcher can't extract it, and it's not worth
        # failing the whole parse over.
        return []
    if not isinstance(value, (list, tuple)):
        raise ManifestParseError(
            "setup_py",
            f"{label}_not_list",
            f"got {type(value).__name__}",
        )
    return [item for item in value if isinstance(item, str)]


def _find_kwarg(call_node: ast.Call, name: str) -> ast.AST | None:
    """Find a keyword argument by name. None if not present."""
    for kw in call_node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _eval_literal(
    node: ast.AST,
    env: dict[str, object],
) -> object | None:
    """
    Evaluate a node as a Python literal, resolving module-level
    variables from `env`. Returns None if the node isn't a literal
    or a resolvable name.

    Handles:
      - ast.Constant (str, int, float, bool, None)
      - ast.List, ast.Tuple (recursively)
      - ast.BinOp with Add (list concatenation)
      - ast.Name (looked up in env)
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        parts = [_eval_literal(e, env) for e in node.elts]
        if any(p is _UNRESOLVED for p in parts):
            return _UNRESOLVED
        return [p for p in parts if p is not None]
    if isinstance(node, ast.Tuple):
        parts = [_eval_literal(e, env) for e in node.elts]
        if any(p is _UNRESOLVED for p in parts):
            return _UNRESOLVED
        return tuple(p for p in parts if p is not None)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_literal(node.left, env)
        right = _eval_literal(node.right, env)
        if left is _UNRESOLVED or right is _UNRESOLVED:
            return _UNRESOLVED
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            return list(left) + list(right)
        return _UNRESOLVED
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        return _UNRESOLVED
    # Anything else (Call, Attribute, Subscript, JoinedStr, etc.) is
    # not statically evaluable.
    return _UNRESOLVED


class _Unresolved:
    """Sentinel for expressions we can't evaluate statically."""
    def __repr__(self) -> str:  # pragma: no cover
        return "<UNRESOLVED>"


_UNRESOLVED = _Unresolved()


# ── setup.cfg ────────────────────────────────────────────────────

def _parse_setup_cfg(text: str) -> list[str] | None:
    """
    INI parse. Extract `install_requires` from the `[options]`
    section.

    setup.cfg supports:
        [options]
        install_requires =
            requests>=2.0
            urllib3<2
        ; or with extras
        [options.extras_require]
        dev =
            pytest
    We extract only the base `install_requires`; extras are
    optional installs the test runner won't hit unless they're
    explicitly requested.

    Returns None if the file has no [options] section or no
    install_requires key.
    """
    parser = configparser.ConfigParser()
    # setup.cfg uses `;` and `#` for comments, both standard
    # configparser. Defaults are fine.
    try:
        parser.read_string(text)
    except configparser.Error as e:
        raise ManifestParseError(
            "setup_cfg", "parse_error", str(e),
        ) from e

    if not parser.has_section("options"):
        return None
    if not parser.has_option("options", "install_requires"):
        return None

    out: list[str] = []
    if parser.has_option("options", "install_requires"):
        raw = parser.get("options", "install_requires")
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")):
                continue
            out.append(stripped)

    # Also pick up test extras from [options.extras_require].
    # This is where repos declare test deps when they don't use
    # setup.py's tests_require (many post-2018 repos do this).
    if parser.has_section("options.extras_require"):
        for extra_name in ("test", "tests", "testing"):
            if parser.has_option("options.extras_require", extra_name):
                raw = parser.get("options.extras_require", extra_name)
                for line in raw.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith(("#", ";")):
                        continue
                    out.append(stripped)

    return out if out else None


# ── pyproject.toml ──────────────────────────────────────────────

def _parse_pyproject(text: str) -> list[str] | None:
    """
    TOML parse (via tomllib in 3.11+). Extract dependencies from
    either [project].dependencies (PEP 621) or [build-system].requires.

    Preference:
      1. [project].dependencies
      2. [build-system].requires

    [project].optional-dependencies.* is ignored — those are extras,
    not installed by default.

    Returns None if neither section is present.
    """
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover
        # Python < 3.11. The container is 3.11-slim, and the
        # orchestrator's pyproject says >=3.11, so this shouldn't
        # fire. Honest degrade if it does.
        raise ManifestParseError(
            "pyproject", "tomllib_unavailable",
            "requires Python 3.11+",
        ) from e

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestParseError(
            "pyproject", "parse_error", str(e),
        ) from e

    project = data.get("project") or {}
    deps: list[str] = []
    if isinstance(project.get("dependencies"), list):
        deps.extend(str(d) for d in project["dependencies"])
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        test_extras = optional.get("test") or optional.get("tests") or []
        if isinstance(test_extras, list):
            deps.extend(str(d) for d in test_extras)

    build = data.get("build-system") or {}
    if isinstance(build.get("requires"), list):
        deps.extend(str(d) for d in build["requires"])

    # Deduplicate while preserving order
    seen: set[str] = set()
    combined: list[str] = []
    for d in deps:
        key = d.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        combined.append(d)

    return combined if combined else None
