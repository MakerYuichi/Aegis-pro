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
        logger.error(f"[TRACE] verify start repo={repo_name} diff_len={len(diff)}")

        workdir = self._new_workdir()
        try:
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

            command, reason_prefix = _detect_runner(workdir / "repo", language)
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
                try:
                    full = workdir / "repo" / target_path
                    file_lines = full.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except Exception as e:
                    logger.warning(
                        f"Could not read {target_path} for "
                        f"realignment: {e}"
                    )

            if file_lines:
                diff, realignment = _realign_diff(diff, file_lines)
                logger.info(
                    f"Realignment: {realignment.hunks_realigned}/"
                    f"{realignment.hunks_total} hunks realigned, "
                    f"{len(realignment.hunks_flagged)} flagged"
                )

            attempts: list[dict] = []
            max_attempts = max(1, settings.VERIFY_MAX_ATTEMPTS)
            current_diff = diff

            for attempt_num in range(1, max_attempts + 1):
                # Try to apply the current diff. If it doesn't apply,
                # treat that as a failure for this attempt and let the
                # retry loop feed the apply error back to the LLM.
                apply_ok, apply_err = await self._apply_diff(
                    workdir, current_diff, reset=True
                )
                if not apply_ok:
                    # Include a preview of the diff and the commit so
                    # the failure is diagnosable from the incident
                    # record alone. Without the commit, a future
                    # version-mismatch failure would require the same
                    # manual archaeology this run just went through.
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
                        current_diff = repaired
                        continue
                    else:
                        break

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
                    logger.error(f"[TRACE] return: tests_passed attempts={len(attempts)}")
                    return VerificationResult(
                        passed=True,
                        reason=f"{reason_prefix}_passed",
                        output=output,
                        duration_ms=self._ms_since(start),
                        attempts=attempts,
                        verifier="hosted",
                        realignment=realignment,
                    )

                if attempt_num < max_attempts:
                    repaired = await _attempt_repair(
                        original_context=context or {},
                        failed_output=output,
                        previous_diff=current_diff,
                    )
                    if not repaired:
                        break
                    current_diff = repaired

            # If we got here, all attempts failed. The last attempt's
            # output tells the reader what happened — either a test
            # failure or an apply failure.
            last_output = attempts[-1]["output"] if attempts else ""
            last_reason = (
                "diff_does_not_apply"
                if attempts and "git apply failed" in attempts[-1]["output"]
                else f"{reason_prefix}_failed"
            )
            return VerificationResult(
                passed=False,
                reason=last_reason,
                output=last_output,
                duration_ms=self._ms_since(start),
                attempts=attempts,
                verifier="hosted",
                realignment=realignment,
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
        text = diff if diff.endswith("\n") else diff + "\n"
        text = _normalize_diff_paths(text)
        diff_file.write_text(text)
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

_RealignReason = Literal["ambiguous_match", "unanchorable"]


def _realign_diff(diff: str, file_lines: list[str]) -> tuple[str, RealignmentReport]:
    """
    Rewrite each hunk's starting line number by searching the target
    file for that hunk's context and removed lines.

    The LLM frequently produces a diff whose hunk header declares a
    starting line that doesn't match where the hunk's content
    actually appears. git apply --recount fixes counts but not
    starting numbers, so an off-by-10 header causes git apply to
    fail with "patch does not apply" even when the content is
    unambiguous.

    This function is pure: it takes the diff text and the target
    file's lines, and returns a corrected diff plus a report of
    what it did. It never touches the filesystem.

    Algorithm, per hunk:
      1. Build the hunk's search signature from its context (' ')
         and removed ('-') lines. Added ('+') lines are the fix's
         new content and don't exist in the file.
      2. Try three tolerance tiers in order:
           tier 1: exact match
           tier 2: right-strip each line, exact match
           tier 3: strip both sides, compare non-whitespace content
      3. At the first tier that produces matches:
           - exactly one match  -> realign the hunk using the
             file's actual bytes at the matched location
           - zero matches       -> try the next tier
           - more than one      -> stop, flag the hunk as
             "ambiguous_match", leave it unchanged
      4. If no tier produces a match, leave the hunk unchanged.

    Hunks are processed independently. One hunk failing to realign
    does not affect the others.

    A hunk with no context and no removed lines (a pure insertion)
    can't be anchored. If the diff's file header is --- /dev/null,
    that's a new file and realignment isn't meaningful; the hunk is
    left alone silently. If the file header is --- a/path, that's
    a pure insertion into an existing file — a suspicious shape
    that likely means a degenerate header — and the hunk is left
    alone and flagged as "unanchorable".

    "\\ No newline at end of file" markers are skipped when
    building signatures, and their presence in the output is
    derived from file_lines rather than carried over from the
    input diff. The LLM's assertions about newline state are not
    trusted.
    """
    report = RealignmentReport()

    if not lines:
        return diff, report
    lines = diff.split("\n")
    if not lines:
        return diff, report

    # Identify the diff's --- / +++ file header, so we can tell
    # a /dev/null insertion from an existing-file insertion.
    is_new_file = False
    for line in lines:
        if line.startswith("--- "):
            is_new_file = line.startswith("--- /dev/null")
            break

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
    extracted = AutoFixService._trim_trailing_noise(extracted)
    if not AutoFixService._diff_looks_valid(extracted):
        return None
    return extracted

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
