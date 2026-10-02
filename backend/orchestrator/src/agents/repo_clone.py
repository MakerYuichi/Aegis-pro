"""
Clone-once helper for the incident pipeline.

The Investigator is the first stage that needs filesystem access.
It clones the target repo here and writes the path into
context["repo_workdir"]. The Verifier reads that same key and
reuses the checkout instead of cloning again.

Design notes:

- One clone per incident. Not per stage.
- The clone respects `commit_sha` if given, but today nothing sets
  it — everyone passes "HEAD". When commit-pinning lands, the
  Watcher should set context["commit_sha"] and both stages will
  resolve the same commit by construction.
- The caller owns cleanup. This module returns a path; it does not
  schedule its own removal. Whoever runs last that needs the
  directory removes it. In the current pipeline that's the
  coordinator, after the Verifier stage.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import os     
import uuid
from pathlib import Path

from loguru import logger

from src.config import settings


def is_local_path(repo: str) -> bool:
    """True when `repo` is already a filesystem path we can read."""
    if not repo:
        return False
    return repo.startswith("/") or repo.startswith("./") or repo.startswith("../")


def repo_url(repo: str) -> str:
    """Build the clone URL from an "owner/repo" name."""
    if repo.startswith("http") or repo.startswith("git@"):
        return repo
    return f"https://github.com/{repo}.git"


def _base_dir() -> Path:
    """
    Where clones go. Honours settings.INVESTIGATOR_WORKDIR when set,
    otherwise falls back to the system temp root.
    """
    import sys
    print(f"[TRACE] _base_dir called, INVESTIGATOR_WORKDIR={settings.INVESTIGATOR_WORKDIR!r}", file=sys.stderr)
    if settings.INVESTIGATOR_WORKDIR:
        base = Path(settings.INVESTIGATOR_WORKDIR)
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(tempfile.gettempdir())


async def clone_repo(
    repo: str,
    commit_sha: str | None = None,
    *,
    timeout: int | None = None,
) -> tuple[str | None, str | None]:
    """
    Clone `repo` to a fresh directory and return (path, error).

    Exactly one of the two is non-None. On success, `path` is an
    absolute filesystem path to the checkout. On failure, `error`
    is a short human-readable reason — the caller logs it and
    degrades (the agent's tools will all return repo_not_found, and
    the agent will refuse).

    If `repo` is already a local path, returns it unchanged and
    does not touch the filesystem. That is the case for tests and
    for any deployment that keeps checkouts on disk.
    """
    if is_local_path(repo):
        if Path(repo).is_dir():
            return repo, None
        return None, f"local_path_not_found: {repo}"

    if not repo or "/" not in repo:
        return None, f"invalid_repo_name: {repo!r}"

    timeout = timeout or settings.INVESTIGATOR_CLONE_TIMEOUT_SECONDS
    target = _base_dir() / f"inv-{uuid.uuid4().hex[:12]}"
    url = repo_url(repo)

    logger.info(f"📥 Cloning {url} → {target}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", url, str(target),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            shutil.rmtree(target, ignore_errors=True)
            return None, f"clone_timeout after {timeout}s"

        if proc.returncode != 0:
            stderr = out.decode("utf-8", errors="replace")[:500]
            shutil.rmtree(target, ignore_errors=True)
            return None, f"clone_failed: {stderr}"

        # Optional commit pinning. Today nothing sets commit_sha, so
        # this is a no-op. When the Watcher starts setting it, both
        # the Investigator and the Verifier will land on the same
        # commit by construction — they read the same checkout.
        if commit_sha and commit_sha != "HEAD":
            fetch = await asyncio.create_subprocess_exec(
                "git", "-C", str(target),
                "fetch", "--depth=1", "origin", commit_sha,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            try:
                fout, _ = await asyncio.wait_for(fetch.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                fetch.kill()
                shutil.rmtree(target, ignore_errors=True)
                return None, "fetch_timeout"
            if fetch.returncode != 0:
                ferr = fout.decode("utf-8", errors="replace")[:500]
                shutil.rmtree(target, ignore_errors=True)
                return None, f"fetch_failed: {ferr}"

        logger.info(f"✅ Clone ready at {target}")
        return str(target), None

    except Exception as e:
        shutil.rmtree(target, ignore_errors=True)
        return None, f"clone_exception: {e}"

def _on_rm_error(func, path, exc_info):
    """
    Error handler for shutil.rmtree that handles read-only files.

    Git clones contain read-only pack files
    (.git/objects/pack/*.pack) with mode 0444. Python 3.11's
    shutil.rmtree refuses to delete them and raises
    PermissionError. The standard fix is to make the file writable
    and retry.

    Python 3.12 changed this behavior — its rmtree handles
    read-only files on its own. Until the project runs on 3.12+,
    this callback is required for git clones to actually be
    removed.
    """
    try:
        os.chmod(path, 0o700)
        func(path)
    except Exception as e:
        logger.warning(f"rmtree: could not remove {path}: {e}")


def _remove_tree(path: str | Path) -> None:
    """
    Remove a directory tree, handling read-only files.

    Wraps shutil.rmtree with the read-only workaround. Does not
    swallow errors silently — failures are logged at WARNING via
    the onerror callback. If the top-level call fails, it raises
    (the caller decides whether to log or propagate).
    """
    shutil.rmtree(str(path), onerror=_on_rm_error)


def cleanup_repo(path: str | None) -> None:
    """
    Remove a clone created by clone_repo.

    Safe to call on None or on a caller-supplied local path. The
    guard is "did we create this?" not "does this look absolute?" —
    every path on a POSIX system is absolute, so the latter check
    would refuse to delete anything.

    Never raises. Cleanup failure is logged, not propagated.
    """
    if not path:
        return

    base = _base_dir().resolve()
    try:
        target = Path(path).resolve()
    except (OSError, RuntimeError) as e:
        logger.warning(f"cleanup_repo: could not resolve {path}: {e}")
        return

    # Only remove paths under our base dir. Anything outside it
    # belongs to the caller — a local checkout, a test fixture, a
    # hand-managed clone — and we leave it alone.
    try:
        target.relative_to(base)
    except ValueError:
        logger.debug(
            f"cleanup_repo: {path} is outside {base}; not deleting"
        )
        return

    if not target.exists():
        logger.debug(f"cleanup_repo: {target} already gone")
        return

    try:
        _remove_tree(target)
        logger.debug(f"🧹 Removed clone {target}")
    except Exception as e:
        # Do not raise. Cleanup failure must not break the pipeline.
        # But do not swallow it silently either — a lingering clone
        # under INVESTIGATOR_WORKDIR is a disk-space leak.
        logger.warning(f"cleanup_repo: failed to remove {path}: {e}")
