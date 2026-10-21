"""
Parse pytest output into a set of test identifiers.

The verifier's baseline run compares failures from a no-diff run
against failures from a with-diff run. What matters is the set of
"path::test_id" strings that failed, not the reason. A test that
fails for the same reason both times is a pre-existing failure.
A test that fails only in the with-diff run was broken by the
diff.

Pytest emits FAILED in two forms depending on the version and
flags:

  FAILED tests/test_foo.py::test_bar - AssertionError: details
  tests/test_foo.py::test_bar FAILED

Both are parsed. The parser is deliberately permissive about the
reason field (which may contain colons, quotes, and stack trace
fragments) — only the "path::test_id" prefix matters.

Failure to parse is not failure to detect. If a line looks like a
test ID at the start but the format is unexpected, the parser
still extracts the ID portion. Better to over-count failures (a
false positive in the baseline makes the with-diff run look safer
than it is) than under-count (a false negative makes a real
regression invisible).

The opposite trade-off is wrong for a security tool. Losing a
regression is worse than a spurious repair attempt. Prefer
over-counting.
"""
from __future__ import annotations

import re


# "FAILED tests/test_foo.py::test_bar - AssertionError: ..."
# "FAILED tests/test_foo.py::TestClass::test_method - ..."
# The reason part after " - " is optional (some pytest versions
# omit it under --tb=no).
_FAILED_LINE_RE = re.compile(
    r"^FAILED\s+(?P<test_id>[^\s]+(?:::[^\s]+)*)"
    r"(?:\s+-\s+.*)?$",
)

# "tests/test_foo.py::test_bar FAILED"
# The status can be "FAILED", "ERROR", "XPASS". The verifier
# only treats FAILED as a test failure — ERROR usually means a
# fixture or collection problem, and XPASS is a passed test that
# was marked xfail. Including those in the baseline would hide
# real regressions.
_STATUS_TRAILING_RE = re.compile(
    r"^(?P<test_id>[^\s]+(?:::[^\s]+)*)\s+FAILED\s*$",
)

# pytest's short summary includes lines like:
#   FAILED tests/foo.py::bar - reason
# and the full test output uses dots and F characters.
# Only the summary is parsed; the F characters in the progress
# line don't include test IDs.
_PYTEST_NOISE_RE = re.compile(
    r"^(=+ FAILURES =+|"
    r"-+ Captured .* -+|"
    r"=+ short test summary info =+|"
    r"=+ \d+ (passed|failed|skipped|error))",
)


def parse_failed_tests(output: str) -> set[str]:
    """
    Return the set of test IDs that pytest reported as FAILED.

    A test ID is "<path>::<test_name>" or
    "<path>::<Class>::<test_method>". The parser strips the
    reason suffix and returns the ID alone.

    Empty output returns an empty set. Malformed output returns
    whatever the parser could extract — better partial than
    nothing.
    """
    if not output:
        return set()

    failures: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _PYTEST_NOISE_RE.match(stripped):
            continue

        m = _FAILED_LINE_RE.match(stripped)
        if m:
            failures.add(m.group("test_id").rstrip(":"))
            continue

        m = _STATUS_TRAILING_RE.match(stripped)
        if m:
            failures.add(m.group("test_id").rstrip(":"))

    return failures


def new_failures(
    current_output: str,
    baseline_failures: set[str],
) -> set[str]:
    """
    Return failures in `current_output` that are not in
    `baseline_failures`.

    The comparison is set subtraction. If a test failed in the
    baseline and also in the current run, it's not new. If it
    failed only in the current run, the diff caused it.
    """
    current = parse_failed_tests(current_output)
    return current - baseline_failures
