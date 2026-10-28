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
from typing import Literal, Optional
from dataclasses import dataclass, field
from src.agents.repo_clone import _remove_tree
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from loguru import logger

from src.config import settings
from src.agents.prefetch.manifest_finder import find_manifest, ManifestRef
from src.agents.prefetch.runner import (
    PrefetchError,
    PrefetchResult,
    run_prefetch,
    run_prefetch_with_build_on_miss,
)
from src.agents.pytest_parser import parse_failed_tests, new_failures


# ---------------------------------------------------------------------------
# Design C — fix-progress classification
#
# After the initial fix runs and the probe still crashes, we need to
# decide: is the initial fix "partial progress" (keep it, repair on
# top), or a "no-op" (reset to pristine, repair from scratch)?
#
# Two signals, both structural, both measurable from data the
# pipeline already has:
#
#   1. Did the crash move?  — different line number OR different
#                             exception message between before/after
#                             tracebacks.
#   2. Did the fix change any lines?  — the initial diff has at
#                                       least one +/- line.
#
# If both signals say "yes, progress" → PARTIAL: keep fix1, apply
# repair on top of it.
# Otherwise → NOOP: reset to pristine, repair from scratch.
#
# "Harmful" collapses into NOOP. If fix1 broke something new, the
# conservative reset removes the harm. If fix1 was a no-op, reset
# is redundant but harmless. Same next step, simpler decision.
# ---------------------------------------------------------------------------

_TRACEBACK_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
_EXCEPTION_LINE_RE = re.compile(
    r'^(\w+(?:Error|Exception)):\s*(.*)$',
    re.MULTILINE,
)


def _extract_last_traceback(
    output: str,
) -> tuple[str | None, str | None]:
    """Return (frame "file:line", exception "Type: message")
    for the LAST traceback in the probe output.

    Both return values are ``None`` when the output doesn't contain
    a recognizable traceback. That's the honest answer for probe
    output like ``"timed out after 60s"``.
    """
    if not output:
        return None, None
    frames = _TRACEBACK_FRAME_RE.findall(output)
    exceptions = _EXCEPTION_LINE_RE.findall(output)
    last_frame = (
        f"{frames[-1][0]}:{frames[-1][1]}" if frames else None
    )
    last_exception = (
        f"{exceptions[-1][0]}: {exceptions[-1][1]}"
        if exceptions
        else None
    )
    return last_frame, last_exception


def _crash_moved(before_output: str, after_output: str) -> bool:
    """True if the crash changed location or message.

    Signal 1 of Design C. Frame OR message differing counts as
    progress. Frame moving from ``cookies.py:470`` to
    ``cookielib.py:785`` is progress — the fix addressed the first
    crash, exposed a second. Message changing from
    ``'startswith'`` to ``'lower'`` is progress for the same
    reason.

    If both are identical (or either is absent so the comparison
    can't be made), the crash hasn't moved. That's the no-op case.
    """
    before_frame, before_exc = _extract_last_traceback(before_output)
    after_frame, after_exc = _extract_last_traceback(after_output)
    if before_frame is None or after_frame is None:
        # No traceback in one of them — treat as "not moved" so
        # the caller falls back to the safe reset path. Better
        # than guessing.
        return False
    if before_frame != after_frame:
        return True
    if before_exc != after_exc:
        return True
    return False


def _diff_has_changes(diff: str) -> bool:
    """True if the diff has at least one added or removed line.

    Signal 2 of Design C. Header lines (``---``, ``+++``) are
    ignored. A diff that only has headers and context has no
    changes.
    """
    for line in (diff or "").split("\n"):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("+") or line.startswith("-"):
            return True
    return False


def _classify_fix_progress(
    before_output: str,
    after_output: str,
    original_diff: str,
) -> str:
    """Classify the initial fix as "partial" or "noop".

    Design C decision function. Returns:

        "partial" — the fix made progress but is incomplete.
                    Caller keeps fix1 applied and repairs on top.
        "noop"    — the fix didn't change anything, or was empty,
                    or we can't tell. Caller resets to pristine
                    before repairing.

    Any uncertainty defaults to "noop" — reset-and-repair is
    always safe. The "partial" path is an optimization, not a
    correctness requirement.
    """
    if not _diff_has_changes(original_diff):
        return "noop"
    if not _crash_moved(before_output, after_output):
        return "noop"
    return "partial"


@dataclass
class RealignmentReport:
    """
    Summary of what _realign_diff did to a diff.

    Fields:
        hunks_total:     number of hunks in the diff
        hunks_realigned: hunks whose header was rewritten to match
                         a location found in the file
        hunks_unchanged: hunks left alone (already correct, or
                         unaffected by realignment)
        hunks_flagged:   hunks that couldn't be realigned for a
                         reason worth surfacing to a human. Each
                         entry: {"index": int, "reason": str} where
                         reason is one of:
                           "ambiguous_match"  — the hunk's context
                                                matches more than
                                                one location
                           "unanchorable"     — the hunk has no
                                                context or removed
                                                lines to search
                                                against, and the
                                                file header signals
                                                an existing file
                                                (i.e. not /dev/null)
    """
    hunks_total: int = 0
    hunks_realigned: int = 0
    hunks_unchanged: int = 0
    hunks_flagged: list[dict] = field(default_factory=list)


