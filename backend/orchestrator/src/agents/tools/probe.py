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

import re
import shutil
import tempfile
import uuid
from pathlib import Path

from loguru import logger

from src.agents.tools.repo_tools import ToolResult


MAX_PROBE_CHARS = 4000  # cap the agent's test source

# Flags the agent is permitted to pass. These are the CPython
# interpreter flags that affect module-load-time behavior without
# requiring a new file. Anything outside this set is refused —
# notably, "-c" (arbitrary code), "-m" (arbitrary module), and any
# path argument. The set is intentionally narrow.
ALLOWED_INTERPRETER_FLAGS = frozenset({
    "-O",    # basic optimizations; strips asserts
    "-OO",   # also strips docstrings
    "-B",    # don't write .pyc files
    "-u",    # unbuffered stdout/stderr
    "-E",    # ignore environment variables
    "-S",    # don't run site initialization
    "-q",    # quiet mode
    "-X",    # implementation-specific option; requires the next arg
})

# Patterns the probe checks for when `reproduced=False` and no
# interpreter_flags were supplied. These are the concrete ways
# an agent can be tripped up by not having set the right flags.
_DUNDER_PATTERNS: dict[str, tuple[re.Pattern, list[str]]] = {
    "__doc__": (
        re.compile(r"\b__doc__\b"),
        ["-OO"],
    ),
    "__file__": (
        re.compile(r"\b__file__\b"),
        ["-c", "-m"],  # informational; not in allowlist
    ),
    "__spec__": (
        re.compile(r"\b__spec__\b"),
        ["-c", "-m"],  # informational
    ),
    "assert": (
        re.compile(r"^\s*assert\b", re.MULTILINE),
        ["-O", "-OO"],
    ),
    "help()": (
        re.compile(r"\bhelp\s*\("),
        ["-OO"],
    ),
}


