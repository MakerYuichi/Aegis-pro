"""
Provisioner — stage 2 of the incident pipeline.

Owns the clone-once lifecycle for an incident. Two responsibilities:

  1. On clone_provision(context), if the incident will need
     filesystem access, clone the repo into context["repo_workdir"].
     Skip otherwise.

  2. Provide cleanup_repo() so the coordinator can remove the clone
     in its finally block. The Provisioner is the only stage that
     creates the clone, and it's the only stage that defines how to
     remove it.

The clone is created when both of these are true:
  - the service has a repo_name
  - the stack trace parsed to a file_path

Otherwise the Provisioner returns an empty result. Stages that need
a clone (Investigator, Fixer, Verifier) each check for its absence
and degrade honestly — the Provisioner does not synthesize a fake
path or fail the incident because there's nothing to clone.

The Provisioner does not read the clone. It creates it, hands the
path forward via context["repo_workdir"], and lets downstream stages
decide what to do with it.

Design notes:

- No DB access. No writes to extra_metadata. The clone path lives
  in the coordinator's context dict, not in the incident row.
  Downstream stages read it; the response builder does not surface
  it (a temp path is not useful to a human).

- Failure is logged, not raised. A repo that can't be cloned means
  the Investigator will refuse. That's the honest outcome — better
  than pretending the incident has no repo.
"""
from __future__ import annotations

from loguru import logger

from src.agents.repo_clone import clone_repo as _clone_repo_impl
from src.agents.repo_clone import cleanup_repo as _cleanup_repo_impl


async def provision_clone(context: dict) -> dict:
    """
    Clone the incident's repo when the incident will need filesystem
    access. Returns a dict with one key when a clone was made:

        {"repo_workdir": "<path>"}

    Returns an empty dict when no clone was made (no repo, no file
    path, or the clone failed). An empty return is not an error —
    the caller does not surface it to the user, and downstream
    stages detect the missing clone by reading context["repo_workdir"].

    `context` is read-only; the function does not mutate it. The
    caller does `context.update(await provision_clone(context))`.
    """
    service = context.get("service") or {}
    stack_analysis = context.get("stack_analysis") or {}

    repo = service.get("repo_name")
    if not repo:
        logger.debug("Provisioner: skipping clone — service has no repo_name")
        return {}

    file_path = stack_analysis.get("file_path")
    if not file_path:
        logger.debug(
            "Provisioner: skipping clone — stack trace has no file_path"
        )
        return {}

    clone_path, clone_error = await _clone_repo_impl(
        repo, commit_sha=context.get("commit_sha"),
    )
    if clone_path:
        logger.info(f"📦 Provisioner: cloned {repo} → {clone_path}")
        return {"repo_workdir": clone_path}

    logger.warning(
        f"📦 Provisioner: clone of {repo!r} failed: {clone_error}. "
        f"Stages that need filesystem access will degrade."
    )
    return {}

def cleanup_repo(repo_workdir: str | None) -> None:
    """
    Remove a clone created by provision_clone.

    Re-exported from src.agents.repo_clone so the coordinator's
    finally block has a single import path for the Provisioner's
    lifecycle. The Provisioner owns the clone; the coordinator just
    invokes the teardown.

    Safe to call with None or a caller-supplied local path — the
    underlying implementation does nothing in those cases.
    """
    _cleanup_repo_impl(repo_workdir)
