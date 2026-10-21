"""
Tests for src.agents.pytest_parser.

The parser extracts FAILED test IDs from pytest output. Two
output shapes are handled:

  FAILED tests/test_foo.py::test_bar - AssertionError: details
  tests/test_foo.py::test_bar FAILED

The comparison (`new_failures`) is set subtraction. A test that
failed in the baseline and also in the with-diff run is not new.
A test that failed only in the with-diff run is new.
"""
from __future__ import annotations

from src.agents.pytest_parser import new_failures, parse_failed_tests


# ── parse_failed_tests ────────────────────────────────────────

def test_parses_standard_failed_line():
    output = (
        "FAILED tests/test_foo.py::test_bar - AssertionError: "
        "assert 1 == 2\n"
    )
    assert parse_failed_tests(output) == {"tests/test_foo.py::test_bar"}


def test_parses_class_method():
    output = (
        "FAILED tests/test_foo.py::TestClass::test_method - "
        "ValueError: boom\n"
    )
    assert parse_failed_tests(output) == {
        "tests/test_foo.py::TestClass::test_method"
    }


def test_parses_trailing_status_form():
    output = "tests/test_foo.py::test_bar FAILED\n"
    assert parse_failed_tests(output) == {"tests/test_foo.py::test_bar"}


def test_parses_multiple_failures():
    output = (
        "FAILED tests/a.py::test_a - reason\n"
        "FAILED tests/b.py::test_b - reason\n"
        "FAILED tests/b.py::TestC::test_c - reason\n"
    )
    result = parse_failed_tests(output)
    assert result == {
        "tests/a.py::test_a",
        "tests/b.py::test_b",
        "tests/b.py::TestC::test_c",
    }


def test_empty_output_returns_empty_set():
    assert parse_failed_tests("") == set()
    assert parse_failed_tests("\n\n\n") == set()


def test_ignores_passing_and_skipped():
    output = (
        "......................\n"
        "FAILED tests/test_foo.py::test_bar - AssertionError\n"
        "........s.............\n"
    )
    assert parse_failed_tests(output) == {"tests/test_foo.py::test_bar"}


def test_ignores_noise_lines():
    output = (
        "= FAILURES =\n"
        "===== short test summary info =====\n"
        "FAILED tests/test_foo.py::test_bar - reason\n"
        "===== 1 failed, 2 passed in 0.5s =====\n"
    )
    assert parse_failed_tests(output) == {"tests/test_foo.py::test_bar"}


def test_deduplicates_repeated_ids():
    output = (
        "FAILED tests/test_foo.py::test_bar - reason\n"
        "tests/test_foo.py::test_bar FAILED\n"
    )
    assert parse_failed_tests(output) == {"tests/test_foo.py::test_bar"}


# ── new_failures ──────────────────────────────────────────────

def test_new_failures_empty_when_identical():
    baseline = {
        "tests/a.py::test_x",
        "tests/b.py::test_y",
    }
    output = (
        "FAILED tests/a.py::test_x - reason\n"
        "FAILED tests/b.py::test_y - reason\n"
    )
    assert new_failures(output, baseline) == set()


def test_new_failures_includes_only_new():
    baseline = {"tests/a.py::test_x"}
    output = (
        "FAILED tests/a.py::test_x - reason\n"
        "FAILED tests/b.py::test_new - reason\n"
    )
    assert new_failures(output, baseline) == {"tests/b.py::test_new"}


def test_new_failures_empty_when_baseline_is_empty_and_output_empty():
    assert new_failures("", set()) == set()


def test_new_failures_all_when_baseline_is_empty():
    output = "FAILED tests/a.py::test_x - reason\n"
    assert new_failures(output, set()) == {"tests/a.py::test_x"}


def test_new_failures_empty_when_current_run_passes():
    baseline = {"tests/a.py::test_x"}
    assert new_failures("", baseline) == set()


def test_new_failures_ignores_fixed_tests():
    """A test that failed in the baseline but passes now is
    not a new failure. The diff fixed it."""
    baseline = {"tests/a.py::test_x"}
    output = ""  # no failures now
    assert new_failures(output, baseline) == set()
