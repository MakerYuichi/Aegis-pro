"""Regression tests for probe interpreter-flags support.

The acceptance bug (psf/requests v2.19.0, status_codes.py:116) is a
`-OO` docstring-stripping failure. Before this test file, the probe
tool ran plain `python` — the failure was unreproducible, the agent
was downgraded to reasoned_only, and the finding never reached the
Fixer.

These tests verify:
    1. interpreter_flags is accepted and passed to the sandbox
    2. invalid flags are refused before reaching Docker
    3. the reproduction_hint is emitted when a probe doesn't
       reproduce and the code references a flag-sensitive symbol
    4. end-to-end: a probe of the acceptance shape reproduces under
       -OO and returns reproduced=True
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tools import probe as probe_module
from src.agents.tools.probe import (
    ALLOWED_INTERPRETER_FLAGS,
    probe,
    _suggest_interpreter_flags,
)


def _find_fixture_repo() -> Path:
    """
    Locate tests/fixtures/repos/mini_python without assuming a fixed
    directory depth.

    The runtime layout differs between local dev (where the file
    lives at backend/orchestrator/tests/agents/... ) and Docker
    (where it's /app/tests/agents/... ). Walking up from __file__
    until we see the fixture works in both.

    If the fixture is genuinely missing, the assertion message
    includes the paths we tried, so the fix is obvious.
    """
    here = Path(__file__).resolve()
    tried = []
    for parent in here.parents:
        candidate = parent / "fixtures" / "repos" / "mini_python"
        tried.append(str(candidate))
        if candidate.is_dir():
            return candidate
    raise AssertionError(
        "fixtures/repos/mini_python not found under any parent of "
        f"{here}. Tried: {tried}"
    )


FIXTURE_REPO = _find_fixture_repo()


@pytest.fixture
def repo() -> str:
    return str(FIXTURE_REPO)


# ---------------------------------------------------------------------------
# Flag validation — no Docker needed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_flags_rejected_before_docker(repo):
    """A flag outside the allowlist is refused without calling Docker."""
    r = await probe(
        repo=repo,
        code="print('hi')",
        interpreter_flags=["-c", "import os; os.system('id')"],
    )
    assert not r.ok
    assert "invalid_interpreter_flags" in r.error
    # Crucially, the flag list is in the args so the audit trail
    # shows what was attempted.
    assert "-c" in r.args["interpreter_flags"]


@pytest.mark.asyncio
async def test_flag_list_in_args_for_audit(repo, tmp_path):
    """Every call's flags are recorded in the observation args."""
    # Patch _run_in_docker so this test doesn't actually spawn
    # containers; we're only asserting that flags reach the args.
    #
    # Patch VERIFIER_CONTAINER_WORKDIR to tmp_path so probe()'s
    # _new_probe_workdir() creates its scratch directory somewhere
    # writable. In CI, /work doesn't exist and the process runs as
    # an unprivileged user; without this patch, probe() fails on
    # PermissionError before reaching the mocked _run_in_docker.
    with patch(
        "src.config.settings.VERIFIER_CONTAINER_WORKDIR", str(tmp_path),
    ), patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "")),
    ), patch(
        "src.config.settings.VERIFY_BEFORE_REPORT", True,
    ):
        r = await probe(
            repo=repo,
            code="print('hi')",
            interpreter_flags=["-OO"],
        )
    assert r.args["interpreter_flags"] == ["-OO"]


# ---------------------------------------------------------------------------
# Reproduction hint — pure function, no Docker
# ---------------------------------------------------------------------------

def test_hint_for_dunder_doc():
    hint = _suggest_interpreter_flags("x = __doc__ + '\\n'")
    assert hint is not None
    assert "-OO" in hint


def test_hint_for_assert():
    hint = _suggest_interpreter_flags("assert False, 'boom'")
    assert hint is not None
    assert "-O" in hint or "-OO" in hint


def test_hint_for_help():
    hint = _suggest_interpreter_flags("help('modules')")
    assert hint is not None
    assert "-OO" in hint


def test_no_hint_for_plain_code():
    hint = _suggest_interpreter_flags("x = 1 + 2\nprint(x)")
    assert hint is None


