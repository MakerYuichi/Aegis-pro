"""Tests for the Pyright runner.

These tests do NOT run Pyright against real files — that's the
acceptance test's job (scanning a repo with Pyright installed).
They test the parsing layer:

  - a real Pyright JSON payload is parsed to the right PatternMatch
  - each of the 5 reportOptional* rules maps to the right pattern name
  - non-Optional diagnostics are filtered out
  - malformed JSON returns []
  - pyright not on PATH returns []
  - non-.py files short-circuit before subprocess

The payloads used here are copied from real Pyright output. The
psf/requests #4750 payload is the exact one that motivated this
module.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.scanner.pyright_runner import run_pyright


def _fake_proc(stdout: str, returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def _payload(diagnostics: list[dict]) -> str:
    return json.dumps({
        "version": "1.1.414",
        "generalDiagnostics": diagnostics,
        "summary": {"errorCount": len(diagnostics)},
    })


# ---------------------------------------------------------------------------
# Real payload — the psf/requests #4750 bug
# ---------------------------------------------------------------------------

def test_parses_status_codes_payload(tmp_path):
    """The exact JSON Pyright emits for the psf/requests bug.

    Pyright reports reportOptionalOperand at line 115 (0-indexed).
    The runner converts to line 116 (1-indexed).
    """
    payload = _payload([
        {
            "file": "/work/requests/status_codes.py",
            "severity": "error",
            "message": 'Operator "+" not supported for "None"',
            "range": {
                "start": {"line": 115, "character": 15},
                "end":   {"line": 115, "character": 22},
            },
            "rule": "reportOptionalOperand",
        }
    ])
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc(payload)):
        matches = run_pyright(
            tmp_path / "status_codes.py", "requests/status_codes.py",
        )

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern == "optional_operand"
    assert m.line == 116
    assert m.file == "requests/status_codes.py"
    assert m.confidence == "proven"
    assert m.requires_chain is True


# ---------------------------------------------------------------------------
# All five reportOptional* rules map to distinct pattern names
# ---------------------------------------------------------------------------

def test_all_five_optional_rules_parse(tmp_path):
    rules = [
        "reportOptionalMemberAccess",
        "reportOptionalSubscript",
        "reportOptionalCall",
        "reportOptionalIterable",
        "reportOptionalOperand",
    ]
    diagnostics = [
        {
            "file": "x.py",
            "severity": "error",
            "message": "x",
            "range": {"start": {"line": i}},
            "rule": rule,
        }
        for i, rule in enumerate(rules)
    ]
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch(
        "subprocess.run", return_value=_fake_proc(_payload(diagnostics)),
    ):
        matches = run_pyright(tmp_path / "x.py", "x.py")

    assert len(matches) == 5
    patterns = {m.pattern for m in matches}
    assert patterns == {
        "optional_member_access",
        "optional_subscript",
        "optional_call",
        "optional_iterable",
        "optional_operand",
    }
    # Lines 1-5 (0-indexed → 1-indexed)
    assert [m.line for m in matches] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_ignores_non_optional_rules(tmp_path):
    """Warnings and non-Optional diagnostics are filtered out."""
    payload = _payload([
        {
            "file": "x.py",
            "severity": "warning",
            "message": "Unsupported escape sequence in string literal",
            "range": {"start": {"line": 10}},
            "rule": "reportInvalidStringEscapeSequence",
        },
        {
            "file": "x.py",
            "severity": "error",
            "message": "Something else entirely",
            "range": {"start": {"line": 20}},
            "rule": "reportUndefinedVariable",
        },
    ])
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc(payload)):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


def test_ignores_warning_severity_optional_rule(tmp_path):
    """Even a reportOptional* rule at warning severity is skipped.

    The runner requests --level error, so this shouldn't happen in
    practice. This test documents the belt-and-suspenders check: if
    a warning-severity Optional diagnostic ever appears in the
    output, it's filtered.
    """
    payload = _payload([
        {
            "file": "x.py",
            "severity": "warning",
            "message": "x",
            "range": {"start": {"line": 5}},
            "rule": "reportOptionalOperand",
        }
    ])
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc(payload)):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


# ---------------------------------------------------------------------------
# Failure modes — all return [], never raise
# ---------------------------------------------------------------------------

def test_pyright_missing_returns_empty(tmp_path):
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=False,
    ):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


def test_non_python_file_returns_empty(tmp_path):
    """Non-.py short-circuits before any subprocess call."""
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ) as mock_avail, patch("subprocess.run") as mock_run:
        matches = run_pyright(tmp_path / "app.js", "app.js")
    assert matches == []
    mock_run.assert_not_called()
    mock_avail.assert_not_called()  # file type checked before availability


def test_malformed_json_returns_empty(tmp_path):
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc("not json")):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


def test_empty_stdout_returns_empty(tmp_path):
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc("")):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


def test_subprocess_timeout_returns_empty(tmp_path):
    import subprocess as sp
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch(
        "subprocess.run",
        side_effect=sp.TimeoutExpired(cmd=["pyright"], timeout=60),
    ):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


def test_subprocess_file_not_found_returns_empty(tmp_path):
    """Pyright reports available but the binary vanished."""
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch(
        "subprocess.run", side_effect=FileNotFoundError("pyright"),
    ):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert matches == []


# ---------------------------------------------------------------------------
# Line number conversion
# ---------------------------------------------------------------------------

def test_line_numbers_converted_from_zero_indexed(tmp_path):
    """Pyright is 0-indexed; PatternMatch is 1-indexed."""
    payload = _payload([
        {
            "file": "x.py", "severity": "error", "message": "x",
            "range": {"start": {"line": 0}}, "rule": "reportOptionalOperand",
        },
        {
            "file": "x.py", "severity": "error", "message": "x",
            "range": {"start": {"line": 99}}, "rule": "reportOptionalOperand",
        },
    ])
    with patch(
        "src.scanner.pyright_runner.pyright_available", return_value=True,
    ), patch("subprocess.run", return_value=_fake_proc(payload)):
        matches = run_pyright(tmp_path / "x.py", "x.py")
    assert [m.line for m in matches] == [1, 100]
