"""
Verification for auto-generated fixes.

The Verifier is stage 4 of the six-stage incident pipeline. Its job:
take a diff, run it against the repo's own tests in an isolated
environment, and return a structured pass/fail result.

Two audiences, two implementations:

  - HostedVerifier  — runs in Docker on the AEGIS PRO host. Used for
                      the public /demo path (a stranger's public repo,
                      no customer infrastructure) and for authenticated
                      users who haven't configured a phone-home runner.
                      This class sees the repo.

  - RunnerVerifier  — hands the job to a phone-home agent running on
                      the customer's own infrastructure. Never touches
                      this process. Planned in a follow-up PR alongside
                      the runner protocol (auth, job queue, heartbeat).

RunnerVerifier does not exist yet. get_verifier(has_runner=True)
raises ValueError rather than returning an unimplemented stub — the
failure is at the selection point, not three layers deep inside a
method that claims to work.

Deployment note: HostedVerifier requires Docker on the host running
the verifier. It will NOT work on Railway or Vercel — those don't
support Docker-in-Docker. Deploy the verifier on a VM (EC2, Hetzner,
Fly Machines) or a dedicated container host. For deployments without
Docker access, keep VERIFY_BEFORE_REPORT=false — the pipeline will
run as if the verifier returned "disabled" and no verification
happens. That's an honest degradation, not a silent failure.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from loguru import logger

from src.config import settings


@dataclass
class VerificationResult:
    """
    Structured result of a verification run.

    Fields:
        passed:       did the verification succeed?
        reason:       machine-readable reason for the outcome.
                      One of: "tests_passed", "tests_failed",
                      "linter_passed", "linter_failed",
                      "typecheck_passed", "typecheck_failed",
                      "syntax_ok", "syntax_failed",
                      "no_verification_surface", "diff_does_not_apply",
                      "timeout", "disabled", "no_diff",
                      "verifier_exception".
        output:       truncated stdout/stderr from the run. Empty when
                      the reason is structural ("disabled", "no_diff").
        duration_ms:  wall-clock duration of the verification, in ms.
        attempts:     per-attempt record. Each entry:
                      {"attempt": int, "passed": bool, "output": str}.
                      Empty for reasons that didn't involve running a
                      command.
        verifier:     which implementation ran. One of "hosted",
                      "runner", "disabled". Set by the implementation
                      or by get_verifier().
    """
    passed: bool
    reason: str
    output: str = ""
    duration_ms: int = 0
    attempts: list[dict] = field(default_factory=list)
    verifier: str = ""


class Verifier(ABC):
    """
    Abstract verifier.

    Implementations own the compute decision — where the diff is
    tested, which runtime is used, what trust boundary applies. The
    caller (the Verifier stage in incident_service.py) only sees the
    interface and the structured result.
    """

    @abstractmethod
    async def verify(
        self,
        repo_name: str,
        commit_sha: str,
        diff: str,
        language: str,
        context: dict | None = None,
    ) -> VerificationResult:
        """
        Verify a diff against the repo's own tests.

        Args:
            repo_name:  "owner/repo" or just "repo". Used to clone.
            commit_sha: the commit to check out before applying the diff.
                        "HEAD" when the caller doesn't know better.
            diff:       the unified diff to apply and test.
            language:   inferred language, e.g. "Python" or "Node".
                        Drives test-runner detection and base image
                        selection.
            context:    optional additional context for the verifier.
                        Not used by the interface; implementations may
                        read fields they understand and ignore the rest.

        Returns:
            VerificationResult. Never raises for a verification
            failure — a failed test is a successful verification with
            passed=False. Raises only for infrastructure failures the
            caller cannot act on (e.g. Docker not installed); the
            caller catches those and returns
            reason="verifier_exception".
        """
        ...


class NoOpVerifier(Verifier):
    """
    Returns a pass without doing anything.

    Used when VERIFY_BEFORE_REPORT is false. The pipeline behaves as
    if verification succeeded, but records reason="disabled" so
    downstream consumers can tell the difference between "we verified
    and it passed" and "we didn't verify." That distinction matters
    for the dashboard and for the future fix_outcomes table.
    """

    async def verify(
        self,
        repo_name: str,
        commit_sha: str,
        diff: str,
        language: str,
        context: dict | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            passed=True,
            reason="disabled",
            verifier="disabled",
        )


class HostedVerifier(Verifier):
    """
    Runs the diff against the repo's own tests in Docker on the AEGIS
    PRO host.

    Deployment constraint: requires Docker CLI + daemon reachable from
    the orchestrator container. In docker-compose that's satisfied by
    the docker-proxy sidecar (see docker-compose.yml and issue #101).
    Deployments without Docker access should keep
    VERIFY_BEFORE_REPORT=false — the pipeline then runs NoOpVerifier
    instead.

    Sandbox model:
      - git clone runs in the orchestrator (trusted code, our network).
      - docker run executes the tests in a sibling container with
        --network none (untrusted execution, no network).
      - Repo is bind-mounted from the host; the sibling sees the
        HOST path, not the orchestrator's internal path.
    """

    async def verify(
        self,
        repo_name: str,
        commit_sha: str,
        diff: str,
        language: str,
        context: dict | None = None,
    ) -> VerificationResult:
        start = time.monotonic()

        workdir = self._new_workdir()
        try:
            clone_ok, clone_err = await self._clone(repo_name, commit_sha, workdir)
            if not clone_ok:
                return VerificationResult(
                    passed=False,
                    reason="clone_failed",
                    output=clone_err,
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )

            apply_ok, apply_err = await self._apply_diff(workdir, diff)
            if not apply_ok:
                return VerificationResult(
                    passed=False,
                    reason="diff_does_not_apply",
                    output=apply_err,
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )

            command, reason_prefix = _detect_runner(workdir / "repo", language)
            if command is None:
                return VerificationResult(
                    passed=False,
                    reason="no_verification_surface",
                    output="",
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )

            attempts: list[dict] = []
            max_attempts = max(1, settings.VERIFY_MAX_ATTEMPTS)

            for attempt_num in range(1, max_attempts + 1):
                exit_code, output = await _run_in_docker(
                    image=_image_for_language(language),
                    host_workdir=workdir,
                    container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
                    command=command,
                    timeout=settings.VERIFY_TIMEOUT_SECONDS,
                    memory_limit=settings.VERIFIER_MEMORY_LIMIT,
                    cpu_limit=settings.VERIFIER_CPU_LIMIT,
                )

                passed = exit_code == 0
                attempts.append({
                    "attempt": attempt_num,
                    "passed": passed,
                    "output": output,
                })

                if passed:
                    return VerificationResult(
                        passed=True,
                        reason=f"{reason_prefix}_passed",
                        output=output,
                        duration_ms=self._ms_since(start),
                        attempts=attempts,
                        verifier="hosted",
                    )

                if attempt_num < max_attempts:
                    repaired = await _attempt_repair(
                        original_context=context or {},
                        failed_output=output,
                        previous_diff=diff,
                    )
                    if not repaired:
                        break
                    ok, _err = await self._apply_diff(
                        workdir, repaired, reset=True
                    )
                    if not ok:
                        break
                    diff = repaired

            return VerificationResult(
                passed=False,
                reason=f"{reason_prefix}_failed",
                output=attempts[-1]["output"] if attempts else "",
                duration_ms=self._ms_since(start),
                attempts=attempts,
                verifier="hosted",
            )

        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _new_workdir(self) -> Path:
        """
        Create a fresh subdirectory under the verifier workdir.

        The host-side path matters: docker-compose bind-mounts
        VERIFIER_CONTAINER_WORKDIR into the orchestrator container, and
        the same host directory is what the verifier tells the Docker
        daemon to bind-mount into the sibling. So we return a path in
        the CONTAINER's view — the code that builds the docker run
        command translates it to the HOST view.
        """
        base = Path(settings.VERIFIER_CONTAINER_WORKDIR)
        base.mkdir(parents=True, exist_ok=True)
        target = base / uuid.uuid4().hex[:12]
        target.mkdir(parents=True, exist_ok=False)
        return target

    async def _clone(self, repo_name, commit_sha, workdir) -> tuple[bool, str]:
        url = _repo_url(repo_name)
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", url, str(workdir / "repo"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return False, out.decode("utf-8", errors="replace")[:4000]
        if commit_sha and commit_sha != "HEAD":
            fetch = await asyncio.create_subprocess_exec(
                "git", "-C", str(workdir / "repo"),
                "fetch", "--depth=1", "origin", commit_sha,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            fout, _ = await fetch.communicate()
            if fetch.returncode != 0:
                return False, fout.decode("utf-8", errors="replace")[:4000]
        return True, ""

    async def _apply_diff(self, workdir, diff, reset: bool = False) -> tuple[bool, str]:
        repo_dir = workdir / "repo"
        if reset:
            # Discard any previously-applied diff before retrying.
            await asyncio.create_subprocess_exec(
                "git", "-C", str(repo_dir), "checkout", "--", ".",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        diff_file = workdir / "fix.diff"
        diff_file.write_text(diff)
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_dir), "apply", "--recount",
            "--whitespace=nowarn", str(diff_file),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return False, out.decode("utf-8", errors="replace")[:4000]
        return True, ""

    @staticmethod
    def _ms_since(start: float) -> int:
        return int((time.monotonic() - start) * 1000)


def _repo_url(repo_name: str) -> str:
    if repo_name.startswith("http") or repo_name.startswith("git@"):
        return repo_name
    return f"https://github.com/{repo_name}.git"


def _image_for_language(language: str) -> str:
    if (language or "").lower().startswith("node"):
        return settings.VERIFY_DOCKER_IMAGE_NODE
    return settings.VERIFY_DOCKER_IMAGE_PYTHON


def _detect_runner(repo_dir: Path, language: str) -> tuple[str | None, str]:
    """
    Walk the degradation ladder for the given language.

    Returns (shell_command, reason_prefix). shell_command is None when
    no rung matches — the caller emits reason="no_verification_surface".

    reason_prefix is the middle token of the final reason
    ("tests_passed", "tests_failed", "linter_passed", etc.).
    """
    lang = (language or "").lower()
    if lang.startswith("node"):
        return _detect_node_runner(repo_dir)
    return _detect_python_runner(repo_dir)


def _detect_python_runner(repo_dir: Path) -> tuple[str | None, str]:
    repo_dir = Path(repo_dir)
    has_py_files = any(repo_dir.rglob("*.py"))
    if not has_py_files:
        return None, "nothing"

    # 1. pytest via pyproject or ini
    if (repo_dir / "pyproject.toml").exists() or \
       (repo_dir / "pytest.ini").exists() or \
       (repo_dir / "setup.cfg").exists() or \
       (repo_dir / "tests").is_dir():
        return "python -m pytest -q", "tests"

    # 2. ruff
    if (repo_dir / "ruff.toml").exists() or (repo_dir / ".ruff.toml").exists():
        return "ruff check .", "linter"

    # 3. mypy
    if (repo_dir / "mypy.ini").exists() or (repo_dir / ".mypy.ini").exists():
        return "mypy .", "typecheck"

    # 4. syntax-only
    return "python -m compileall -q .", "syntax"


def _detect_node_runner(repo_dir: Path) -> tuple[str | None, str]:
    repo_dir = Path(repo_dir)
    has_js = any(repo_dir.rglob("*.js")) or any(repo_dir.rglob("*.ts"))
    if not has_js:
        return None, "nothing"

    pkg = repo_dir / "package.json"
    if pkg.exists():
        return "npm test --silent -- --ci", "tests"
    if (repo_dir / "jest.config.js").exists() or (repo_dir / "jest.config.ts").exists():
        return "npx --yes jest --ci", "tests"
    if (repo_dir / "vitest.config.ts").exists() or (repo_dir / "vitest.config.js").exists():
        return "npx --yes vitest run", "tests"
    if (repo_dir / ".eslintrc").exists() or (repo_dir / ".eslintrc.json").exists() or (repo_dir / ".eslintrc.js").exists():
        return "npx --yes eslint .", "linter"
    if (repo_dir / "tsconfig.json").exists():
        return "npx --yes tsc --noEmit", "typecheck"
    return "node --check $(find . -name '*.js' -not -path './node_modules/*' | head -1)", "syntax"


async def _run_in_docker(
    *,
    image: str,
    host_workdir: Path,
    container_workdir: str,
    command: str,
    timeout: int,
    memory_limit: str,
    cpu_limit: str,
) -> tuple[int, str]:
    """
    Run `command` inside a fresh container with the repo bind-mounted
    read-write. --network none is deliberate: the sibling container
    executes unreviewed, AI-generated code and must not reach the
    network.
    """
    container_relative = host_workdir.name
    host_path = f"{settings.VERIFIER_HOST_WORKDIR.rstrip('/')}/{container_relative}"
    container_path = f"{container_workdir}/{container_relative}/repo"
    
    # Every argument in argv comes from a trusted source:
    #   - "docker", "run", "--rm", "--network", "none", "--memory",
    #     "--cpus", "-v", "-w", "sh", "-c"  — hardcoded
    #   - memory_limit, cpu_limit            — settings
    #   - host_path                          — settings + uuid4().hex[:12]
    #   - container_path                     — settings + the same uuid
    #   - image                              — one of two config values
    #                                           (VERIFY_DOCKER_IMAGE_*)
    #   - command                            — one of the hardcoded strings
    #                                           in _detect_runner
    #
    # No user input (repo name, diff, stack trace) flows into argv. The
    # diff is written to a file and mounted as data; the repo URL is
    # used by `git clone` on the host, never by `docker run`. If you add
    # a new argument here, it must come from config or a generated
    # value — never from customer input.
    argv = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", memory_limit,
        "--cpus", cpu_limit,
        "-v", f"{host_path}:{container_workdir}/{container_relative}",
        "-w", container_path,
        image,
        "sh", "-c", command,
    ]

    proc = await asyncio.create_subprocess_exec(
        *argv,
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
        return 124, f"verification timed out after {timeout}s"

    exit_code = proc.returncode if proc.returncode is not None else -1
    return exit_code, out.decode("utf-8", errors="replace")[:8000]


async def _attempt_repair(
    *,
    original_context: dict,
    failed_output: str,
    previous_diff: str,
) -> str | None:
    """
    On test failure, ask the LLM to repair the diff. The prompt
    includes the ORIGINAL reasoning context (option B) so the model
    can reconsider its diagnosis, not just tweak a line.

    Returns the repaired diff, or None on failure.
    """
    from src.services.llm_service import LLMService

    llm = LLMService()
    if not llm.chain:
        return None

    analysis = original_context.get("analysis") or {}
    stack = original_context.get("stack_analysis") or {}

    prompt = (
        "A previous fix was applied but the tests failed.\n\n"
        f"Original stack: {stack.get('exception_type', 'Unknown')} at "
        f"{stack.get('file_path', 'unknown')}:{stack.get('line_number', 'unknown')}\n"
        f"Original root cause: {analysis.get('root_cause', 'unknown')}\n"
        f"Original suggested fix: {analysis.get('suggested_fix', 'unknown')}\n\n"
        "Previous diff:\n"
        f"{previous_diff}\n\n"
        "Test failure output:\n"
        f"{failed_output}\n\n"
        "Reconsider the diagnosis. If the root cause was wrong, correct it. "
        "Otherwise revise the diff. Return ONLY the corrected unified diff "
        "in git-apply-compatible format. No explanation, no prose."
    )

    content = await llm.complete_raw(
        prompt=prompt,
        system="You are an expert software engineer. Return ONLY a unified diff.",
        temperature=0.2,
        max_tokens=1500,
    )
    return content

def get_verifier(*, has_runner: bool = False) -> Verifier:
    """
    Return the verifier implementation for the current request.

    Selection:
        VERIFY_BEFORE_REPORT=false  -> NoOpVerifier (no compute)
        VERIFY_BEFORE_REPORT=true   -> HostedVerifier (Docker on AEGIS host)
        has_runner=True             -> ValueError

    The ValueError on has_runner=True is deliberate. The runner
    implementation does not exist yet; a caller asking for it should
    fail at the point of the mistake, not three calls deep inside an
    unimplemented method. When the runner PR lands, this function
    grows a real branch and the error goes away.
    """
    if has_runner:
        raise ValueError(
            "has_runner=True was requested but no runner verifier is "
            "configured. The phone-home runner protocol has not been "
            "implemented yet — see the runner verifier follow-up issue. "
            "Set has_runner=False to use the hosted verifier."
        )

    if not settings.VERIFY_BEFORE_REPORT:
        logger.debug("Verifier disabled — VERIFY_BEFORE_REPORT=false")
        return NoOpVerifier()

    return HostedVerifier()