async def probe(
    repo: str,
    code: str,
    language: str = "Python",
    interpreter_flags: list[str] | None = None,
    cache_host_path: str | None = None,
    manifest_relative_path: str | None = None,
) -> ToolResult:
    """Run a small test in the verifier's sandbox.

    [unchanged docstring for the base case...]

    `interpreter_flags`, when supplied, is prepended to the python
    invocation inside the sandbox: `python -OO -m aegis_probe`.
    The list must contain only flags from ALLOWED_INTERPRETER_FLAGS;
    anything else is refused with error="invalid_interpreter_flags".

    When `reproduced=False`, the result metadata contains
    `reproduction_hint`: a short string the agent can act on. See
    `_suggest_interpreter_flags` for how it is derived.
    """
    args = {
        "language": language,
        "code": code[:MAX_PROBE_CHARS] if code else "",
        "code_chars": len(code or ""),
        "interpreter_flags": list(interpreter_flags or []),
    }

    if not code or not code.strip():
        return ToolResult(
            ok=False, tool="probe", args=args, error="empty_code",
        )

    if len(code) > MAX_PROBE_CHARS:
        return ToolResult(
            ok=False, tool="probe", args=args,
            error=f"code_too_long: {len(code)} > {MAX_PROBE_CHARS}",
        )

    # Validate flags before anything else — cheap, and the error
    # message tells the agent what's allowed.
    flags = list(interpreter_flags or [])
    invalid = [f for f in flags if f not in ALLOWED_INTERPRETER_FLAGS]
    if invalid:
        return ToolResult(
            ok=False, tool="probe", args=args,
            error=(
                f"invalid_interpreter_flags: {invalid!r}; "
                f"allowed: {sorted(ALLOWED_INTERPRETER_FLAGS)}"
            ),
        )

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return ToolResult(
            ok=False, tool="probe", args=args, error="repo_not_found",
        )

    from src.agents.verifier import _run_in_docker, _image_for_language
    from src.config import settings

    if not settings.VERIFY_BEFORE_REPORT:
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

        # Build the command with flags. The flags were validated
        # against ALLOWED_INTERPRETER_FLAGS above, so the only
        # tokens reaching the shell are allowlisted and the module
        # name is a fixed string. There is no path through this
        # code where agent-supplied text becomes a shell token.
        flag_str = (" " + " ".join(flags)) if flags else ""

        # When the pipeline has prefetched deps, install them into a
        # venv inside the probe container, then run the probe from
        # that venv. This makes `import <repo_module>` work so the
        # agent can write probes that test the actual code instead of
        # toy reproductions that don't load the tree.
        # The probe container mounts `workdir` at
        # <VERIFIER_CONTAINER_WORKDIR>/<workdir.name>. `workdir.name`
        # is "probe-<uuid>", and the repo is copied into
        # `workdir/repo`, so the tree root inside the container is:
        #   <VERIFIER_CONTAINER_WORKDIR>/<workdir.name>/repo
        # The previous command hardcoded `/work/probe-repo`, which
        # is not where anything is mounted. `cd` failed, pip never
        # ran, and every probe that imported tree code hit
        # ModuleNotFoundError.
        container_workdir = settings.VERIFIER_CONTAINER_WORKDIR
        container_repo = (
            f"{container_workdir}/{workdir.name}/repo"
        )
        if cache_host_path and manifest_relative_path:
            probe_command = (
                f"cd {container_repo} && "
                "python -m venv /tmp/venv && "
                "/tmp/venv/bin/pip install --no-index --find-links /cache "
                "--quiet -r /cache/requirements.lock && "
                f"PATH=/tmp/venv/bin:$PATH "
                f"PYTHONPATH={container_repo} "
                f"python{flag_str} -m aegis_probe"
            )
        else:
            probe_command = f"python{flag_str} -m aegis_probe"

        exit_code, output = await _run_in_docker(
            image=_image_for_language(language),
            host_workdir=workdir,
            container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
            command=probe_command,
            timeout=settings.VERIFY_TIMEOUT_SECONDS,
            memory_limit=settings.VERIFIER_MEMORY_LIMIT,
            cpu_limit=settings.VERIFIER_CPU_LIMIT,
            cache_host_path=(
                Path(cache_host_path) if cache_host_path else None
            ),
        )

        reproduced = (exit_code != 0) or _output_signals_bug(output)


        # Build metadata. When reproduced is False and no flags were
        # supplied, check whether the code likely needs them.
        metadata: dict = {
            "ran": True,
            "reproduced": reproduced,
            "exit_code": exit_code,
        }
        if not reproduced and not flags:
            hint = _suggest_interpreter_flags(code)
            if hint:
                metadata["reproduction_hint"] = hint

        return ToolResult(
            ok=True,
            tool="probe",
            args=args,
            result=output,
            metadata=metadata,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _suggest_interpreter_flags(code: str) -> str | None:
    """
    Inspect the agent's probe source. If it references a symbol
    whose value depends on interpreter flags, return a hint string
    suggesting the flag.

    The hint is advisory — the agent decides whether to retry.
    Returning None means "no evidence the flags are needed", which
    is the honest answer when the code doesn't touch dunders.
    """
    for symbol, (pattern, flags) in _DUNDER_PATTERNS.items():
        if pattern.search(code):
            usable = [f for f in flags if f in ALLOWED_INTERPRETER_FLAGS]
            if not usable:
                continue
            flag_list = ", ".join(repr(f) for f in usable)
            return (
                f"probe referenced {symbol!r} but ran without "
                f"interpreter flags; the value of {symbol} depends on "
                f"the interpreter mode. If the failure mode requires "
                f"{flag_list}, retry with interpreter_flags=[{flag_list}]."
            )
    return None


def _new_probe_workdir() -> Path:
    from src.config import settings
    base = Path(settings.VERIFIER_CONTAINER_WORKDIR)
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"probe-{uuid.uuid4().hex[:12]}"
    target.mkdir(parents=True, exist_ok=False)
    return target

def _output_signals_bug(output: str) -> bool:
    """
    Return True if the probe's output contains a Python exception
    signature — i.e., the code caught the exception and printed it
    (as agents often do), rather than letting it propagate.

    Two forms of exception output are recognized:

    1. Python's default uncaught-exception traceback:
         Traceback (most recent call last):
         ...
         TypeError: unsupported operand type(s)

       In this form the exception class name is followed by a
       colon — `TypeError:`, `AttributeError:`, etc.

    2. Agent-written try/except that prints `type(e).__name__` and
       the message separately:
         try:
             ...
         except Exception as e:
             print('Error:', type(e).__name__, e)

       In this form the output is:
         Error: TypeError unsupported operand type(s)

       The exception class name is followed by a SPACE, not a
       colon. The previous version of this function only matched
       form (1); form (2) was missed, causing probe runs that
       reproduced a bug to be classified as "passed." See
       INC-20261027-5DDC5A: the probe printed
       "Error: TypeError unsupported operand type(s)..."
       and was classified as `before_passed=True`, leading to
       `probe_ambiguous` and a false negative.

    Also matches the runtime-error prefix "ERROR:" that pip and
    other tools emit, and the string "ModuleNotFoundError" without
    a colon (the most common form for missing-deps failures).
    """
    if not output:
        return False

    # Form 1: `TypeError: ...` (traceback style, with colon)
    COLONED = (
        "TypeError:",
        "AttributeError:",
        "KeyError:",
        "ValueError:",
        "RuntimeError:",
        "AssertionError:",
        "ImportError:",
        "ModuleNotFoundError:",
        "SyntaxError:",
        "IndexError:",
        "FileNotFoundError:",
        "PermissionError:",
        "OSError:",
        "NameError:",
        "NotImplementedError:",
        "StopIteration:",
        "UnicodeError:",
    )

    # Form 2: `Error: TypeError unsupported ...` (agent style, class
    # name followed by space and the message)
    SPACED_CLASSES = (
        "TypeError ",
        "AttributeError ",
        "KeyError ",
        "ValueError ",
        "RuntimeError ",
        "AssertionError ",
        "ImportError ",
        "ModuleNotFoundError ",
        "SyntaxError ",
        "IndexError ",
        "FileNotFoundError ",
        "PermissionError ",
        "OSError ",
        "NameError ",
        "NotImplementedError ",
    )

    # Verifier-friendly: `_output_signals_bug` is also used in
    # verifier.py to classify probes. Include the string forms
    # that appear regardless of whether a colon is present.
    return (
        any(p in output for p in COLONED)
        or any(p in output for p in SPACED_CLASSES)
    )
