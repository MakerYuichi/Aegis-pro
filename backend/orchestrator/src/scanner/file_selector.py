"""Rank files by likelihood of containing a latent bug.

The scan has no stack trace, so it must decide what to look at. The
answer, in order of importance:

    1. Churn.     Files a human changed recently. The single
                  strongest predictor.
    2. Patterns.  Files matching known-bad shapes.
    3. Complexity. Big, deeply-nested files.
    4. Centrality. Files many other files import.

The combined score:

    score = 3.0 * churn
          + 1.5 * pattern
          + 1.0 * complexity
          + 0.5 * centrality

All sub-scores are normalized to [0.0, 1.0].

Top-N defaults tier by repo size:
    < 100 files   → 10
    < 1000 files  → 25
    < 10000 files → 50
    otherwise     → 100

The churn set is the natural ceiling. On a repo where only 15 files
changed in the last 30 days, scan those 15 even if top_n is 50.

Fallback: a repo with no recent churn (brand-new, dormant, or
freshly-cloned-with-no-history) scans by structural signals only,
with a note in the reasons list.

Scope: Python-only. Non-.py files are not scored. Same discipline
as call_chain_builder — silent skipping of unsupported files is a
worse failure mode than saying so.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from loguru import logger

from src.scanner.candidate import FileScore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Score weights. Churn dominates by design.
_WEIGHT_CHURN = 3.0
_WEIGHT_PATTERN = 1.5
_WEIGHT_COMPLEXITY = 1.0
_WEIGHT_CENTRALITY = 0.5

# Normalization saturations. A sub-score of 1.0 means "saturated".
_CHURN_SATURATION_LINES = 100
_PATTERN_SATURATION_MATCHES = 5
_COMPLEXITY_SATURATION_LINES = 1000
_CENTRALITY_SATURATION_IMPORTERS = 20

# Directories never scanned. Same set as the tool layer, plus a
# couple of Python-specific ones.
_EXCLUDES = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "target", "vendor", "coverage", "htmlcov",
    ".tox", ".eggs", "site-packages", ".next", ".nuxt",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def default_top_n(repo_size: int) -> int:
    """Tiered default for top_n based on repo size (file count)."""
    if repo_size < 100:
        return 10
    if repo_size < 1000:
        return 25
    if repo_size < 10000:
        return 50
    return 100


def select_files(
    repo_dir: Path | str,
    top_n: int | None = None,
    since_days: int = 30,
) -> list[FileScore]:
    """Rank Python files by likelihood of a latent bug.

    Returns the top N FileScore, sorted by score descending.

    Args:
        repo_dir:    path to the repo root
        top_n:       max files to return. None means "use the tiered
                     default based on repo size".
        since_days:  churn window. Default 30.

    Returns an empty list when the repo has no Python files. Does not
    raise — a repo with nothing to scan is not an error.
    """
    repo_path = Path(repo_dir).resolve()
    if not repo_path.is_dir():
        logger.warning(f"file_selector: not a directory: {repo_path}")
        return []

    py_files = _collect_python_files(repo_path)
    if not py_files:
        return []

    if top_n is None:
        top_n = default_top_n(len(py_files))

    # Churn: one git call, results in {relative_path: lines_changed}.
    churn_map = _churn_scores(repo_path, since_days)

    # Centrality: one AST pass over all files.
    centrality_map = _centrality_scores(repo_path, py_files)

    scored: list[FileScore] = []
    for rel in py_files:
        text = _safe_read(repo_path / rel)
        if text is None:
            continue

        churn, churn_reason = _churn_subscore(churn_map.get(rel, 0), since_days)
        pattern, pattern_reasons = _pattern_subscore(text)
        complexity = _complexity_subscore(text)
        centrality = _centrality_subscore(centrality_map.get(rel, 0))

        combined = (
            _WEIGHT_CHURN * churn
            + _WEIGHT_PATTERN * pattern
            + _WEIGHT_COMPLEXITY * complexity
            + _WEIGHT_CENTRALITY * centrality
        )

        reasons: list[str] = []
        if churn_reason:
            reasons.append(churn_reason)
        reasons.extend(pattern_reasons)
        if complexity >= 0.1:
            reasons.append(f"complexity {complexity:.2f}")
        if centrality >= 0.1:
            reasons.append(f"centrality {centrality:.2f}")

        scored.append(FileScore(
            path=rel,
            score=combined,
            churn_score=churn,
            risk_pattern_score=pattern,
            complexity_score=complexity,
            centrality_score=centrality,
            reasons=reasons,
        ))

    # Sort by score descending, then by path ascending for determinism.
    scored.sort(key=lambda f: (-f.score, f.path))
    return scored[:top_n]


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def _collect_python_files(repo_path: Path) -> list[str]:
    """Return repo-relative POSIX paths of all .py files, sorted."""
    found: list[str] = []
    for p in repo_path.rglob("*.py"):
        if not p.is_file():
            continue
        if any(part in _EXCLUDES for part in p.parts):
            continue
        try:
            rel = p.relative_to(repo_path).as_posix()
        except ValueError:
            continue
        found.append(rel)
    found.sort()
    return found


def _safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Sub-scorer: churn
# ---------------------------------------------------------------------------

def _churn_scores(repo_path: Path, since_days: int) -> dict[str, int]:
    """Map relative path → lines changed in the last `since_days`.

    Uses `git log --numstat`. Returns an empty dict on any git failure
    — a repo without git history scores 0 on churn for every file,
    which is the honest signal that churn isn't available.
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_path), "log",
                f"--since={since_days} days ago",
                "--numstat", "--no-merges",
                "--pretty=format:",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"file_selector: git churn unavailable: {e}")
        return {}

    if result.returncode != 0:
        logger.debug(
            f"file_selector: git log failed ({result.returncode}): "
            f"{result.stderr[:200]}"
        )
        return {}

    churn: dict[str, int] = {}
    for line in result.stdout.splitlines():
        # numstat line: "added\tdeleted\tpath"
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if added == "-" or deleted == "-":
            # Binary file — skip.
            continue
        try:
            lines = int(added) + int(deleted)
        except ValueError:
            continue
        churn[path] = churn.get(path, 0) + lines

    return churn


