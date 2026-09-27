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

    See the module docstring for the deployment constraint: this
    requires Docker on the host. Deployments without Docker should
    leave VERIFY_BEFORE_REPORT=false and get NoOpVerifier instead.

    Implementation lands in the next commit on this branch. This
    skeleton exists so the interface, the factory, and the tests are
    all coherent on day one; the verify() body is the only thing
    still to write.
    """

    async def verify(
        self,
        repo_name: str,
        commit_sha: str,
        diff: str,
        language: str,
        context: dict | None = None,
    ) -> VerificationResult:
        raise NotImplementedError(
            "HostedVerifier.verify is not implemented yet. "
            "This commit defines the interface; the Docker-based "
            "implementation lands in the next commit on agent-hub. "
            "Leave VERIFY_BEFORE_REPORT=false until then."
        )


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