@dataclass
class VerificationResult:
    """
    Structured result of a verification run.

    Fields:
        passed:       did the verification succeed?
        reason:       machine-readable reason for the outcome.
                      One of: "tests_passed", "tests_failed",
                      "tests_passed_pre_existing_failures",
                      "linter_passed", "linter_failed",
                      "typecheck_passed", "typecheck_failed",
                      "syntax_ok", "syntax_failed",
                      "no_verification_surface", "diff_does_not_apply",
                      "timeout", "disabled", "no_diff",
                      "verifier_exception".
                      "tests_passed_pre_existing_failures" means
                      the test command exited nonzero but every
                      failing test was already failing in the
                      baseline (no-diff) run. The diff didn't
                      break anything; the repo's tests were
                      already failing in the sandbox environment.
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
    realignment: RealignmentReport = field(default_factory=RealignmentReport)


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
   

    async def verify(
        self,
        repo_name: str,
        commit_sha: str,
        diff: str,
        language: str,
        context: dict | None = None,
    ) -> VerificationResult:
        start = time.monotonic()
        logger.error(f"[TRACE] verify start repo={repo_name} diff_len={len(diff)}")

        # Prefer the clone the Provisioner created. When
        # context["repo_workdir"] is set, it points at a checkout
        # under VERIFIER_CONTAINER_WORKDIR, visible to both the
        # orchestrator and (via the host bind mount) the sibling
        # container the tests run in. In that case, no second clone.
        existing = (context or {}).get("repo_workdir")
        reuse = False
        workdir: Path
        tree_root: Path | None = None
        # Whether the tree lives at <workdir>/repo/ (GitHub incident path:
        # Provisioner cloned there) or directly at <workdir>/ (local scan:
        # the operator pointed AEGIS at a checkout). The distinction
        # matters for three things below: where git apply runs, where
        # the test runner is detected, and where the file is read for
        # realignment. Determined once and threaded through.
        tree_relative: str = "repo"

        if existing:
            candidate = Path(existing)
            if candidate.is_dir():
                if (candidate / "repo").is_dir():
                    workdir = candidate
                    tree_root = candidate / "repo"
                    tree_relative = "repo"
                else:
                    # Local scan: <workdir> IS the tree.
                    workdir = candidate
                    tree_root = candidate
                    tree_relative = ""
                reuse = True
                logger.info(
                    f"Verifier: reusing clone at {workdir} "
                    f"(tree_root={tree_root})"
                )


        if not reuse:
            workdir = self._new_workdir()
            clone_ok, clone_err = await self._clone(repo_name, commit_sha, workdir)
            if not clone_ok:
                logger.error(f"[TRACE] return: clone_failed")
                return VerificationResult(
                    passed=False,
                    reason="clone_failed",
                    output=clone_err,
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )
            tree_root = workdir / "repo"
            tree_relative = "repo"
            if not clone_ok:
                logger.error(f"[TRACE] return: clone_failed")
                return VerificationResult(
                    passed=False,
                    reason="clone_failed",
                    output=clone_err,
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )

        try:
            command, reason_prefix = _detect_runner(tree_root, language)
            if command is None:
                logger.error(f"[TRACE] return: no_verification_surface")
                return VerificationResult(
                    passed=False,
                    reason="no_verification_surface",
                    output="",
                    duration_ms=self._ms_since(start),
                    verifier="hosted",
                )

            # Realign the diff against the cloned file. The LLM's
            # hunk headers are frequently off by several lines;
            # git apply --recount fixes counts but not starting
            # numbers, so an off-by-N header makes git apply fail
            # even when the content is unambiguous. The realignment
            # is best-effort: if it can't find a match, the diff
            # passes through unchanged and git apply decides.
            realignment = RealignmentReport()
            target_path = (context or {}).get(
                "stack_analysis", {}
            ).get("file_path")
            file_lines: list[str] = []
            if target_path:
                full = _resolve_repo_path(tree_root, target_path)
                if full is not None:
                    try:
                        file_lines = full.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines()
                    except Exception as e:
                        logger.warning(
                            f"Could not read {target_path} for "
                            f"realignment: {e}"
                        )
                else:
                    logger.warning(
                        f"Could not find {target_path} in clone "
                        f"for realignment"
                    )

            if file_lines:
                repo_relative_path = None
                if full is not None:
                    try:
                        repo_relative_path = full.relative_to(
                            tree_root
                        ).as_posix()
                    except ValueError:
                        repo_relative_path = None

                diff, realignment = _realign_diff(
                    diff, file_lines, repo_relative_path
                )
                logger.info(
                    f"Realignment: {realignment.hunks_realigned}/"
                    f"{realignment.hunks_total} hunks realigned, "
                    f"{len(realignment.hunks_flagged)} flagged"
                )

            # ── Prefetch reuse ─────────────────────────────────
            #
            # The prefetch now happens once, in _stage_prefetch,
            # BEFORE the Investigator. This lets the Investigator's
            # probe tool install real deps and run real imports. The
            # Verifier reuses the same cache — no second download.
            #
            # If the prefetch failed (or no manifest), context will
            # not have prefetch_cache_host_path. The Verifier then
            # runs the tests without cached deps — the honest
            # degradation.
            cache_host_path = (
                Path(context["prefetch_cache_host_path"])
                if context and context.get("prefetch_cache_host_path")
                else None
            )
            manifest_relative_path = (
                context.get("prefetch_manifest_relative")
                if context else None
            )

            if cache_host_path is None:
                logger.info(
                    f"Verifier: no prefetch cache for "
                    f"{repo_name}; tests will run without cached deps"
                )

                
                        # ── Single-attempt verification ──────────────────────
            #
            # No toolchain loop. Use the fixed image (Python 3.11 +
            # pytest 8.3.4) and try to run the repo's tests. If the
            # suite can't collect (old repo, MarkDecorator error,
            # pytest version mismatch), report tests_could_not_run
            # honestly. No whack-a-mole, no Python 3.7.
            image = _image_for_language(language)

            logger.info(
                f"Verifier: single-attempt verification "
                f"(image={image})"
            )

            tc_result = await self._attempt_with_toolchain(
                tree_root=tree_root,
                workdir=workdir,
                tree_relative=tree_relative,
                diff=diff,
                language=language,
                command=command,
                commit_sha=commit_sha,
                context=context,
                realignment=realignment,
                cache_host_path=cache_host_path,
                manifest_relative_path=manifest_relative_path,
                pytest_version="8.3.4",
                python_version="3.11",
                image=image,
                file_lines=file_lines,
                repo_relative_path=repo_relative_path,
            )

            return tc_result


        finally:
            # Tree preservation is a per-SCAN decision, not a
            # per-incident decision.
            #
            # The rule:
            #
            #   - Once ANY incident in the current scan has produced
            #     probe_passed, the tree MUST stay preserved for the
            #     rest of the scan (and after it ends). The fix is
            #     the product; .aegis/fixes.json recorded it; the
            #     next scan must find it applied.
            #
            #   - Only if NO incident in the scan has yet produced
            #     probe_passed should a non-probe_passed incident
            #     reset the tree. This cleans up failed/ambiguous
            #     diffs that would otherwise corrupt the next
            #     verification's realignment.
            #
            # The bug this fixes (observed 2026-10-27, scan at 14:40):
            # INC-...-12D2B6 at status_codes.py:116 passed probe_passed
            # as incident #1. Its fix was written to the tree and to
            # .aegis/fixes.json. Then INC-...-D365F9 (incident #2) had
            # reason="refused" → this finally block reset the tree,
            # wiping the status_codes.py:116 fix. By the end of the
            # scan, the fix was gone even though the log said
            # "preserving tree" for incident #1.
            #
            # The per-scan gate is stored on the context so it
            # survives across incidents. Once set, it never unsets
            # during the scan.
            scan_ctx = (context or {})
            already_preserved = bool(
                scan_ctx.get("scan_tree_has_verified_fix")
            )

            current_passed = (
                "tc_result" in locals()
                and tc_result is not None
                and tc_result.reason == "probe_passed"
            )

            if current_passed:
                # Mark the scan as having a preserved fix. This
                # propagates to every subsequent incident in the
                # same scan via the context dict (mutable, shared).
                scan_ctx["scan_tree_has_verified_fix"] = True

            preserve_tree = (
                current_passed
                or already_preserved
            ) and reuse and tree_root is not None

            if preserve_tree:
                reason_logged = (
                    "this incident probe_passed"
                    if current_passed
                    else "an earlier incident in this scan probe_passed"
                )
                logger.info(
                    f"Verifier: preserving tree at {tree_root} "
                    f"({reason_logged} — fix stays applied; next "
                    f"scan will report it as already_fixed)"
                )
            elif reuse and tree_root is not None:
                try:
                    reset_proc = await asyncio.create_subprocess_exec(
                        "git", "-C", str(tree_root), "reset", "--hard",
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    )
                    await reset_proc.communicate()
                    clean_proc = await asyncio.create_subprocess_exec(
                        "git", "-C", str(tree_root), "clean", "-fd",
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    )
                    await clean_proc.communicate()
                except Exception as e:
                    logger.warning(
                        f"Verifier: failed to reset tree at end of "
                        f"verify(): {e}"
                    )


            # Only remove clones we created. The Provisioner's clone
            # is cleaned up by the coordinator's finally block.
            if not reuse:
                try:
                    _remove_tree(workdir)
                    logger.debug(f"🧹 Verifier removed {workdir}")
                except Exception as e:
                    logger.warning(
                        f"Verifier: failed to remove {workdir}: {e}"
                )
    async def _compute_combined_diff(
        self, tree_root: Path,
    ) -> str | None:
        """Return the net diff between HEAD and the current tree.

        Design C uses this after a "partial" repair succeeds: the
        tree currently has ``fix1 + repair`` applied on top of
        pristine. The stored artifact must be the combined diff so
        that applying it to a fresh clone reproduces the passing
        tree state.

        Returns ``None`` if the diff can't be computed. The caller
        falls back to storing the repair-only diff in that case —
        honest degradation, not a silent lie.
        """
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(tree_root), "diff", "HEAD",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                f"Verifier: could not compute combined diff: "
                f"{out.decode(errors='replace')[:300]!r}"
            )
            return None
        diff = out.decode("utf-8", errors="replace")
        return diff or None
    
                    
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
        
        # Diagnostic: confirm the clone has the expected structure.
        repo_root = workdir / "repo"
        fixture_path = repo_root / "backend" / "orchestrator" / "tests" / "fixtures" / "repos" / "mini_python"
        logger.info(f"VERIFIER CLONE: repo_root exists={repo_root.is_dir()}")
        logger.info(f"VERIFIER CLONE: fixture exists={fixture_path.is_dir()}")
        if repo_root.is_dir():
            bo = repo_root / "backend" / "orchestrator"
            if bo.is_dir():
                items = sorted(p.name for p in bo.iterdir())[:10]
                logger.info(f"VERIFIER CLONE: backend/orchestrator contents={items}")
            else:
                logger.info(f"VERIFIER CLONE: backend/orchestrator missing")
                
        return True, ""

    async def _apply_diff(self, tree_root: Path, diff: str, reset: bool = False) -> tuple[bool, str]:
        repo_dir = tree_root
        if reset:
            # Discard any previously-applied diff before retrying.
            #
            # Two changes from the previous version, both necessary
            # for a retry to actually start clean:
            #
            # 1. await communicate(), not just create_subprocess_exec.
            #    create_subprocess_exec returns when the process
            #    starts, not when it exits. Without communicate(),
            #    the reset races with the following git apply for
            #    .git/index.lock, and the process is never reaped.
            #
            # 2. git reset --hard plus git clean -fd, not
            #    checkout -- . The latter restores tracked files but
            #    doesn't remove files that a previous diff added.
            #    reset --hard discards tracked changes; clean -fd
            #    removes untracked files the diff created. Both are
            #    needed for a true reset.
            reset_proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(repo_dir), "reset", "--hard",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            await reset_proc.communicate()
            clean_proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(repo_dir), "clean", "-fd",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            await clean_proc.communicate()

        # Write the diff to a temp file OUTSIDE the tree. Writing
        # it inside leaves a stray file if the apply fails, and
        # that file corrupts the next run's realignment (it appears
        # in git status as untracked, and the realignment search
        # sees spurious context matches). This is a general fix,
        # not a per-repo one — any repo's tree should be pristine
        # between attempts.
        text = diff if diff.endswith("\n") else diff + "\n"
        text = _normalize_diff_paths(text)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False,
            prefix="aegis-apply-", encoding="utf-8",
        ) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(repo_dir), "apply", "--recount",
                "--whitespace=nowarn", tmp_path,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                return False, out.decode("utf-8", errors="replace")[:4000]
            return True, ""
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _ms_since(start: float) -> int:
        return int((time.monotonic() - start) * 1000)
    
    
    async def _attempt_with_toolchain(
        self,
        *,
        tree_root: Path,
        workdir: Path,
        tree_relative: str,
        diff: str,
        language: str,
        command: str,
        commit_sha: str,
        context: dict | None,
        realignment: RealignmentReport,
        cache_host_path: Path | None,
        manifest_relative_path: str | None,
        pytest_version: str,
        python_version: str,
        image: str,
        file_lines: list[str],
        repo_relative_path: str | None,
        constraints: list[str] | None = None,
    ) -> VerificationResult:
        """
        One attempt: baseline pytest, apply diff, re-run pytest.
        No toolchain-specific logic — the image is fixed at Python
        3.11 with pytest 8.3.4. Used when running pytest against a
        repo whose test suite is modern enough to collect on pytest 8.
        """
        start = time.monotonic()

        baseline_failures: set[str] = set()
        baseline_output = ""
        baseline_exit = -1
        try:
            baseline_exit, baseline_full_output = await _run_in_docker(
                image=image,
                host_workdir=workdir,
                container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
                command=command,
                timeout=settings.VERIFY_TIMEOUT_SECONDS,
                memory_limit=settings.VERIFIER_MEMORY_LIMIT,
                cpu_limit=settings.VERIFIER_CPU_LIMIT,
                cache_host_path=cache_host_path,
                manifest_relative_path=manifest_relative_path,
                tree_relative=tree_relative,
            )
            baseline_output = baseline_full_output[:8000]
            baseline_failures = parse_failed_tests(baseline_full_output)
            logger.info(
                f"Verifier: baseline run exit={baseline_exit}, "
                f"{len(baseline_failures)} pre-existing failures"
            )
        except Exception as e:
            logger.warning(
                f"Verifier: baseline run failed, "
                f"treating all failures as new: {e}"
            )

        # pytest couldn't run. Multiple signals:
        #  - exit 5 = no tests collected
        #  - exit 2 with MarkDecorator / collection errors = old suite
        #  - Requires-Python = deps won't install on this Python
        # For all these, fall back to probe-based verification.
        could_not_run = False
        if baseline_exit == 5:
            could_not_run = True
        elif baseline_exit == 2 and (
            "MarkDecorator" in baseline_output
            or "ERROR collecting" in baseline_output
        ):
            could_not_run = True
        elif "Requires-Python" in baseline_output or "requires a different Python" in baseline_output:
            could_not_run = True

        if could_not_run:
            logger.info(
                f"Verifier: pytest couldn't run "
                f"(exit={baseline_exit}); falling back to probe verification"
            )
            return await self._verify_with_probe(
                tree_root=tree_root,
                tree_relative=tree_relative,
                investigation=(context or {}).get("investigation") or {},
                diff=diff,
                cache_host_path=cache_host_path,
                manifest_relative_path=manifest_relative_path,
                image=image,
                context=context or {},
            )

        # Normal test run.
        attempts: list[dict] = []
        max_attempts = max(1, settings.VERIFY_MAX_ATTEMPTS)
        current_diff = diff

        for attempt_num in range(1, max_attempts + 1):
            apply_ok, apply_err = await self._apply_diff(
                tree_root, current_diff, reset=True
            )
            if not apply_ok:
                diff_preview = current_diff[:400] if current_diff else "<empty>"
                attempts.append({
                    "attempt": attempt_num,
                    "passed": False,
                    "output": (
                        f"git apply failed at commit {commit_sha}: {apply_err}\n"
                        f"--- diff (first 400 chars) ---\n"
                        f"{diff_preview}"
                    ),
                })
                if attempt_num < max_attempts:
                    repaired = await _attempt_repair(
                        original_context=context or {},
                        failed_output=f"git apply failed: {apply_err}",
                        previous_diff=current_diff,
                    )
                    if not repaired:
                        break
                    if file_lines:
                        repaired, _ = _realign_diff(
                            repaired, file_lines,
                            repo_relative_path,
                        )
                    current_diff = repaired
                    continue
                else:
                    break

            exit_code, full_output = await _run_in_docker(
                image=image,
                host_workdir=workdir,
                container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
                command=command,
                timeout=settings.VERIFY_TIMEOUT_SECONDS,
                memory_limit=settings.VERIFIER_MEMORY_LIMIT,
                cpu_limit=settings.VERIFIER_CPU_LIMIT,
                cache_host_path=cache_host_path,
                manifest_relative_path=manifest_relative_path,
                tree_relative=tree_relative,
            )
            output = full_output[:8000]

            current_failed = parse_failed_tests(full_output)
            new = current_failed - baseline_failures
            pre_existing = current_failed & baseline_failures

            passed = exit_code == 0
            attempts.append({
                "attempt": attempt_num,
                "passed": passed,
                "output": output,
                "new_failures": sorted(new),
                "pre_existing_failures": sorted(pre_existing),
            })

            if passed:
                return VerificationResult(
                    passed=True,
                    reason="tests_passed",
                    output=output,
                    duration_ms=self._ms_since(start),
                    attempts=attempts,
                    verifier="hosted",
                    realignment=realignment,
                )

            if not new and pre_existing:
                return VerificationResult(
                    passed=True,
                    reason="tests_passed_pre_existing_failures",
                    output=output,
                    duration_ms=self._ms_since(start),
                    attempts=attempts,
                    verifier="hosted",
                    realignment=realignment,
                )

            if not new and not pre_existing:
                if (
                    "no tests ran" in full_output
                    or "collected 0 items" in full_output
                    or "ERROR collecting" in full_output
                ):
                    return VerificationResult(
                        passed=False,
                        reason="tests_could_not_run",
                        output=output,
                        duration_ms=self._ms_since(start),
                        attempts=attempts,
                        verifier="hosted",
                        realignment=realignment,
                    )

            if attempt_num < max_attempts:
                repaired = await _attempt_repair(
                    original_context=context or {},
                    failed_output=full_output[-8000:],
                    previous_diff=current_diff,
                )
                if not repaired:
                    break
                if file_lines:
                    repaired, _ = _realign_diff(
                        repaired, file_lines,
                        repo_relative_path,
                    )
                current_diff = repaired

        last_output = attempts[-1]["output"] if attempts else ""
        if attempts and "git apply failed" in attempts[-1]["output"]:
            return VerificationResult(
                passed=False,
                reason="diff_does_not_apply",
                output=last_output,
                duration_ms=self._ms_since(start),
                attempts=attempts,
                verifier="hosted",
                realignment=realignment,
            )

        return VerificationResult(
            passed=False,
            reason="tests_failed",
            output=last_output,
            duration_ms=self._ms_since(start),
            attempts=attempts,
            verifier="hosted",
            realignment=realignment,
        )
        
    async def _verify_with_probe(
        self,
        *,
        tree_root: Path,
        tree_relative: str,
        investigation: dict,
        diff: str,
        cache_host_path: Path | None,
        manifest_relative_path: str | None,
        image: str,
        context: dict | None = None,
    ) -> VerificationResult:
        """
        Verify a fix by re-running the Investigator's probe against
        the original code and the fixed code. Used when pytest can't
        run (old Python, dep conflicts, collection errors).

        The probe is extracted from investigation.history: the last
        successful probe observation, with its code and flags.

        Returns:
          probe_passed  — probe failed before, passed after (verified!)
          probe_failed  — probe failed both before and after (fix wrong)
          probe_ambiguous — probe passed both (doesn't reproduce bug)
          tests_could_not_run — no probe in history
        """
        import shlex
        
        context = context or {}
        history = investigation.get("history") or []

        # Prefer a probe that touches the tree over one that
        # doesn't. The previous selection used `reversed(history)`
        # — "the last successful probe." That's wrong when the
        # agent retried a failed probe with a toy reproduction:
        # the last probe becomes the toy, and the Verifier
        # re-runs the toy, which fails before *and* after by
        # construction. See INC-20261027-B209DF: the agent's
        # probe #1 imported requests.status_codes (correct, but
        # failed on ModuleNotFoundError due to a container path
        # bug in probe.py); probe #2 hardcoded `__doc__ = None`
        # on a fresh ModuleType (toy). The Verifier picked #2
        # and reported probe_failed for a fix that was correct.
        #
        # Heuristic: a probe that imports anything other than
        # `types`, `sys`, `os`, `traceback`, or the string
        # builtins is assumed to touch the tree. Toy probes are
        # almost always built from stdlib primitives only.
        TOY_ONLY_MODULES = {
            "types", "sys", "os", "traceback", "warnings",
            "functools", "itertools", "collections", "re",
        }

        def _is_toy(code: str) -> bool:
            import ast
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return False  # unparseable — treat as real, let it run
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root not in TOY_ONLY_MODULES:
                            return False
                elif isinstance(node, ast.ImportFrom):
                    root = (node.module or "").split(".")[0]
                    if root and root not in TOY_ONLY_MODULES:
                        return False
            return True

        candidates: list[tuple[dict, str, list[str]]] = []
        for obs in history:
            if obs.get("tool") != "probe" or not obs.get("ok"):
                continue
            code = (obs.get("args") or {}).get("code") or ""
            flags = (obs.get("args") or {}).get("interpreter_flags") or []
            candidates.append((obs, code, flags))

        # Prefer non-toy probes; among those, prefer the most
        # recent. Fall back to the most recent toy probe only if
        # every probe was a toy.
        real = [c for c in candidates if not _is_toy(c[1])]
        chosen = real[-1] if real else (candidates[-1] if candidates else None)

        probe_code: str | None = None
        probe_flags: list[str] = []
        if chosen is not None:
            _, probe_code, probe_flags = chosen

        if not probe_code:
            return VerificationResult(
                passed=False,
                reason="tests_could_not_run",
                output="No probe in Investigator history; cannot verify.",
                verifier="hosted",
            )

        # Run a probe inside a Docker container against the tree.
        # Uses --network none because the probe code is LLM-generated.
        # Run a probe inside a Docker container against the tree.
        # Uses --network none because the probe code is LLM-generated.
        # Installs deps from the cache into a venv before running —
        # otherwise `import requests` fails on missing urllib3, etc.
        async def _run_probe() -> tuple[bool, str]:
            host_path = f"{settings.VERIFIER_HOST_WORKDIR.rstrip('/')}/{tree_root.name}"
            if tree_relative:
                workdir_inside = f"/work/{tree_relative}"
            else:
                workdir_inside = "/work"
            flag_str = " ".join(probe_flags)
            quoted_code = shlex.quote(probe_code)

            has_cache = (
                cache_host_path is not None
                and manifest_relative_path is not None
            )

            if has_cache:
                # pip install must succeed. The previous version
                # appended `|| true`, which silently swallowed every
                # pip failure — including the case where the cache
                # manifest itself is missing (/cache/requirements.lock
                # not found), leaving the probe to run in an empty
                # venv and crash on ModuleNotFoundError. That crash
                # was then classified as "the bug reproduced" by
                # _output_signals_bug, producing false
                # probe_passed / probe_failed / no_verification_surface
                # results. See INC-20261028-3F38D0.
                #
                # Now pip failures are visible: if the install fails,
                # the whole command fails, and the caller gets a
                # specific error message ("pip install failed:
                # ...") instead of a misleading crash.
                #
                # The `&&` chain preserves the same semantics (venv
                # → pip install → probe) but aborts if any step
                # fails. Combined with `set -e` at the top of the
                # command, this guarantees the probe only runs when
                # its dependencies are actually installed.
                command = (
                    f"set -e; "
                    f"cd {workdir_inside} && "
                    "python -m venv /tmp/venv && "
                    "/tmp/venv/bin/pip install --no-index --find-links /cache "
                    "--quiet -r /cache/requirements.lock && "
                    f"PATH=/tmp/venv/bin:$PATH "
                    f"PYTHONPATH={workdir_inside} "
                    f"python {flag_str} -c {quoted_code}"
                )
            else:
                command = (
                    f"cd {workdir_inside} && "
                    f"PYTHONPATH={workdir_inside} "
                    f"python {flag_str} -c {quoted_code}"
                )

            argv = [
                "docker", "run", "--rm",
                "--network", "none",
                "-v", f"{host_path}:/work",
            ]
            if has_cache:
                argv.extend(["-v", f"{cache_host_path}:/cache:ro"])
            argv.extend([
                "-w", workdir_inside,
                image,
                "sh", "-c", command,
            ])

            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await proc.wait()
                except Exception:
                    pass
                return False, "probe timed out after 60s"
            output = out.decode("utf-8", errors="replace")[:2000]
            # "passed" = "bug absent" = no exception + exit 0.
            # Uses _output_signals_bug so probes that catch-and-print
            # (agent style) are correctly classified as failures.
            from src.agents.tools.probe import _output_signals_bug
            passed = (proc.returncode == 0) and not _output_signals_bug(output)
            return passed, output

        # Ensure the tree is at HEAD (original code).
        reset_proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(tree_root), "reset", "--hard",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        await reset_proc.communicate()

        # Probe BEFORE fix.
        before_passed, before_output = await _run_probe()

        # Apply the diff.
        apply_ok, apply_err = await self._apply_diff(tree_root, diff, reset=True)
        if not apply_ok:
            return VerificationResult(
                passed=False,
                reason="diff_does_not_apply",
                output=f"Probe verification: {apply_err}",
                verifier="hosted",
            )

        # Probe AFTER fix.
        after_passed, after_output = await _run_probe()

        # IMPORTANT: do NOT reset the tree here.
        #
        # The whole point of probe-verified fixes is that the fix
        # stays in the working tree. The next scan reads .aegis/fixes.json,
        # sees the fix is applied, and reports it as "already_fixed."
        # If we reset here, the fix is lost, the next scan finds the
        # bug again, and the "already fixed" state is never observable.
        #
        # The pre-probe reset at the top of this method is what
        # guarantees a clean baseline — the before-probe runs against
        # pristine code. That reset stays. This one goes.
        #
        # See INC-20261027-4B97CB: the fix was applied, .aegis/fixes.json
        # was written correctly, and this reset wiped status_codes.py
        # back to the buggy line — so the very next scan found the same
        # bug again and reported probe_passed again, with no
        # already_fixed state ever surfacing.


        if not before_passed and after_passed:
            return VerificationResult(
                passed=True,
                reason="probe_passed",
                output=(
                    f"Probe failed before fix:\n{before_output}\n\n"
                    f"Probe passed after fix:\n{after_output}"
                ),
                verifier="hosted",
            )

        if before_passed and after_passed:
            return VerificationResult(
                passed=False,
                reason="probe_ambiguous",
                output=(
                    f"Probe passed BOTH before and after fix; "
                    f"it does not reproduce the bug.\n"
                    f"Before: {before_output}\n\n"
                    f"After: {after_output}"
                ),
                verifier="hosted",
            )

        # Probe failed both before and after. But the failure may be
        # DIFFERENT after the fix (crash moved). If so, the Fixer
        # produced an incomplete fix — it patched one site but the
        # value still flows to another crash site downstream.
        #
        # Attempt one repair: feed the "after" traceback back to the
        # Fixer and let it produce a corrected diff. The probe re-runs
        # against the corrected diff. This closes the loop:
        #
        #   Fixer produces diff → Verifier rejects it with the exact
        #   failure → Fixer produces a corrected diff → Verifier
        #   re-runs.
        #
        # If the repair succeeds and the new probe passes, return
        # probe_passed. If it fails, or if the traceback is identical
        # (the fix didn't change anything), return probe_failed.
        # Attempt repair — one shot.
        # ── Design C — classify fix progress, attempt one repair ──
        #
        # Two signals decide the path:
        #   1. Did the crash move?   (frame or exception message)
        #   2. Did the fix touch any lines?
        #
        # "partial" — the fix made progress. Keep fix1 applied,
        #             ask the repair LLM to correct it on top.
        # "noop"    — no progress, empty fix, or unknown. Reset
        #             to pristine, ask the repair LLM for a
        #             complete fix from scratch.
        #
        # Anything uncertain defaults to "noop". Reset-and-repair
        # is always safe; "partial" is an optimization.

        progress_kind = _classify_fix_progress(
            before_output, after_output, diff,
        )
        logger.info(
            f"Verifier: probe_failed reached. "
            f"before_len={len(before_output or '')} "
            f"after_len={len(after_output or '')} "
            f"before_passed={before_passed} "
            f"after_passed={after_passed} "
            f"outputs_differ={before_output != after_output} "
            f"progress_kind={progress_kind} "
            f"repair_will_fire="
            f"{bool(before_output and after_output and before_output != after_output)}"
        )

        if before_output and after_output and before_output != after_output:
            try:
                repaired_diff = await _attempt_probe_repair(
                    context=context or {},
                    original_diff=diff,
                    before_output=before_output,
                    after_output=after_output,
                    progress_kind=progress_kind,
                )
            except Exception as e:
                logger.warning(
                    f"Verifier: probe repair failed with exception: {e}"
                )
                repaired_diff = None

            if repaired_diff:
                # Duplicate check — do not re-run the same fix.
                def _strip_diff_headers(d: str) -> str:
                    return "\n".join(
                        ln for ln in (d or "").split("\n")
                        if not ln.startswith("---")
                        and not ln.startswith("+++")
                    )

                if (
                    _strip_diff_headers(repaired_diff)
                    == _strip_diff_headers(diff)
                ):
                    logger.warning(
                        "Verifier: repair produced the same diff as "
                        "the initial fix; skipping re-run"
                    )
                    return VerificationResult(
                        passed=False,
                        reason="probe_failed",
                        output=(
                            f"Probe failed both before and after "
                            f"the initial fix, and the repair "
                            f"attempt produced an identical diff. "
                            f"No further repair attempted.\n"
                            f"Before: {before_output}\n\n"
                            f"After: {after_output}"
                        ),
                        verifier="hosted",
                    )

                # Read the file's current state for realignment.
                #
                #   - "partial" path: do NOT reset. The tree has
                #     fix1 applied. The repair diff's '-' lines
                #     must match "pristine + fix1".
                #   - "noop" path: reset to pristine. The repair
                #     diff's '-' lines must match pristine.
                stack = context.get("stack_analysis") or {}
                target_path = stack.get("file_path")
                file_lines_for_repair: list[str] = []
                repo_relative_for_repair: str | None = None

                if progress_kind == "noop":
                    reset_proc = await asyncio.create_subprocess_exec(
                        "git", "-C", str(tree_root), "reset", "--hard",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    await reset_proc.communicate()
                    clean_proc = await asyncio.create_subprocess_exec(
                        "git", "-C", str(tree_root), "clean", "-fd",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    await clean_proc.communicate()

                if target_path:
                    full = _resolve_repo_path(tree_root, target_path)
                    if full is not None:
                        try:
                            file_lines_for_repair = full.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                            try:
                                repo_relative_for_repair = (
                                    full.relative_to(tree_root).as_posix()
                                )
                            except ValueError:
                                repo_relative_for_repair = None
                        except OSError:
                            pass

                if file_lines_for_repair:
                    repaired_diff, _ = _realign_diff(
                        repaired_diff,
                        file_lines_for_repair,
                        repo_relative_for_repair,
                    )
                    logger.info(
                        f"Verifier: realigned repaired diff "
                        f"(path={progress_kind})"
                    )

                apply_ok, apply_err = await self._apply_diff(
                    tree_root,
                    repaired_diff,
                    reset=(progress_kind == "noop"),
                )
                if not apply_ok:
                    logger.warning(
                        f"Verifier: repaired diff did not apply "
                        f"(path={progress_kind}): "
                        f"{apply_err[:300]!r}"
                    )
                else:
                    (
                        after_repaired_passed,
                        after_repaired_output,
                    ) = await _run_probe()
                    logger.info(
                        f"Verifier: repaired probe result "
                        f"(path={progress_kind}): "
                        f"passed={after_repaired_passed}"
                    )
                    if not before_passed and after_repaired_passed:
                        # Stored artifact must reproduce the
                        # passing tree state.
                        #   - "noop" path: repaired_diff already
                        #     applies to pristine, so it's the
                        #     correct artifact.
                        #   - "partial" path: tree is
                        #     "pristine + fix1 + repair".
                        #     Compute the net diff so applying
                        #     it to pristine gives the same
                        #     final state.
                        stored_diff = repaired_diff
                        if progress_kind == "partial":
                            combined = await self._compute_combined_diff(
                                tree_root,
                            )
                            if combined:
                                stored_diff = combined
                                logger.info(
                                    f"Verifier: stored combined "
                                    f"diff ({len(combined)} chars) "
                                    f"for partial-progress repair"
                                )
                            else:
                                logger.warning(
                                    "Verifier: could not compute "
                                    "combined diff; storing "
                                    "repair-only diff"
                                )

                        return VerificationResult(
                            passed=True,
                            reason="probe_passed",
                            output=(
                                f"Probe failed before fix:\n"
                                f"{before_output}\n\n"
                                f"Probe failed after initial fix:\n"
                                f"{after_output}\n\n"
                                f"Probe passed after repaired fix "
                                f"(path={progress_kind}):\n"
                                f"{after_repaired_output}"
                            ),
                            verifier="hosted",
                        )

        return VerificationResult(
            passed=False,
            reason="probe_failed",
            output=(
                f"Probe failed BOTH before and after fix; the fix "
                f"did not work.\n"
                f"Before: {before_output}\n\n"
                f"After: {after_output}"
            ),
            verifier="hosted",
        )


def _repo_url(repo_name: str) -> str:
    if repo_name.startswith("http") or repo_name.startswith("git@"):
        return repo_name
    return f"https://github.com/{repo_name}.git"

def _resolve_repo_path(repo_root: Path, file_path: str) -> Path | None:
    candidate = repo_root / file_path
    if candidate.is_file():
        return candidate

    basename = Path(file_path).name
    if not basename:
        return None

    excludes = {
        ".git", "node_modules", "venv", ".venv",
        "dist", "build", "__pycache__",
    }
    for found in repo_root.rglob(basename):
        if found.is_file() and not any(
            part in excludes for part in found.parts
        ):
            return found
    return None


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

_RealignReason = Literal["ambiguous_match", "unanchorable"]


def _realign_diff(
    diff: str,
    file_lines: list[str],
    repo_relative_path: str | None = None,
) -> tuple[str, RealignmentReport]:
    """
    ... existing docstring ...
    
    If `repo_relative_path` is provided, the diff's --- and +++ file
    headers are rewritten to that path. This is what makes a diff
    whose header said "src/services/foo.py" (from the stack trace)
    apply against a file that actually lives at
    "backend/orchestrator/src/services/foo.py" (in the repo).
    """
    report = RealignmentReport()

    lines = diff.split("\n")
    if not lines:
        return diff, report

    # Rewrite the file headers to the resolved repo-relative path.
    # git apply -p1 strips the a/ or b/ prefix and expects the rest
    # to match a path in the working tree. The stack trace's path is
    # not that path in a monorepo. The realigner has already resolved
    # the correct path; use it.
    if repo_relative_path:
        lines = _rewrite_file_headers(lines, repo_relative_path)

    is_new_file = any(
        line.startswith("--- /dev/null") for line in lines
    )
    
    if not file_lines and not is_new_file:
        return diff, report

    # Split the diff into three regions: preamble (--- / +++ lines
    # and anything before the first @@), hunks, and trailing noise.
    # We only touch hunks.
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("@@"):
            out.append(line)
            i += 1
            continue

        # Found a hunk header. Collect its body.
        header_match = re.match(
            r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$",
            line,
        )
        if not header_match:
            # Malformed header; leave as-is, count it, move on.
            out.append(line)
            i += 1
            continue

        old_start = int(header_match.group(1))
        new_start = int(header_match.group(3))
        tail = header_match.group(5) or ""

        body_start = i + 1
        body_end = body_start
        while body_end < len(lines):
            candidate = lines[body_end]
            if candidate.startswith("@@") or candidate.startswith("diff --git"):
                break
            body_end += 1
        body = lines[body_start:body_end]
        i = body_end

        report.hunks_total += 1

        # Build the search signature from context + removed lines.
        signature: list[str] = []
        body_meta: list[tuple[str, str]] = []  # (kind, content)
        for raw in body:
            if raw.startswith("\\"):
                # No newline marker; skip during matching. Its
                # presence in the output is derived later.
                continue
            if raw.startswith(" "):
                signature.append(raw[1:])
                body_meta.append(("context", raw[1:]))
            elif raw.startswith("-") and not raw.startswith("---"):
                signature.append(raw[1:])
                body_meta.append(("removed", raw[1:]))
            elif raw.startswith("+") and not raw.startswith("+++"):
                body_meta.append(("added", raw[1:]))
            else:
                # Unknown line shape. Treat as opaque; keep it in
                # the output but don't try to match on it.
                body_meta.append(("opaque", raw))

        if not signature:
            # No context or removed lines to search with. Leave the
            # hunk alone. Flag it only if this isn't a new file —
            # a pure insertion into an existing file is
            # unanchorable and suspicious.
            if not is_new_file:
                report.hunks_flagged.append({
                    "index": report.hunks_total - 1,
                    "reason": "unanchorable",
                })
            out.append(_rebuild_hunk_header(old_start, new_start, body))
            out.extend(body)
            report.hunks_unchanged += 1
            continue

        # Search the file at each tolerance tier.
        match, tier = _find_unique_match(signature, file_lines)
        if match is None and tier is None:
            # No matches at any tier.
            report.hunks_flagged.append({
                "index": report.hunks_total - 1,
                "reason": "context_not_found",
            })
            out.append(_rebuild_hunk_header(old_start, new_start, body))
            out.extend(body)
            report.hunks_unchanged += 1
            continue

        if match is None:
            # tier is "ambiguous"
            report.hunks_flagged.append({
                "index": report.hunks_total - 1,
                "reason": "ambiguous_match",
            })
            out.append(_rebuild_hunk_header(old_start, new_start, body))
            out.extend(body)
            report.hunks_unchanged += 1
            continue

        # Found a unique match at line index `match`.
        realigned_start = match + 1  # 1-indexed for the header
        new_body = _rebuild_hunk_body(body_meta, file_lines, match)
        out.append(_rebuild_hunk_header(
            realigned_start, realigned_start, new_body,
        ))
        out.extend(new_body)

        if realigned_start != old_start:
            report.hunks_realigned += 1
        else:
            report.hunks_unchanged += 1

    return "\n".join(out), report


def _find_unique_match(
    signature: list[str],
    file_lines: list[str],
) -> tuple[Optional[int], Optional[str]]:
    """
    Return (index, tier) for the unique location where signature
    matches, or (None, "ambiguous") if multiple, or (None, None) if
    none.

    Tier 1 (returned as tier="exact"): exact per-line match.
    Tier 2 (tier="rstrip"): right-strip each line before comparing.
    Tier 3 (tier="strip"): strip both sides before comparing.

    A tier is only tried if all stricter tiers produced zero
    matches. If a tier produces multiple matches, we stop and
    report ambiguity — looser tiers would only match more.
    """
    def _matches_at(normalize):
        sig = [normalize(s) for s in signature]
        hits = []
        n = len(file_lines)
        m = len(sig)
        if m == 0 or m > n:
            return hits
        for start in range(n - m + 1):
            window = [normalize(file_lines[start + k]) for k in range(m)]
            if window == sig:
                hits.append(start)
        return hits

    tiers = [
        ("exact", lambda s: s),
        ("rstrip", lambda s: s.rstrip()),
        ("strip", lambda s: s.strip()),
    ]
    for tier_name, normalize in tiers:
        hits = _matches_at(normalize)
        if len(hits) == 1:
            return hits[0], tier_name
        if len(hits) > 1:
            return None, "ambiguous"
        # Zero hits; try next tier.
    return None, None


def _rebuild_hunk_header(
    old_start: int,
    new_start: int,
    body: list[str],
) -> str:
    """
    Recompute a hunk header from its body.

    Counts are derived from the body: context counts toward both
    old and new, removed toward old, added toward new.
    """
    old_count = 0
    new_count = 0
    for line in body:
        if line.startswith("\\"):
            continue
        if line.startswith(" "):
            old_count += 1
            new_count += 1
        elif line.startswith("-") and not line.startswith("---"):
            old_count += 1
        elif line.startswith("+") and not line.startswith("+++"):
            new_count += 1
    return f"@@ -{old_start},{old_count} +{new_start},{new_count} @@"


def _rebuild_hunk_body(
    body_meta: list[tuple[str, str]],
    file_lines: list[str],
    start_index: int,
) -> list[str]:
    """
    Reconstruct the hunk body from file_lines and the LLM's added
    lines.

    Context and removed lines come from the file at the matched
    location — not from the LLM's diff, which may have the wrong
    indentation or trailing whitespace.

    Added lines come from the LLM, because the file doesn't contain
    them yet.

    The "\\ No newline at end of file" marker is derived from
    file_lines, not carried over from the LLM's diff: it appears
    only if the last line referenced by the hunk is the file's
    last line and the file has no trailing newline.
    """
    out: list[str] = []
    cursor = start_index
    for kind, _content in body_meta:
        if kind == "context":
            out.append(" " + file_lines[cursor])
            cursor += 1
        elif kind == "removed":
            out.append("-" + file_lines[cursor])
            cursor += 1
        elif kind == "added":
            out.append("+" + _content)
        else:
            out.append(_content)
    return out


def _detect_python_runner(repo_dir: Path) -> tuple[str | None, str]:
    """
    Walk the degradation ladder for Python, looking for test
    configuration at any depth — not just the repo root.

    Rationale: repos often keep their Python code in a subdirectory
    (backend/orchestrator/, src/, app/). Looking only at the repo
    root misses pytest configs and test directories that live one
    or two levels down. The previous behavior collapsed such repos
    to `compileall`, which reported `syntax_passed` — an honest but
    weak claim. Finding the real test runner makes the verification
    claim stronger.

    When a config is found in a subdirectory, the returned command
    `cd`s into that directory before running pytest. That matches
    how a human would run the tests from the project root.
    """
    repo_dir = Path(repo_dir)
    has_py_files = any(repo_dir.rglob("*.py"))
    if not has_py_files:
        return None, "nothing"

    # 1. pytest via pyproject, pytest.ini, setup.cfg, or a tests/ dir —
    #    at any depth. Return the pytest command anchored at the
    #    directory that contains the config, so relative imports and
    #    conftest.py files resolve correctly.
    config_markers = (
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
    )
    for marker in config_markers:
        for found in repo_dir.rglob(marker):
            # Skip anything inside a hidden or virtualenv directory.
            if any(
                part.startswith(".") or part in ("venv", ".venv", "node_modules")
                for part in found.relative_to(repo_dir).parts
            ):
                continue
            rel = found.parent.relative_to(repo_dir)
            if str(rel) == ".":
                return "python -m pytest -q .", "tests"
            return f"cd {rel.as_posix()} && python -m pytest -q .", "tests"

    # A bare tests/ directory (no config) is also a pytest signal.
    for tests_dir in repo_dir.rglob("tests"):
        if not tests_dir.is_dir():
            continue
        if any(
            part.startswith(".") or part in ("venv", ".venv", "node_modules")
            for part in tests_dir.relative_to(repo_dir).parts
        ):
            continue
        rel = tests_dir.parent.relative_to(repo_dir)
        if str(rel) == ".":
            return "python -m pytest -q tests/", "tests"
        return f"cd {rel.as_posix()} && python -m pytest -q tests/", "tests"

    # 2. ruff — same any-depth treatment.
    for marker in ("ruff.toml", ".ruff.toml"):
        for found in repo_dir.rglob(marker):
            if any(
                part.startswith(".") and part not in (".ruff.toml",)
                for part in found.relative_to(repo_dir).parts
            ):
                continue
            rel = found.parent.relative_to(repo_dir)
            if str(rel) == ".":
                return "ruff check .", "linter"
            return f"cd {rel.as_posix()} && ruff check .", "linter"

    # 3. mypy — same.
    for marker in ("mypy.ini", ".mypy.ini"):
        for found in repo_dir.rglob(marker):
            rel = found.parent.relative_to(repo_dir)
            if str(rel) == ".":
                return "mypy .", "typecheck"
            return f"cd {rel.as_posix()} && mypy .", "typecheck"

    # 4. syntax-only fallback.
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
    cache_host_path: Path | None = None,
    manifest_relative_path: str | None = None,
    tree_relative: str = "repo",
) -> tuple[int, str]:
    """
    Run `command` inside a fresh container with the repo bind-mounted
    read-write. --network none is deliberate: the sibling container
    executes unreviewed, AI-generated code and must not reach the
    network.

    Every run gets a name so a timeout can kill it by name. The
    Docker CLI client is what proc.kill() SIGKILLs — SIGKILL cannot
    be forwarded through the client to the daemon, so the container
    keeps running unless we address it directly.
    """
    container_relative = host_workdir.name
    host_path = f"{settings.VERIFIER_HOST_WORKDIR.rstrip('/')}/{container_relative}"
    if tree_relative:
        container_path = f"{container_workdir}/{container_relative}/{tree_relative}"
    else: 
        container_path = f"{container_workdir}/{container_relative}/repo"
    container_name = f"aegis-verify-{uuid.uuid4().hex[:12]}"

    # Every argument in argv comes from a trusted source:
    #   - "docker", "run", "--rm", "--name", "--network", "none",
    #     "--memory", "--cpus", "-v", "-w", "sh", "-c"  — hardcoded
    #   - container_name                     — generated uuid
    #   - memory_limit, cpu_limit            — settings
    #   - host_path                          — settings + uuid4().hex[:12]
    #   - container_path                     — settings + the same uuid
    #   - image                              — one of two config values
    #                                           (VERIFY_DOCKER_IMAGE_*)
    #   - command                            — one of the hardcoded strings
    #                                           in _detect_runner
    #
    # No user input (repo name, diff, stack trace) flows into argv. If
    # you add a new argument here, it must come from config or a
    # generated value — never from customer input.
        # The container runs as the invoking user so files it writes
    # to the bind-mounted workspace are owned by the orchestrator's
    # UID — otherwise cleanup leaves root-owned residue on the
    # host. --read-only plus non-root means pip can't write to
    # the rootfs; PIP_NO_CACHE_DIR avoids the pip cache, and
    # HOME points at a tmpfs-backed directory. When a cache is
    # mounted, the install goes to /tmp/site-packages and
    # PYTHONPATH points there for the test command.
    argv = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp/aegis-home",
        "-e", "PIP_NO_CACHE_DIR=1",
        "--memory", memory_limit,
        "--cpus", cpu_limit,
        "-v", f"{host_path}:{container_workdir}/{container_relative}",
        "-v", f"{settings.VERIFIER_HOST_WORKDIR}:/work-investigator",
    ]

    effective_command = command
    if cache_host_path is not None and manifest_relative_path is not None:
        argv.extend([
            "-v", f"{cache_host_path}:/cache:ro",
        ])
        # Create a fresh virtualenv for this repo and install
        # everything (runtime + test deps) into it. Run pytest from
        # INSIDE the venv — this isolates the repo's deps AND plugins
        # from the verifier image's packages.
        #
        # Without this:
        #   - A repo pinning idna<2.8 conflicts with the image's
        #     anyio (which needs idna>=2.8).
        #   - The image's pytest-asyncio 0.25 breaks psf/requests
        #     v2.19.0's collection (MarkDecorator incompatibility).
        #
        # With the venv:
        #   - The venv has only what requirements.lock declared.
        #   - pytest-asyncio is NOT installed unless the repo needs it.
        #   - Old test suites collect and run correctly.
        #
        # PATH=/tmp/venv/bin:$PATH means `python -m pytest -q` (the
        # command _detect_runner emits) resolves to the venv's python
        # and pytest. No command-string rewriting needed.
        # Pin pytest to the specific version decided by the
        # toolchain selector. The prefetched requirements.lock
        # contains `pytest>=X` (usually unpinned), so pip would
        # install the latest — which breaks old repos. Override
        # with an explicit pytest install first.
        install_cmd = (
            "python -m venv /tmp/venv && "
            "/tmp/venv/bin/pip install --no-index --find-links /cache "
            "--quiet "
            "-r /cache/requirements.lock "
            "&& "
            "PATH=/tmp/venv/bin:$PATH "
        )
        effective_command = install_cmd + command


    argv.extend([
        "-w", container_path,
        image,
        "sh", "-c", effective_command,
    ])

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        # Kill the client process.
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        # Kill the container by name. proc.kill() only SIGKILLs the
        # Docker CLI client; the daemon doesn't see it, so the
        # container would keep running without this.
        try:
            kp = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            await kp.wait()
        except Exception as e:
            logger.warning(
                f"Verifier: docker kill {container_name} failed: {e}"
            )
        return 124, f"verification timed out after {timeout}s"

    exit_code = proc.returncode if proc.returncode is not None else -1
    # Return the full output. Callers that display it truncate at
    # display time. The parser needs the full string — pytest's
    # FAILED summary is at the end of the output, past the
    # 8000-byte point where truncation used to occur.
    return exit_code, out.decode("utf-8", errors="replace")


async def _attempt_probe_repair(
    *,
    context: dict,
    original_diff: str,
    before_output: str,
    after_output: str,
    progress_kind: str = "noop",
) -> str | None:
    """Repair a fix whose probe failed before AND after.

    Called from _verify_with_probe when the probe crashed both times
    but with DIFFERENT tracebacks. That pattern means the Fixer
    produced an incomplete fix — the crash moved, it didn't
    disappear.

    The repair prompt asks the Fixer to:
      1. Read the new traceback.
      2. Identify where the value that's causing the crash enters
         the function (usually a parameter merged into a dict, or
         a kwargs.get).
      3. Normalize the value at entry — not at individual use sites.
      4. Ensure the probe (which is still the original probe) will
         not encounter the None value anywhere.

    Returns the repaired diff, or None if the repair failed.
    """
    from src.services.llm_service import LLMService

    llm = LLMService()
    if not llm.chain:
        return None

    analysis = context.get("analysis") or {}
    stack = context.get("stack_analysis") or {}
    investigation = context.get("investigation") or {}

    # Read the current file context so the repair LLM has the
    # ACTUAL code to work against — not a hallucinated version
    # of it. The original Fixer got this via code_context. The
    # repair prompt currently doesn't, which is why its diffs
    # hallucinate context lines that don't exist in the file.
    code_context_str = ""
    target_path = stack.get("file_path") if stack else None
    if target_path:
        # context may carry a pre-fetched code window
        code_ctx = (context or {}).get("code_context") or {}
        raw = code_ctx.get("code_snippet") or code_ctx.get("raw_snippet")
        if raw:
            code_context_str = raw

    code_context_block = ""
    if code_context_str:
        code_context_block = (
            f"## Current code (around the crash site, copied verbatim from the file)\n\n"
            f"{code_context_str}\n\n"
        )

    if progress_kind == "partial":
        state_block = (
            f"## Tree state — IMPORTANT\n\n"
            f"The tree currently has the PREVIOUS FIX APPLIED. "
            f"Your diff will run WITHOUT a reset, on top of the "
            f"current state. Your '-' (removed) lines must match "
            f"the COMBINED state (pristine code + the previous "
            f"diff's changes) — not pristine code alone.\n\n"
            f"The previous diff (already applied to the tree):\n"
            f"{original_diff}\n\n"
        )
        instruction = (
            f"## What to do\n\n"
            f"The previous fix was PARTIAL progress. It changed "
            f"something (the crash moved), but the fix is "
            f"incomplete. Correct it ON TOP of the current state:\n\n"
            f"  1. Read the Current Code block above — it shows "
            f"the file AS IT EXISTS NOW (with the previous fix "
            f"applied).\n"
            f"  2. Your diff should CORRECT the previous fix. "
            f"Add the missing guard at the entry point where the "
            f"value enters the function, and simplify or remove "
            f"the ineffective part of the previous fix if it's "
            f"now redundant.\n"
            f"  3. The tree will NOT be reset. Your diff applies "
            f"to the current state, and the final tree is "
            f"pristine + previous diff + your diff. The pipeline "
            f"captures the net diff for storage.\n\n"
        )
    else:  # "noop"
        state_block = (
            f"## Tree state — IMPORTANT\n\n"
            f"The tree is PRISTINE. The previous fix has been "
            f"REVERTED. Before your diff runs, the tree is reset "
            f"to HEAD. Your '-' lines must match the PRISTINE "
            f"code shown in the Current Code block — not the "
            f"previous fix's changes.\n\n"
            f"The previous diff (for reference — already reverted):\n"
            f"{original_diff}\n\n"
        )
        instruction = (
            f"## What to do\n\n"
            f"The previous fix was a NO-OP or WORSE. It either "
            f"didn't change the crash at all, or made it worse. "
            f"The tree is now pristine. Produce a COMPLETE fix "
            f"from scratch:\n\n"
            f"  1. Find the point where the offending value "
            f"ENTERS the function. In the Current Code block "
            f"above, look for the dict literal "
            f"(`result = {{...}}`), the kwargs merge "
            f"(`result.update(kwargs)` or "
            f"`kwargs['domain'] = ...`), or the parameter "
            f"declaration (`def create_cookie(..., **kwargs)`).\n"
            f"  2. Insert a normalization guard AT ENTRY, before "
            f"the value can be used anywhere else. Right after "
            f"the kwargs merge or at the top of the function.\n"
            f"  3. Do NOT patch individual use sites. The "
            f"previous fix did that and it didn't work.\n"
            f"  4. Do NOT reference the previous diff's changes "
            f"in your '-' lines — those changes are gone.\n\n"
        )

    prompt = (
        f"A previous fix was applied to the repo and the probe "
        f"still crashes. Your job is to produce a corrected "
        f"diff.\n\n"
        f"Original failure (before any fix):\n"
        f"{before_output}\n\n"
        f"Failure after the initial fix was applied:\n"
        f"{after_output}\n\n"
        f"Diagnosis from the Investigator: "
        f"{(investigation.get('failure_mode') or 'N/A')[:300]}\n"
        f"Fix location: "
        f"{stack.get('file_path', 'unknown')}:"
        f"{stack.get('line_number', '?')}\n\n"
        f"{code_context_block}"
        f"{state_block}"
        f"{instruction}"
        f"## CRITICAL — diff applicability\n\n"
        f"The context lines (the ones starting with a space, "
        f"and the '-' removed lines) in your diff MUST be "
        f"copied byte-for-byte from the Current Code block "
        f"above. Do not retype from memory. Do not imagine "
        f"what the function looks like — READ the actual code "
        f"block and copy those lines exactly. If you write "
        f"context lines that don't exist in the file, git "
        f"apply will reject the entire patch.\n\n"
        f"For each hunk:\n"
        f"  - Copy 2-3 lines before your change from the code "
        f"    block, verbatim, prefix with space.\n"
        f"  - Copy the line you're changing, verbatim, prefix "
        f"    with '-'.\n"
        f"  - Write your new line, prefix with '+'.\n"
        f"  - Copy 2-3 lines after your change, verbatim, "
        f"    prefix with space.\n"
        f"  - Use actual line numbers from the code block "
        f"    (they're on the left side).\n\n"
        f"Produce ONLY a corrected unified diff in "
        f"git-apply-compatible format. No prose, no Markdown "
        f"fences."
    )


    resp = await llm.complete_raw_detailed(
        prompt=prompt,
        system=(
            "You are an expert software engineer fixing an incomplete "
            "bug fix. The previous fix guarded the wrong line. Produce "
            "a fix that normalizes the offending value at function "
            "entry, not at individual use sites. Return ONLY a unified "
            "diff in git-apply-compatible format. No prose, no "
            "Markdown fences."
        ),
        temperature=0.2,
        max_tokens=1500,
    )

    if not resp.content:
        return None

    if resp.finish_reason in ("length", "MAX_TOKENS", "max_tokens"):
        logger.warning(
            f"Probe repair response truncated at {len(resp.content)} chars"
        )
        return None

    from src.services.autofix_service import AutoFixService
    extracted = AutoFixService._extract_diff(resp.content)
    if not extracted:
        logger.warning(
            f"Probe repair: _extract_diff returned empty. "
            f"Head: {resp.content[:200]!r}"
        )
        return None

    trimmed = AutoFixService._trim_trailing_noise(extracted)
    if not trimmed:
        return None

    if not AutoFixService._diff_looks_valid(trimmed):
        logger.warning(
            f"Probe repair: _diff_looks_valid rejected. "
            f"Head: {trimmed[:200]!r}"
        )
        return None

    logger.info(
        f"Probe repair: produced {len(trimmed)} chars, re-running probe"
    )
    return trimmed


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

    # Distinguish between "the diff applied but tests failed" and
    # "the diff didn't apply at all". The repair strategy is different:
    # in the first case the LLM needs to reconsider the fix; in the
    # second, it needs to make the diff actually apply.
    if "git apply failed" in failed_output or "corrupt patch" in failed_output:
        situation = (
            "A previous diff was generated but git apply rejected it "
            "before any tests could run. The diff did not apply."
        )
        instruction = (
            "Produce a NEW diff that will apply cleanly. Pay close "
            "attention to the exact lines in the current code — the "
            "hunk context must match byte-for-byte. Return ONLY a "
            "unified diff in git-apply-compatible format. No "
            "explanation, no prose, no Markdown fences."
        )
    else:
        situation = (
            "A previous fix was applied and the tests failed."
        )
        instruction = (
            "Reconsider the diagnosis. If the root cause was wrong, "
            "correct it. Otherwise revise the diff. Return ONLY the "
            "corrected unified diff in git-apply-compatible format. "
            "No explanation, no prose, no Markdown fences."
        )

    prompt = (
        f"{situation}\n\n"
        f"Original stack: {stack.get('exception_type', 'Unknown')} at "
        f"{stack.get('file_path', 'unknown')}:{stack.get('line_number', 'unknown')}\n"
        f"Original root cause: {analysis.get('root_cause', 'unknown')}\n"
        f"Original suggested fix: {analysis.get('suggested_fix', 'unknown')}\n\n"
        "Previous diff:\n"
        f"{previous_diff}\n\n"
        "Failure output:\n"
        f"{failed_output}\n\n"
        "IMPORTANT: the previous diff has been reverted. `git checkout -- .` "
        "runs before your diff is applied, restoring the repo to its "
        "original state. Your diff applies to the ORIGINAL repo. Do not "
        "produce a diff that tries to undo the previous diff — those "
        "changes are already gone. Produce a diff that, starting from the "
        "original repo, results in the fix.\n\n"
        "Keep the diff small and focused. Fix only the failing tests. Do "
        "not refactor unrelated code, do not add tests, do not rename "
        "anything. The minimum diff that makes the failing tests pass is "
        "the correct diff.\n\n"
        f"{instruction}"
    )

    resp = await llm.complete_raw_detailed(
        prompt=prompt,
        system=(
            "You are an expert software engineer. Return ONLY a unified "
            "diff in git-apply-compatible format. No prose, no Markdown "
            "fences, no explanation."
        ),
        temperature=0.2,
        max_tokens=1500,
    )
    if not resp.content:
        return None

    logger.info(
        f"Repair response: {len(resp.content)} chars, "
        f"finish_reason={resp.finish_reason!r}"
    )
    
    if resp.finish_reason in ("length", "MAX_TOKENS", "max_tokens"):
        logger.warning("Repair response was truncated by token limit.")
        return None

    from src.services.autofix_service import AutoFixService
    extracted = AutoFixService._extract_diff(resp.content)
    if not extracted:
        logger.warning(
            "Repair: _extract_diff returned empty. Response head: "
            f"{resp.content[:200]!r}"
        )
        return None

    trimmed = AutoFixService._trim_trailing_noise(extracted)
    if not trimmed:
        logger.warning(
            "Repair: _trim_trailing_noise returned empty. Extracted: "
            f"{extracted[:200]!r}"
        )
        return None

    if not AutoFixService._diff_looks_valid(trimmed):
        logger.warning(
            "Repair: _diff_looks_valid rejected the diff. Head: "
            f"{trimmed[:300]!r}"
        )
        return None

    return trimmed


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

def _normalize_diff_paths(diff: str) -> str:
    """
    Ensure the diff's --- and +++ file headers use the a/ and b/
    prefixes that git apply -p1 expects.

    LLMs frequently emit `--- path/to/file` and `+++ path/to/file`
    without the a/ and b/ prefixes. git apply -p1 strips the first
    path component by default, so without the prefixes it strips a
    real directory and looks for the file at the wrong path.

    This normalizes both forms to use a/ and b/.
    """
    lines = diff.split("\n")
    out = []
    for line in lines:
        if line.startswith("--- ") and not line.startswith("--- /dev/null"):
            rest = line[4:]
            if not rest.startswith("a/"):
                rest = "a/" + rest
            out.append("--- " + rest)
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            rest = line[4:]
            if not rest.startswith("b/"):
                rest = "b/" + rest
            out.append("+++ " + rest)
        else:
            out.append(line)
    return "\n".join(out)


def _rewrite_file_headers(
    lines: list[str], repo_relative_path: str
) -> list[str]:
    """
    Rewrite the --- and +++ header lines to point at
    repo_relative_path, preserving the a/ and b/ prefixes git apply
    expects.

    Only the file header lines are touched. Everything else in the
    diff, including hunk bodies, is passed through unchanged.
    """
    out = []
    for line in lines:
        if line.startswith("--- ") and not line.startswith("--- /dev/null"):
            out.append(f"--- a/{repo_relative_path}")
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            out.append(f"+++ b/{repo_relative_path}")
        else:
            out.append(line)
    return out
