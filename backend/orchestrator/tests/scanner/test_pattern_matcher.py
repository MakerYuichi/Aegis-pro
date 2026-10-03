"""Tests for the pattern matcher.

Every test parses a small snippet and asserts the matches found.
No file I/O needed — pass the snippet through tmp_path.
"""
from pathlib import Path

import pytest

from src.scanner.pattern_matcher import match_patterns


def _matches(text: str, name: str = "test.py") -> list:
    """Write `text` to a temp file and run the matcher."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(text)
        return match_patterns(p, name)


# ---------------------------------------------------------------------------
# unchecked_optional_attr
# ---------------------------------------------------------------------------

def test_matches_call_then_attr():
    """The matcher fires on `fetch().attr`. When the call is
    assigned to a name and the attribute access uses that name,
    the matcher cannot tell — that's the chain builder's job.
    """
    matches = _matches("x = fetch().total\n")
    assert any(m.pattern == "unchecked_optional_attr" for m in matches)


def test_does_not_match_attr_on_bare_name():
    """`order.total` where order is a name assigned on a previous
    line — matcher sees no call. The chain builder resolves this
    case. This is the boundary between the two.
    """
    matches = _matches("order = fetch()\nreturn order.total\n")
    assert not any(
        m.pattern == "unchecked_optional_attr" for m in matches
    )


def test_matches_direct_call_attr():
    matches = _matches("x = fetch_order().total\n")
    assert any(m.pattern == "unchecked_optional_attr" for m in matches)
    m = [x for x in matches if x.pattern == "unchecked_optional_attr"][0]
    assert m.symbol == "fetch_order"
    assert m.requires_chain is True


def test_matches_subscript_then_attr():
    matches = _matches("x = config['a'].value\n")
    assert any(m.pattern == "unchecked_optional_attr" for m in matches)


def test_ignores_bare_attr():
    """`self.x.y` is not a call or subscript result — no match."""
    matches = _matches("x = self.config.value\n")
    assert not any(m.pattern == "unchecked_optional_attr" for m in matches)


def test_ignores_attr_in_comment():
    matches = _matches("# order.total would crash here\nx = 1\n")
    assert matches == []


def test_ignores_attr_in_string():
    matches = _matches('msg = "order.total is bad"\n')
    assert matches == []


# ---------------------------------------------------------------------------
# unchecked_dict_access
# ---------------------------------------------------------------------------

def test_matches_subscript_on_call():
    matches = _matches("x = get_config()['db']\n")
    assert any(m.pattern == "unchecked_dict_access" for m in matches)


def test_ignores_subscript_on_name():
    """`config['db']` where config is a plain name — no match."""
    matches = _matches("x = config['db']\n")
    assert not any(m.pattern == "unchecked_dict_access" for m in matches)


# ---------------------------------------------------------------------------
# bare_except
# ---------------------------------------------------------------------------

def test_matches_bare_except_pass():
    text = "try:\n    x = 1\nexcept:\n    pass\n"
    matches = _matches(text)
    assert any(m.pattern == "bare_except" for m in matches)
    m = [x for x in matches if x.pattern == "bare_except"][0]
    assert m.requires_chain is False


def test_matches_except_exception_pass():
    text = "try:\n    x = 1\nexcept Exception:\n    pass\n"
    matches = _matches(text)
    assert any(m.pattern == "bare_except" for m in matches)


def test_ignores_except_with_body():
    """An except with a real body isn't a bare-except smell."""
    text = "try:\n    x = 1\nexcept:\n    log(e)\n"
    matches = _matches(text)
    assert not any(m.pattern == "bare_except" for m in matches)


def test_ignores_narrow_except():
    """`except ValueError: pass` is narrow — not flagged."""
    text = "try:\n    x = 1\nexcept ValueError:\n    pass\n"
    matches = _matches(text)
    assert not any(m.pattern == "bare_except" for m in matches)


# ---------------------------------------------------------------------------
# mutable_default_arg
# ---------------------------------------------------------------------------

def test_matches_mutable_list_default():
    matches = _matches("def f(x=[]):\n    pass\n")
    assert any(m.pattern == "mutable_default_arg" for m in matches)


def test_matches_mutable_dict_default():
    matches = _matches("def f(x={}):\n    pass\n")
    assert any(m.pattern == "mutable_default_arg" for m in matches)


def test_ignores_immutable_default():
    matches = _matches("def f(x=None):\n    pass\n")
    assert not any(m.pattern == "mutable_default_arg" for m in matches)


# ---------------------------------------------------------------------------
# comparison_with_none_identity
# ---------------------------------------------------------------------------

def test_matches_eq_none():
    matches = _matches("if x == None:\n    pass\n")
    assert any(m.pattern == "comparison_with_none_identity" for m in matches)


def test_matches_ne_none():
    matches = _matches("if x != None:\n    pass\n")
    assert any(m.pattern == "comparison_with_none_identity" for m in matches)


def test_ignores_is_none():
    matches = _matches("if x is None:\n    pass\n")
    assert not any(m.pattern == "comparison_with_none_identity" for m in matches)


# ---------------------------------------------------------------------------
# Non-Python, syntax errors, missing files
# ---------------------------------------------------------------------------

def test_non_python_returns_empty():
    matches = _matches("const x = 1;\n", name="app.js")
    assert matches == []


def test_syntax_error_returns_empty():
    matches = _matches("def (:\n    pass\n")
    assert matches == []


def test_missing_file_returns_empty(tmp_path):
    assert match_patterns(tmp_path / "nope.py", "nope.py") == []


def test_matches_sorted_by_line():
    text = (
        "if x == None:\n    pass\n"
        "y = fetch().total\n"
    )
    matches = _matches(text)
    assert [m.line for m in matches] == sorted(m.line for m in matches)
