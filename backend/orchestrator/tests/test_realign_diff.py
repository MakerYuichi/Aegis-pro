"""
Tests for _realign_diff — the pure function that rewrites hunk
headers by searching the target file.

Realignment exists because the LLM frequently produces a diff whose
hunk header declares a starting line that doesn't match where the
hunk's content actually appears. git apply --recount fixes counts
but not starting numbers, so the header has to be corrected by
searching the file.

These tests use hand-written file fixtures. No filesystem, no
Docker, no LLM.
"""
import pytest

from src.agents.verifier import _realign_diff, RealignmentReport




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file(*lines: str) -> list[str]:
    """Build a file_lines list from varargs."""
    return list(lines)


def _diff(*body_lines: str, header: str = "@@ -1,1 +1,1 @@",
          old_file: str = "a/x.py", new_file: str = "b/x.py") -> str:
    """Build a diff string from a header and body lines."""
    return "\n".join([f"--- {old_file}", f"+++ {new_file}", header, *body_lines])


# ---------------------------------------------------------------------------
# Basic realignment
# ---------------------------------------------------------------------------

def test_realigns_hunk_to_correct_line():
    """
    Diff header says line 1, but the hunk's context actually appears
    at line 4 in the file. Realignment moves the header to 4 and
    rewrites the body from the file's actual bytes.
    """
    file_lines = _file(
        "line1",
        "line2",
        "line3",
        "def foo():",
        "    return 1",
    )
    diff = _diff(
        " def foo():",
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 1
    assert report.hunks_realigned == 1
    assert report.hunks_unchanged == 0
    assert report.hunks_flagged == []

    assert "@@ -4,2 +4,2 @@" in realigned
    assert " def foo():" in realigned
    assert "-    return 1" in realigned
    assert "+    return 2" in realigned


def test_idempotent_when_header_already_correct():
    """
    A hunk already anchored at the right line is unchanged.
    """
    file_lines = _file("def foo():", "    return 1")
    diff = _diff(
        " def foo():",
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_realigned == 0
    assert report.hunks_unchanged == 1
    assert report.hunks_flagged == []
    assert realigned == diff


# ---------------------------------------------------------------------------
# The new behavior: context_not_found
# ---------------------------------------------------------------------------

def test_flags_context_not_found_when_hunk_matches_nowhere():
    """
    The hunk's context does not appear anywhere in the file. The
    LLM invented it. The hunk is flagged as 'context_not_found'
    rather than silently left as 'unchanged'.

    This is the case that produces the end-to-end bug: the LLM's
    diff says '# Stage 4 — Investigator' but the file says
    '# Stage 4 — Verifier'. Realignment can't match the invented
    comment, so the hunk should be flagged.
    """
    file_lines = _file(
        "def foo():",
        "    # real comment",
        "    return 1",
    )
    diff = _diff(
        " # invented comment",  # not in the file
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 1
    assert report.hunks_realigned == 0
    assert report.hunks_unchanged == 1
    assert report.hunks_flagged == [
        {"index": 0, "reason": "context_not_found"},
    ]


def test_flags_only_the_unmatchable_hunk_others_realign():
    """
    Two hunks in one diff. The first matches somewhere in the file,
    the second doesn't. Only the second is flagged; the first is
    realigned. Per-hunk independence.
    """
    file_lines = _file(
        "header",
        "def foo():",
        "    return 1",
        "middle",
        "def bar():",
        "    return 2",
    )
    diff = "\n".join([
        "--- a/x.py",
        "+++ b/x.py",
        "@@ -1,2 +1,2 @@",
        " def foo():",
        "-    return 1",
        "+    return 3",
        "@@ -1,2 +1,2 @@",
        " # comment that does not exist",
        "-    some_removed_line",
        "+    some_added_line",
    ])

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 2
    assert report.hunks_realigned == 1
    assert report.hunks_unchanged == 1
    assert report.hunks_flagged == [
        {"index": 1, "reason": "context_not_found"},
    ]
    assert "@@ -2,2 +2,2 @@" in realigned


# ---------------------------------------------------------------------------
# Ambiguous match (existing behavior, still correct)
# ---------------------------------------------------------------------------

def test_flags_ambiguous_when_signature_matches_multiple_locations():
    """
    The hunk's context appears at two locations in the file. There's
    no way to know which one the LLM meant. The hunk is flagged as
    'ambiguous_match' and left alone.
    """
    file_lines = _file(
        "def foo():",
        "    return 1",
        "def foo():",
        "    return 1",
    )
    diff = _diff(
        " def foo():",
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 1
    assert report.hunks_realigned == 0
    assert report.hunks_unchanged == 1
    assert report.hunks_flagged == [
        {"index": 0, "reason": "ambiguous_match"},
    ]


# ---------------------------------------------------------------------------
# Tolerance tiers
# ---------------------------------------------------------------------------

def test_rstrip_tier_matches_and_realigns():
    """
    Tier 2 matches at a line that isn't the declared line. The
    header moves.
    """
    file_lines = _file(
        "line1",
        "def foo():",
        "    return 1",
    )
    diff = _diff(
        " def foo():   ",       # trailing whitespace
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",   # header claims line 1, real is line 2
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_realigned == 1
    assert "@@ -2,2 +2,2 @@" in realigned


def test_strip_tier_matches_when_rstrip_does_not():
    """
    The LLM's context has different indentation than the file.
    Tier 3 (strip both sides) matches on content alone.
    """
    file_lines = _file("def foo():", "    return 1")
    diff = _diff(
        "def foo():",           # no leading space; real line has none
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_realigned == 1


# ---------------------------------------------------------------------------
# Pure-addition hunks
# ---------------------------------------------------------------------------

def test_pure_addition_against_dev_null_is_not_flagged():
    """
    A new-file diff has no context to anchor. Realignment is
    meaningless. Not flagged — nothing is wrong.
    """
    file_lines = _file()  # empty file
    diff = _diff(
        "+line 1",
        "+line 2",
        header="@@ -0,0 +1,2 @@",
        old_file="/dev/null",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 1
    assert report.hunks_unchanged == 1
    assert report.hunks_flagged == []


def test_pure_addition_against_existing_file_is_flagged_unanchorable():
    """
    A pure-addition hunk against an existing file has no context and
    no removed lines to search for. That's a suspicious shape — a
    normal diff against an existing file includes context. Flagged
    as 'unanchorable'.
    """
    file_lines = _file("def foo():", "    return 1")
    diff = _diff(
        "+new line",
        header="@@ -1,0 +1,1 @@",
        old_file="a/x.py",
    )

    realigned, report = _realign_diff(diff, file_lines)

    assert report.hunks_total == 1
    assert report.hunks_flagged == [
        {"index": 0, "reason": "unanchorable"},
    ]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_file_lines_leaves_diff_unchanged():
    """
    No file content to search. The function returns the input diff
    and a report with zero hunks (since the search never runs).
    """
    diff = _diff(
        " def foo():",
        "-    return 1",
        "+    return 2",
        header="@@ -1,2 +1,2 @@",
    )

    realigned, report = _realign_diff(diff, [])

    assert realigned == diff
    assert report.hunks_total == 0


def test_no_hunks_returns_input_unchanged():
    """A diff with no @@ header is passed through untouched."""
    diff = "--- a/x.py\n+++ b/x.py\n"
    realigned, report = _realign_diff(diff, _file("def foo():"))

    assert realigned == diff
    assert report.hunks_total == 0
