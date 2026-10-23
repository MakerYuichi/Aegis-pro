"""Tests for the CPython module-builtin injection in scan mode.

The Investigator's scan-mode system prompt gains a note when the
candidate's symbol matches a known CPython optional builtin
(__doc__, __file__, __spec__, __loader__, __package__, __path__).

The note is what makes the Investigator confirm findings like
`__doc__ + '\\n'` under -OO mode — without it, the model reasons
"__doc__ is a string" and refuses the finding as a false positive.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.cpython_builtins import (
    OPTIONAL_MODULE_BUILTINS,
    format_note,
    lookup,
)
from src.agents.investigator import InvestigatorAgent
from src.agents.investigator_models import (
    MODE_INCIDENT,
    MODE_SCAN,
    InvestigatorContext,
)


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------

def test_all_six_builtins_are_known():
    """The six CPython builtins documented in the fix are all
    present in the lookup table."""
    for name in ("__doc__", "__file__", "__spec__",
                 "__loader__", "__package__", "__path__"):
        assert name in OPTIONAL_MODULE_BUILTINS
        assert lookup(name) is not None


def test_lookup_normalizes_attribute_access():
    """`module.__doc__` and `__doc__` both resolve to the same entry."""
    assert lookup("__doc__") == lookup("module.__doc__")
    assert lookup("__doc__") == lookup("self.__doc__")


def test_lookup_normalizes_brackets_and_parens():
    """`__path__[0]` and `__path__()` both resolve to `__path__`."""
    assert lookup("__path__") == lookup("__path__[0]")
    # Some analyzers report the symbol with a trailing parens on
    # call-style findings. Normalize the same way.
    assert lookup("__path__") == lookup("__path__()")


def test_lookup_returns_none_for_non_builtin():
    assert lookup("self.headers") is None
    assert lookup("request.body") is None
    assert lookup("") is None
    assert lookup("orders") is None


def test_format_note_names_the_reason():
    """The note must explain *why* the builtin can be None, not
    just *that* it can."""
    note = format_note("__doc__")
    assert note is not None
    assert "-OO" in note
    assert "None" in note


def test_format_note_returns_none_for_non_builtin():
    assert format_note("self.headers") is None
    assert format_note("") is None


# ---------------------------------------------------------------------------
# Prompt injection — the actual behavior change
# ---------------------------------------------------------------------------

def _scan_context_with_symbol(symbol: str) -> InvestigatorContext:
    """A minimal scan-mode context with the given symbol."""
    return InvestigatorContext(
        mode=MODE_SCAN,
        service_name="svc",
        message="Proactive scan finding",
        repo="",
        chain=[],
        symbol=symbol,
    )


def _agent() -> InvestigatorAgent:
    # Mock LLM so we can build the prompt without a provider.
    llm = AsyncMock()
    return InvestigatorAgent(llm_service=llm, repo_root="")


def test_scan_prompt_includes_builtin_note_for_doc():
    """When the context's symbol is __doc__, the system prompt
    contains the CPython builtin note."""
    agent = _agent()
    ctx = _scan_context_with_symbol("__doc__")
    prompt = agent._system_prompt(MODE_SCAN, context=ctx)
    assert "CPython module builtin" in prompt
    assert "-OO" in prompt
    assert "__doc__" in prompt


def test_scan_prompt_includes_builtin_note_for_file():
    """Same for __file__, the other common builtin."""
    agent = _agent()
    ctx = _scan_context_with_symbol("__file__")
    prompt = agent._system_prompt(MODE_SCAN, context=ctx)
    assert "CPython module builtin" in prompt
    assert "__file__" in prompt
    assert "stdin" in prompt


def test_scan_prompt_has_no_builtin_note_for_non_builtin_symbol():
    """A finding on self.headers must NOT get the builtin note."""
    agent = _agent()
    ctx = _scan_context_with_symbol("self.headers")
    prompt = agent._system_prompt(MODE_SCAN, context=ctx)
    assert "CPython module builtin" not in prompt


def test_scan_prompt_has_no_builtin_note_when_symbol_empty():
    """Pattern-matcher findings have no symbol; no note is appended."""
    agent = _agent()
    ctx = _scan_context_with_symbol("")
    prompt = agent._system_prompt(MODE_SCAN, context=ctx)
    assert "CPython module builtin" not in prompt


def test_incident_prompt_never_includes_builtin_note():
    """Incident mode never gets the note, even if the symbol happens
    to be a builtin. Incident diagnosis is grounded in a stack trace,
    not in a Pyright finding."""
    agent = _agent()
    ctx = InvestigatorContext(
        mode=MODE_INCIDENT,
        service_name="svc",
        message="crash",
        repo="",
        symbol="__doc__",   # present, but incident mode ignores it
    )
    prompt = agent._system_prompt(MODE_INCIDENT, context=ctx)
    assert "CPython module builtin" not in prompt


# ---------------------------------------------------------------------------
# The acceptance case
# ---------------------------------------------------------------------------

def test_status_codes_bug_context_gets_the_note():
    """The psf/requests __doc__ bug: symbol is __doc__, pattern is
    optional_operand. The note must be injected. This is the case
    that motivated the fix."""
    agent = _agent()
    ctx = InvestigatorContext(
        mode=MODE_SCAN,
        service_name="requests",
        message=(
            "Proactive scan finding: optional_operand at "
            "requests/status_codes.py:116"
        ),
        repo="requests-buggy",
        chain=[],
        symbol="__doc__",
        pyright_message='Operator "+" not supported for "None"',
    )
    prompt = agent._system_prompt(MODE_SCAN, context=ctx)
    assert "CPython module builtin" in prompt
    assert "-OO" in prompt
    assert "__doc__" in prompt