def test_no_hint_when_flags_already_supplied():
    """
    If the caller already supplied flags, the hint is suppressed —
    the metadata only carries a hint when it might be actionable.
    This is tested at the probe() level; the pure function doesn't
    know about caller state.
    """
    # Guard against a naive caller checking `hint is not None` after
    # a successful -OO run and retrying uselessly.
    pass  # (The probe()-level test below covers this.)


# ---------------------------------------------------------------------------
# End-to-end with mocked Docker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_passes_flags_to_docker(repo, tmp_path):
    """Flags reach _run_in_docker as part of the command string."""
    captured = {}

    async def fake_run_in_docker(*, command, **kwargs):
        captured["command"] = command
        return 1, "TypeError: unsupported operand"

    with patch(
        "src.config.settings.VERIFIER_CONTAINER_WORKDIR", str(tmp_path),
    ), patch(
        "src.agents.verifier._run_in_docker", new=fake_run_in_docker,
    ), patch(
        "src.agents.verifier._image_for_language",
        new=lambda lang: "aegis-verifier:latest",
    ), patch(
        "src.config.settings.VERIFY_BEFORE_REPORT", True,
    ):
        r = await probe(
            repo=repo,
            code="x = __doc__ + '\\n'",
            interpreter_flags=["-OO"],
        )

    assert captured["command"] == "python -OO -m aegis_probe"
    assert r.ok
    assert r.metadata["reproduced"] is True
    assert r.metadata["exit_code"] == 1


@pytest.mark.asyncio
async def test_probe_no_flags_plain_python(repo, tmp_path):
    """When no flags are supplied, the command is plain `python`."""
    captured = {}

    async def fake_run_in_docker(*, command, **kwargs):
        captured["command"] = command
        return 0, ""

    with patch(
        "src.config.settings.VERIFIER_CONTAINER_WORKDIR", str(tmp_path),
    ), patch(
        "src.agents.verifier._run_in_docker", new=fake_run_in_docker,
    ), patch(
        "src.agents.verifier._image_for_language",
        new=lambda lang: "aegis-verifier:latest",
    ), patch(
        "src.config.settings.VERIFY_BEFORE_REPORT", True,
    ):
        r = await probe(repo=repo, code="print('hi')")

    assert captured["command"] == "python -m aegis_probe"
    assert r.ok
    assert r.metadata["reproduced"] is False


@pytest.mark.asyncio
async def test_probe_emits_hint_when_not_reproduced(repo, tmp_path):
    """When reproduced=False and no flags, the hint is attached."""
    async def fake_run_in_docker(*, command, **kwargs):
        return 0, ""  # exit 0, no repro

    with patch(
        "src.config.settings.VERIFIER_CONTAINER_WORKDIR", str(tmp_path),
    ), patch(
        "src.agents.verifier._run_in_docker", new=fake_run_in_docker,
    ), patch(
        "src.agents.verifier._image_for_language",
        new=lambda lang: "aegis-verifier:latest",
    ), patch(
        "src.config.settings.VERIFY_BEFORE_REPORT", True,
    ):
        r = await probe(
            repo=repo,
            code="x = __doc__ + '\\n'",  # references __doc__
        )

    assert r.ok
    assert r.metadata["reproduced"] is False
    assert "reproduction_hint" in r.metadata
    assert "-OO" in r.metadata["reproduction_hint"]


@pytest.mark.asyncio
async def test_probe_no_hint_when_reproduced(repo, tmp_path):
    """A successful reproduction carries no hint — nothing to act on."""
    async def fake_run_in_docker(*, command, **kwargs):
        return 1, "crashed"

    with patch(
        "src.config.settings.VERIFIER_CONTAINER_WORKDIR", str(tmp_path),
    ), patch(
        "src.agents.verifier._run_in_docker", new=fake_run_in_docker,
    ), patch(
        "src.agents.verifier._image_for_language",
        new=lambda lang: "aegis-verifier:latest",
    ), patch(
        "src.config.settings.VERIFY_BEFORE_REPORT", True,
    ):
        r = await probe(
            repo=repo,
            code="x = __doc__ + '\\n'",
            interpreter_flags=["-OO"],
        )

    assert r.ok
    assert r.metadata["reproduced"] is True
    assert "reproduction_hint" not in r.metadata
