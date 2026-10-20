"""
Find a repo's dependency manifest.

The verifier needs to know which file to prefetch. A repo can have
several candidates (requirements.txt at root, pyproject.toml in a
subdirectory, package.json alongside Python code in a monorepo).
This module picks the primary manifest by a deterministic walk.

Precedence, Python:

  1. requirements.txt or requirements-*.txt at root or in a
     subdirectory (shallowest first, alphabetical tiebreak)
  2. pyproject.toml with a [project] or [build-system] table
  3. setup.py
  4. setup.cfg

Precedence, Node:

  1. package-lock.json or yarn.lock or pnpm-lock.yaml at root or
     in a subdirectory
  2. package.json

If none is found, the repo has no dependency manifest and the
verifier skips prefetch entirely. That's the correct degradation
for a small script repo.

The walk never descends into hidden directories, virtualenvs,
node_modules, or build/dist. Same exclusions the test-runner
detector uses — one convention, applied in both places.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_EXCLUDES = frozenset({
    "venv", ".venv", "env", ".env",
    "node_modules", "build", "dist",
    "target", ".tox", "__pycache__",
    ".git", ".hg", ".svn",
})


@dataclass(frozen=True)
class ManifestRef:
    """
    A manifest found in the repo.

    path: the file path relative to the repo root.
    kind: "requirements" | "pyproject" | "setup_py" | "setup_cfg" |
          "package_lock" | "package_json"
    """
    path: Path
    kind: str


def find_manifest(repo_dir: Path, language: str) -> ManifestRef | None:
    """
    Return the primary dependency manifest for the repo, or None.

    The returned path is relative to repo_dir. The caller is
    responsible for resolving it — manifest paths stay relative
    because the same repo is read from a container path
    (/verifier-workdir/<uuid>/repo) and a host path
    (/Users/.../verifier-workdir/<uuid>/repo). Returning a
    relative path lets both views compute their own absolute.
    """
    lang = (language or "").lower()
    if lang.startswith("node"):
        return _find_node(repo_dir)
    return _find_python(repo_dir)


def _find_python(repo_dir: Path) -> ManifestRef | None:
    # Pass 1: requirements*.txt. Shallowest path wins; among
    # equally-shallow paths, alphabetical order wins.
    candidates: list[tuple[int, str, Path]] = []
    for found in _walk_files(repo_dir):
        if not found.name.startswith("requirements"):
            continue
        if not found.name.endswith(".txt"):
            continue
        rel = found.relative_to(repo_dir)
        candidates.append((len(rel.parts), rel.as_posix(), rel))
    if candidates:
        candidates.sort()
        return ManifestRef(path=candidates[0][2], kind="requirements")

    # Pass 2: pyproject.toml with a [project] or [build-system]
    # table. A pyproject without either isn't a dependency
    # manifest.
    for found in _walk_named(repo_dir, "pyproject.toml"):
        if _pyproject_has_dependency_section(found):
            return ManifestRef(
                path=found.relative_to(repo_dir),
                kind="pyproject",
            )

    # Pass 3: setup.py
    for found in _walk_named(repo_dir, "setup.py"):
        return ManifestRef(
            path=found.relative_to(repo_dir), kind="setup_py",
        )

    # Pass 4: setup.cfg
    for found in _walk_named(repo_dir, "setup.cfg"):
        return ManifestRef(
            path=found.relative_to(repo_dir), kind="setup_cfg",
        )

    return None


def _find_node(repo_dir: Path) -> ManifestRef | None:
    # Pass 1: lock files. Preferred over package.json because
    # they pin exact versions.
    lock_names = (
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    )
    for name in lock_names:
        for found in _walk_named(repo_dir, name):
            return ManifestRef(
                path=found.relative_to(repo_dir),
                kind="package_lock",
            )

    # Pass 2: package.json
    for found in _walk_named(repo_dir, "package.json"):
        return ManifestRef(
            path=found.relative_to(repo_dir),
            kind="package_json",
        )

    return None


def _walk_files(repo_dir: Path):
    """Yield every regular file under repo_dir, skipping excluded
    directories."""
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(p in _EXCLUDES for p in path.relative_to(repo_dir).parts):
            continue
        yield path


def _walk_named(repo_dir: Path, filename: str):
    """Yield every file with the given name, shallowest first."""
    matches = []
    for path in _walk_files(repo_dir):
        if path.name != filename:
            continue
        rel = path.relative_to(repo_dir)
        matches.append((len(rel.parts), rel.as_posix(), path))
    matches.sort()
    for _depth, _str, path in matches:
        yield path


def _pyproject_has_dependency_section(path: Path) -> bool:
    """
    True when the pyproject has a [project] or [build-system]
    table — i.e. it declares dependencies or a build backend.
    A pyproject with only [tool.*] sections isn't a manifest.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # Cheap textual check — parse errors and edge cases fall
    # through to False, which is the safe default.
    for marker in ("[project]", "[build-system]", "[tool.poetry]"):
        if marker in text:
            return True
    return False
