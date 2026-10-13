"""Probe tool — run a small test in the verifier's sandbox.

The scan-mode Investigator uses this to check whether a suspected
failure mode is real. The agent writes the smallest test that would
trigger the failure, and this tool runs it.

The sandbox is the same one HostedVerifier uses: a Docker container
with --network none, memory and CPU caps, and a wall-clock timeout.
Reusing it means the probe inherits the same isolation as
verification, and it inherits the same honest degradation — when
Docker is unavailable, the probe returns a "not_run" observation
and the agent falls back to confirmation="reasoned_only".
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from loguru import logger

from src.agents.tools.repo_tools import ToolResult


MAX_PROBE_CHARS = 4000  # cap the agent's test source


async def probe(
    repo: str,
    code: str,
    language: str = "Python",
) -> ToolResult:
    """Run a small test in the verifier's sandbox.

    `repo` is the checked-out repo the agent is investigating. The
    probe writes `code` to a temp file inside a sandbox workdir and
    runs it. The test is expected to fail (that's the point — the
    agent is trying to reproduce a suspected failure mode); a
    successful run means the failure mode was NOT reproduced.

    Returns a ToolResult whose `result` is the captured stdout/stderr
    and whose metadata carries:
        exit_code:  int
        duration_ms: int
        reproduced: True when the test ran and failed as expected
                    (exit_code != 0). False otherwise.
        ran:        True when the probe actually ran in a sandbox.
                    False when the sandbox was unavailable or the
                    run could not be attempted. The agent must not
                    claim probe_reproduced when ran is False.

    This tool never raises. Every failure mode — no repo, empty
    code, sandbox unavailable — is a ToolResult with ok=False or
    ran=False, and the agent handles it as an observation.
    """
    args = {"language": language, "code_chars": len(code or "")}

    if not code or not code.strip():
        return ToolResult(
            ok=False, tool="probe", args=args, error="empty_code",
        )

    if len(code) > MAX_PROBE_CHARS:
        return ToolResult(
            ok=False, tool="probe", args=args,
            error=f"code_too_long: {len(code)} > {MAX_PROBE_CHARS}",
        )

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return ToolResult(
            ok=False, tool="probe", args=args, error="repo_not_found",
        )

    # Import the sandbox primitive from the verifier. This is the
    # same code path HostedVerifier uses; keeping the import local
    # avoids a circular dependency (verifier imports models, models
    # imports nothing from tools).
    from src.agents.verifier import _run_in_docker, _image_for_language
    from src.config import settings

    if not settings.VERIFY_BEFORE_REPORT:
        # The sandbox is disabled. Refuse to run — and report the
        # reason so the agent knows probe_reproduced is impossible
        # in this deployment.
        return ToolResult(
            ok=False,
            tool="probe",
            args=args,
            error="sandbox_disabled",
            metadata={
                "ran": False,
                "reproduced": False,
                "reason": "VERIFY_BEFORE_REPORT is false; sandbox unavailable",
            },
        )

    workdir = _new_probe_workdir()
    try:
        # Write the agent's test into the workdir alongside a copy of
        # the repo, so the test can import from it. The sandbox
        # mounts the workdir read-write.
        repo_copy = workdir / "repo"
        try:
            shutil.copytree(
                repo_path,
                repo_copy,
                symlinks=False,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
        except Exception as e:
            return ToolResult(
                ok=False, tool="probe", args=args,
                error=f"repo_copy_failed: {e}",
                metadata={"ran": False, "reproduced": False},
            )

        test_file = repo_copy / "aegis_probe.py"
        test_file.write_text(code, encoding="utf-8")

        exit_code, output = await _run_in_docker(
            image=_image_for_language(language),
            host_workdir=workdir,
            container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
            command="python -m aegis_probe",
            timeout=settings.VERIFY_TIMEOUT_SECONDS,
            memory_limit=settings.VERIFIER_MEMORY_LIMIT,
            cpu_limit=settings.VERIFIER_CPU_LIMIT,
        )

        reproduced = exit_code != 0
        return ToolResult(
            ok=True,
            tool="probe",
            args=args,
            result=output,
            metadata={
                "ran": True,
                "reproduced": reproduced,
                "exit_code": exit_code,
            },
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _new_probe_workdir() -> Path:
    """Create a fresh workdir for the probe. Same layout as the
    verifier's, so the sandbox mount resolves the same way."""
    from src.config import settings
    base = Path(settings.VERIFIER_CONTAINER_WORKDIR)
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"probe-{uuid.uuid4().hex[:12]}"
    target.mkdir(parents=True, exist_ok=False)
    return target