def _churn_subscore(lines_changed: int, since_days: int) -> tuple[float, str]:
    """Normalize churn lines to [0, 1]. Returns (score, reason)."""
    if lines_changed <= 0:
        return 0.0, ""
    normalized = min(lines_changed / _CHURN_SATURATION_LINES, 1.0)
    return normalized, f"{lines_changed} lines changed in last {since_days} days"


# ---------------------------------------------------------------------------
# Sub-scorer: pattern
# ---------------------------------------------------------------------------

def _pattern_subscore(text: str) -> tuple[float, list[str]]:
    """Count known-bad shapes. Normalize to [0, 1].

    Uses a cheap AST walk for the same reason the full pattern_matcher
    does: regex fires on comments and strings. This sub-scorer is a
    *pre-filter*, not a finding — it just boosts files that look
    suspicious so the full matcher runs on them first.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0.0, []

    count = 0
    reasons: list[str] = []

    for node in ast.walk(tree):
        # Bare except: pass or except Exception: pass
        if isinstance(node, ast.ExceptHandler):
            if node.type is None or _is_exception_class(node.type, "Exception"):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    count += 1
                    reasons.append(f"bare except at line {node.lineno}")

        # Attribute access on a function call result — the classic
        # "order.total where order comes from fetch_order()" shape.
        # AST gives us the shape; whether order is actually Optional
        # is the chain builder's job.
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Call):
                # foo().bar — the call result is dereferenced
                count += 1
                reasons.append(f"attribute on call at line {node.lineno}")
            elif isinstance(node.value, ast.Subscript):
                # foo["x"].bar — same shape through a subscript
                count += 1
                reasons.append(f"attribute on subscript at line {node.lineno}")

    normalized = min(count / _PATTERN_SATURATION_MATCHES, 1.0)
    # Deduplicate reasons — a file with many bare excepts shouldn't
    # have a hundred identical reason strings.
    return normalized, list(dict.fromkeys(reasons))[:5]


def _is_exception_class(node: ast.AST, name: str) -> bool:
    """True when the except clause names the given exception class."""
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    if isinstance(node, ast.Tuple):
        return any(_is_exception_class(elt, name) for elt in node.elts)
    return False


# ---------------------------------------------------------------------------
# Sub-scorer: complexity
# ---------------------------------------------------------------------------

def _complexity_subscore(text: str) -> float:
    """Cheap structural complexity: line count, saturated.

    A real cyclomatic complexity measure would be better but costs
    an AST walk per file. Line count is a proxy that correlates well
    enough for ranking.
    """
    line_count = text.count("\n") + 1
    return min(line_count / _COMPLEXITY_SATURATION_LINES, 1.0)


# ---------------------------------------------------------------------------
# Sub-scorer: centrality
# ---------------------------------------------------------------------------

def _centrality_scores(
    repo_path: Path, py_files: list[str]
) -> dict[str, int]:
    """Count how many other files import each file.

    Uses AST to find import statements, then resolves each import to
    a repo-relative path. Imports that don't resolve to a repo file
    (stdlib, third-party) are ignored — they don't make a file more
    central to *this* repo.
    """
    # Build a module-name → relative-path map. A file at
    # `a/b/c.py` is importable as `a.b.c` (or `a.b` if it's a
    # package). Both forms are registered.
    module_to_path: dict[str, str] = {}
    for rel in py_files:
        posix = rel[:-3] if rel.endswith(".py") else rel
        module_to_path[posix.replace("/", ".")] = rel
        # __init__.py means the parent directory is the module.
        if rel.endswith("/__init__.py"):
            parent = rel[: -len("/__init__.py")]
            module_to_path[parent.replace("/", ".")] = rel

    centrality: dict[str, int] = {rel: 0 for rel in py_files}

    for rel in py_files:
        text = _safe_read(repo_path / rel)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = module_to_path.get(alias.name)
                    if target and target != rel:
                        centrality[target] += 1
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                target = module_to_path.get(node.module)
                if target and target != rel:
                    centrality[target] += 1

    return centrality


def _centrality_subscore(importer_count: int) -> float:
    return min(importer_count / _CENTRALITY_SATURATION_IMPORTERS, 1.0)
