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
        probe_command = f"python{flag_str} -m aegis_probe"

        exit_code, output = await _run_in_docker(
            image=_image_for_language(language),
            host_workdir=workdir,
            container_workdir=settings.VERIFIER_CONTAINER_WORKDIR,
            command=probe_command,
            timeout=settings.VERIFY_TIMEOUT_SECONDS,
            memory_limit=settings.VERIFIER_MEMORY_LIMIT,
            cpu_limit=settings.VERIFIER_CPU_LIMIT,
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
    """
    if not output:
        return False
    patterns = (
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
    )
    return any(p in output for p in patterns)
