"""Tests for HostedVerifier — the Docker-based verifier implementation.

All tests mock asyncio.create_subprocess_exec. Nothing here touches
Docker, the network, or the filesystem beyond tmp dirs. The tests
exercise the orchestration logic: clone, apply, detect, run, retry,
return structured result.

Sandbox and docker CLI behavior are asserted against the argv that
would have been passed to subprocess — see _build_argv_in_tests below.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents import verifier as vmod
from src.agents.verifier import (
    HostedVerifier,
    VerificationResult,
    _detect_node_runner,
    _detect_python_runner,
    _image_for_language,
    _repo_url,
    _run_in_docker,
)


def _fake_proc(returncode=0, stdout=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def test_repo_url_passthrough_https():
    assert _repo_url("https://github.com/owner/repo.git") == "https://github.com/owner/repo.git"


def test_repo_url_expands_short_form():
    assert _repo_url("owner/repo") == "https://github.com/owner/repo.git"


def test_image_for_language_python_default():
    assert "python" in _image_for_language("Python").lower()


def test_image_for_language_node():
    assert "node" in _image_for_language("Node").lower()


# ---------------------------------------------------------------------------
# Runner detection — Python
# ---------------------------------------------------------------------------

def test_detect_python_no_files_returns_none(tmp_path):
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd is None
    assert prefix == "nothing"


def test_detect_python_pyproject_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd and "pytest" in cmd
    assert prefix == "tests"


def test_detect_python_bare_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text("x = 1\n")
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd and "pytest" in cmd


def test_detect_python_ruff_fallback(tmp_path):
    (tmp_path / "ruff.toml").write_text("line-length = 100\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd and "ruff" in cmd
    assert prefix == "linter"


def test_detect_python_mypy_fallback(tmp_path):
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd and "mypy" in cmd
    assert prefix == "typecheck"


def test_detect_python_syntax_only(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    cmd, prefix = _detect_python_runner(tmp_path)
    assert cmd and "compileall" in cmd
    assert prefix == "syntax"


# ---------------------------------------------------------------------------
# Runner detection — Node
# ---------------------------------------------------------------------------

def test_detect_node_no_files_returns_none(tmp_path):
    cmd, prefix = _detect_node_runner(tmp_path)
    assert cmd is None


def test_detect_node_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "index.js").write_text("x\n")
    cmd, prefix = _detect_node_runner(tmp_path)
    assert cmd and "npm test" in cmd
    assert prefix == "tests"


def test_detect_node_tsconfig_fallback(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "index.ts").write_text("x\n")
    cmd, prefix = _detect_node_runner(tmp_path)
    assert cmd and "tsc" in cmd
    assert prefix == "typecheck"


# ---------------------------------------------------------------------------
# Docker invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_in_docker_builds_correct_argv(monkeypatch):
    captured = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return _fake_proc(returncode=0, stdout=b"ok\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")

    exit_code, out = await _run_in_docker(
        image="python:3.11-slim",
        host_workdir=Path("/verifier-workdir/abc"),
        container_workdir="/verifier-workdir",
        command="python -m pytest -q",
        timeout=30,
        memory_limit="1g",
        cpu_limit="1",
    )

    argv = captured["argv"]
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--network" in argv and "none" in argv
    assert "--rm" in argv
    assert "/host/work/abc:/verifier-workdir/abc" in " ".join(argv)
    assert "python:3.11-slim" in argv
    assert exit_code == 0
    assert "ok" in out


@pytest.mark.asyncio
async def test_run_in_docker_timeout_returns_124(monkeypatch):
    proc = MagicMock()
    proc.returncode = None
    async def hang(*a, **k):
        await asyncio.sleep(1000)
    proc.communicate = hang
    proc.kill = MagicMock()
    proc.wait = AsyncMock()

    async def fake_exec(*argv, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")

    exit_code, out = await _run_in_docker(
        image="python:3.11-slim",
        host_workdir=Path("/verifier-workdir/abc"),
        container_workdir="/verifier-workdir",
        command="sleep 999",
        timeout=1,
        memory_limit="1g",
        cpu_limit="1",
    )
    assert exit_code == 124
    assert "timed out" in out


# ---------------------------------------------------------------------------
# HostedVerifier.verify — end to end with mocked subprocess
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_clone_failure_returns_clone_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))

    async def fake_exec(*argv, **kwargs):
        return _fake_proc(returncode=128, stdout=b"fatal: repo not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    v = HostedVerifier()
    result = await v.verify(
        repo_name="owner/repo",
        commit_sha="HEAD",
        diff="x",
        language="Python",
    )
    assert result.passed is False
    assert result.reason == "clone_failed"


@pytest.mark.asyncio
async def test_verify_no_surface_returns_no_verification_surface(monkeypatch, tmp_path):
    """
    Clone and apply succeed but the repo has no .py / .js files — the
    detector returns None and verify reports honestly.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))

    calls = {"n": 0}
    async def fake_exec(*argv, **kwargs):
        calls["n"] += 1
        # First call: clone (success). Second: apply (success). No more.
        return _fake_proc(returncode=0, stdout=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    v = HostedVerifier()
    result = await v.verify(
        repo_name="owner/empty",
        commit_sha="HEAD",
        diff="--- a\n+++ b\n",
        language="Python",
    )
    assert result.passed is False
    assert result.reason == "no_verification_surface"


@pytest.mark.asyncio
async def test_verify_happy_path_returns_tests_passed(monkeypatch, tmp_path):
    """
    Clone succeeds, apply succeeds, detector finds a Python repo
    (create a pyproject.toml so it picks pytest), docker run exits 0.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")
    monkeypatch.setattr(vmod.settings, "VERIFY_MAX_ATTEMPTS", 2)

    call_log = []
    async def fake_exec(*argv, **kwargs):
        call_log.append(argv)
        if argv[0] == "git" and "clone" in argv:
            # Mimic a repo with a pyproject.toml so pytest is detected.
            repo_dir = Path(argv[-1])
            (repo_dir).mkdir(parents=True, exist_ok=True)
            (repo_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
            (repo_dir / "app.py").write_text("x = 1\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "apply" in argv:
            return _fake_proc(returncode=0)
        if argv[0] == "docker":
            return _fake_proc(returncode=0, stdout=b"3 passed\n")
        return _fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    v = HostedVerifier()
    result = await v.verify(
        repo_name="owner/ok",
        commit_sha="HEAD",
        diff="--- a\n+++ b\n",
        language="Python",
    )
    assert result.passed is True
    assert result.reason == "tests_passed"
    assert len(result.attempts) == 1
    assert result.attempts[0]["passed"] is True


@pytest.mark.asyncio
async def test_verify_test_failure_no_repair_returns_tests_failed(monkeypatch, tmp_path):
    """
    Docker run exits non-zero and the LLM is unavailable — verify
    returns tests_failed with one attempt recorded.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")
    monkeypatch.setattr(vmod.settings, "VERIFY_MAX_ATTEMPTS", 2)

    async def fake_exec(*argv, **kwargs):
        if argv[0] == "git" and "clone" in argv:
            repo_dir = Path(argv[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
            (repo_dir / "app.py").write_text("x = 1\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "apply" in argv:
            return _fake_proc(returncode=0)
        if argv[0] == "docker":
            return _fake_proc(returncode=1, stdout=b"1 failed\n")
        return _fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with patch("src.agents.verifier._attempt_repair",
               new=AsyncMock(return_value=None)):
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/fail",
            commit_sha="HEAD",
            diff="--- a\n+++ b\n",
            language="Python",
        )

    assert result.passed is False
    assert result.reason == "tests_failed"
    assert len(result.attempts) == 1
    assert result.attempts[0]["passed"] is False


@pytest.mark.asyncio
async def test_verify_retry_succeeds(monkeypatch, tmp_path):
    """
    First docker run fails, the LLM returns a repaired diff, the
    second run passes. verify returns tests_passed with two attempts.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")
    monkeypatch.setattr(vmod.settings, "VERIFY_MAX_ATTEMPTS", 2)

    docker_calls = {"n": 0}
    async def fake_exec(*argv, **kwargs):
        if argv[0] == "git" and "clone" in argv:
            repo_dir = Path(argv[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
            (repo_dir / "app.py").write_text("x = 1\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "apply" in argv:
            return _fake_proc(returncode=0)
        if argv[0] == "docker":
            docker_calls["n"] += 1
            if docker_calls["n"] == 1:
                return _fake_proc(returncode=1, stdout=b"1 failed\n")
            return _fake_proc(returncode=0, stdout=b"3 passed\n")
        return _fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with patch("src.agents.verifier._attempt_repair",
               new=AsyncMock(return_value="--- a2\n+++ b2\n")):
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/retry",
            commit_sha="HEAD",
            diff="--- a\n+++ b\n",
            language="Python",
            context={"analysis": {"root_cause": "x"}},
        )

    assert result.passed is True
    assert result.reason == "tests_passed"
    assert len(result.attempts) == 2
    assert result.attempts[0]["passed"] is False
    assert result.attempts[1]["passed"] is True


@pytest.mark.asyncio
async def test_verify_attempt_repair_prompt_includes_context_and_output(monkeypatch):
    """
    _attempt_repair must feed BOTH the original context (root cause,
    stack) and the failure output into the prompt — option B shape.
    """
    valid_diff = (
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -42,3 +42,4 @@\n"
        " context\n"
        "-old\n"
        "+new\n"
        "+added\n"
    )

    from src.services.llm_service import RawCompletion

    fake_llm = MagicMock()
    fake_llm.chain = MagicMock()
    fake_llm.complete_raw_detailed = AsyncMock(
        return_value=RawCompletion(
            content=valid_diff,
            finish_reason="stop",
            provider="mock",
            model="mock-model",
        )
    )

    with patch("src.services.llm_service.LLMService", return_value=fake_llm):
        result = await vmod._attempt_repair(
            original_context={
                "analysis": {"root_cause": "pool exhausted",
                             "suggested_fix": "raise pool size"},
                "stack_analysis": {"exception_type": "SQLException",
                                   "file_path": "DB.java",
                                   "line_number": 88},
            },
            failed_output="1 failed: assertion error at test_charge.py:42",
            previous_diff="--- old\n+++ old\n",
        )

    assert result == valid_diff.rstrip()
    prompt = fake_llm.complete_raw_detailed.await_args.kwargs["prompt"]
    assert "pool exhausted" in prompt
    assert "SQLException" in prompt
    assert "assertion error" in prompt
    assert "--- old" in prompt

@pytest.mark.asyncio
async def test_verify_retries_when_diff_does_not_apply(monkeypatch, tmp_path):
    """
    First apply fails with a corrupt-patch error. The retry loop
    calls _attempt_repair, the second apply succeeds, and the test
    run passes. The result should be tests_passed with two attempts.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")
    monkeypatch.setattr(vmod.settings, "VERIFY_MAX_ATTEMPTS", 2)

    apply_calls = {"n": 0}
    async def fake_exec(*argv, **kwargs):
        if argv[0] == "git" and "clone" in argv:
            repo_dir = Path(argv[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
            (repo_dir / "app.py").write_text("x = 1\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "apply" in argv:
            apply_calls["n"] += 1
            if apply_calls["n"] == 1:
                return _fake_proc(returncode=1, stdout=b"error: corrupt patch at line 37\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "checkout" in argv:
            return _fake_proc(returncode=0)
        if argv[0] == "docker":
            return _fake_proc(returncode=0, stdout=b"3 passed\n")
        return _fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with patch("src.agents.verifier._attempt_repair",
               new=AsyncMock(return_value="--- a2\n+++ b2\n@@ -1 +1 @@\n-a\n+b\n")):
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/retry-apply",
            commit_sha="HEAD",
            diff="--- bad\n+++ bad\n@@\n-x\n+y\n",
            language="Python",
        )

    assert result.passed is True
    assert result.reason == "tests_passed"
    assert len(result.attempts) == 2
    assert "git apply failed" in result.attempts[0]["output"]


@pytest.mark.asyncio
async def test_verify_diff_does_not_apply_after_exhausted_retries(monkeypatch, tmp_path):
    """
    Every apply attempt fails. Result is diff_does_not_apply with
    all attempts recorded.
    """
    monkeypatch.setattr(vmod.settings, "VERIFIER_CONTAINER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(vmod.settings, "VERIFIER_HOST_WORKDIR", "/host/work")
    monkeypatch.setattr(vmod.settings, "VERIFY_MAX_ATTEMPTS", 2)

    async def fake_exec(*argv, **kwargs):
        if argv[0] == "git" and "clone" in argv:
            repo_dir = Path(argv[-1])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
            (repo_dir / "app.py").write_text("x = 1\n")
            return _fake_proc(returncode=0)
        if argv[0] == "git" and "apply" in argv:
            return _fake_proc(returncode=1, stdout=b"error: corrupt patch\n")
        if argv[0] == "git" and "checkout" in argv:
            return _fake_proc(returncode=0)
        return _fake_proc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with patch("src.agents.verifier._attempt_repair",
               new=AsyncMock(return_value="--- a2\n+++ b2\n@@ -1 +1 @@\n-a\n+b\n")):
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/all-bad",
            commit_sha="HEAD",
            diff="--- bad\n+++ bad\n",
            language="Python",
        )

    assert result.passed is False
    assert result.reason == "diff_does_not_apply"
    assert len(result.attempts) == 2

@pytest.mark.asyncio
async def test_attempt_repair_extracts_and_validates(monkeypatch):
    """
    _attempt_repair now runs the same extraction as generate_fix:
    a Markdown-wrapped diff comes out bare, and a genuinely bad
    response returns None instead of a string that git apply would
    reject as garbage.
    """
    from src.agents import verifier as vmod

    # Wrapped output — extraction should strip the fence.
    from src.services.llm_service import RawCompletion

    fake_llm = MagicMock()
    fake_llm.chain = MagicMock()
    fake_llm.complete_raw_detailed = AsyncMock(
        return_value=RawCompletion(
            content=(
                "Sure, here you go:\n\n"
                "```diff\n"
                "--- a/x.py\n+++ b/x.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
                "```\n"
            ),
            finish_reason="stop",
            provider="mock",
            model="mock-model",
        )
    )

    with patch("src.services.llm_service.LLMService", return_value=fake_llm):
        result = await vmod._attempt_repair(
            original_context={},
            failed_output="test failed",
            previous_diff="--- a\n+++ b\n",
        )

    assert result is not None
    assert result.startswith("--- a/x.py")
    assert "```" not in result


@pytest.mark.asyncio
async def test_attempt_repair_returns_none_on_garbage(monkeypatch):
    """A response with no diff at all returns None."""
    from src.agents import verifier as vmod

    from src.services.llm_service import RawCompletion

    fake_llm = MagicMock()
    fake_llm.chain = MagicMock()
    fake_llm.complete_raw_detailed = AsyncMock(
        return_value=RawCompletion(
            content="I cannot fix this.",
            finish_reason="stop",
            provider="mock",
            model="mock-model",
        )
    )

    with patch("src.services.llm_service.LLMService", return_value=fake_llm):
        result = await vmod._attempt_repair(
            original_context={},
            failed_output="test failed",
            previous_diff="--- a\n+++ b\n",
        )

    assert result is None

@pytest.mark.asyncio
async def test_attempt_repair_returns_none_on_truncated_response():
    """
    A response that stopped because of the token limit is rejected
    even if the diff-shaped prefix it produced looks valid. This is
    the bug that took six rounds of debugging to identify: a
    truncated diff and a malformed diff both produce "corrupt patch"
    from git apply, and only finish_reason tells them apart.
    """
    from src.agents import verifier as vmod
    from src.services.llm_service import RawCompletion

    # A diff that parses but is incomplete — the hunk header claims
    # more lines than the body contains.
    truncated = (
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,5 +1,5 @@\n"
        " ctx1\n"
        "-old\n"
        "+new\n"
        # body ends here — should have 2 more context lines
    )

    fake_llm = MagicMock()
    fake_llm.chain = MagicMock()
    fake_llm.complete_raw_detailed = AsyncMock(
        return_value=RawCompletion(
            content=truncated,
            finish_reason="length",
            provider="mock",
            model="mock-model",
        )
    )

    with patch("src.services.llm_service.LLMService", return_value=fake_llm):
        result = await vmod._attempt_repair(
            original_context={},
            failed_output="git apply failed",
            previous_diff="--- a\n+++ b\n",
        )

    assert result is None
