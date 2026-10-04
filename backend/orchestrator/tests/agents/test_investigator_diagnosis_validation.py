"""
Tests for the post-hoc diagnosis validator.

The validator checks that a diagnosed symbol is *grounded*: it
appears in the code the agent fetched, at a site where it is
dereferenced. It does not check correctness — that's the Verifier's
job downstream.

All tests are pure functions of (InvestigationResult, history).
No LLM, no network, no filesystem.
"""
import pytest

from src.agents.investigator import (
    REFUSAL_REASON_NOT_VISIBLE,
    _symbol_is_grounded,
    _symbol_leaf,
    _validate_diagnosis,
)
from src.agents.investigator_models import (
    STATUS_DIAGNOSED,
    STATUS_REFUSED,
    InvestigationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _diagnosed(symbol: str, confidence: float = 0.9) -> InvestigationResult:
    return InvestigationResult(
        status=STATUS_DIAGNOSED,
        null_source=symbol,
        evidence="test",
        confidence=confidence,
        iterations=3,
    )


def _read_file_obs(text: str, iteration: int = 1) -> dict:
    """A successful read_file observation carrying `text` as its result."""
    return {
        "iteration": iteration,
        "tool": "read_file",
        "args": {"path": "test.py"},
        "ok": True,
        "result": text,
        "error": None,
        "truncated": False,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# _symbol_leaf
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,expected", [
    ("self.rag", "rag"),
    ("get_rag_service", "get_rag_service"),
    ("get_rag_service()", "get_rag_service"),
    ("order.items[0]", "items"),
    ("x", "x"),
    ("", ""),
    ("   ", ""),
    ("self.rag()", "rag"),
])
def test_symbol_leaf_extraction(symbol, expected):
    assert _symbol_leaf(symbol) == expected


# ---------------------------------------------------------------------------
# _symbol_is_grounded
# ---------------------------------------------------------------------------

def test_grounded_when_symbol_is_dereferenced():
    history = [_read_file_obs(
        "   40      outcome = await self.rag.search_similar_outcomes(\n"
    )]
    assert _symbol_is_grounded("self.rag", history) is True


def test_grounded_when_symbol_is_subscripted():
    history = [_read_file_obs("   12      x = config['db']\n")]
    assert _symbol_is_grounded("config", history) is True


def test_grounded_when_symbol_is_called():
    history = [_read_file_obs(
        "   14      order = fetch_order(order_id)\n"
    )]
    assert _symbol_is_grounded("fetch_order", history) is True


def test_not_grounded_when_symbol_only_in_signature():
    """The #110 case: code_context appears as a parameter, never used."""
    history = [_read_file_obs(
        "  137  async def generate_fix(self, incident_data, code_context=None):\n"
        "  138      service_name = incident_data.get('service_name')\n"
    )]
    assert _symbol_is_grounded("code_context", history) is False


def test_not_grounded_when_symbol_only_in_comment():
    history = [_read_file_obs(
        "   14      # TODO: code_context may be None here\n"
        "   15      x = 1\n"
    )]
    assert _symbol_is_grounded("code_context", history) is False


def test_not_grounded_when_symbol_absent():
    history = [_read_file_obs("   1      x = 1\n")]
    assert _symbol_is_grounded("never_seen", history) is False


def test_not_grounded_when_history_is_empty():
    assert _symbol_is_grounded("anything", []) is False


def test_not_grounded_when_all_observations_failed():
    history = [{
        "iteration": 1, "tool": "read_file", "args": {}, "ok": False,
        "result": "", "error": "not_a_file", "truncated": False,
        "metadata": {},
    }]
    assert _symbol_is_grounded("x", history) is False


def test_substring_does_not_falsely_match():
    """`rag` must not match `storagerag.`"""
    history = [_read_file_obs(
        "   8      y = storagerag.get('x')\n"
    )]
    assert _symbol_is_grounded("self.rag", history) is False


def test_symbol_matches_across_multiple_observations():
    """The symbol appears in the second observation, not the first."""
    history = [
        _read_file_obs("   1      x = 1\n", iteration=1),
        _read_file_obs("   8      y = self.rag.lookup()\n", iteration=2),
    ]
    assert _symbol_is_grounded("self.rag", history) is True


def test_dereference_after_whitespace():
    """`x = foo .bar` — unusual but valid Python, and a dereference."""
    history = [_read_file_obs("   5      y = foo .bar()\n")]
    assert _symbol_is_grounded("foo", history) is True


# ---------------------------------------------------------------------------
# _validate_diagnosis — the integration
# ---------------------------------------------------------------------------

def test_grounded_diagnosis_passes_through():
    result = _diagnosed("self.rag")
    history = [_read_file_obs(
        "   40      await self.rag.search_similar_outcomes()\n"
    )]
    validated = _validate_diagnosis(result, history)
    assert validated.status == STATUS_DIAGNOSED
    assert validated.null_source == "self.rag"
    assert validated.confidence == 0.9


def test_ungrounded_diagnosis_becomes_refusal():
    result = _diagnosed("code_context", confidence=0.95)
    history = [_read_file_obs(
        "  137  def generate_fix(self, code_context=None):\n"
        "  138      pass\n"
    )]
    validated = _validate_diagnosis(result, history)
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_VISIBLE
    assert validated.candidates_considered == ["code_context"]
    # Iteration count and history are preserved so the audit trail
    # shows what the agent actually did.
    assert validated.iterations == result.iterations
    assert validated.history == history


def test_empty_symbol_becomes_refusal():
    result = _diagnosed("   ")
    history = [_read_file_obs("   1      x = 1\n")]
    validated = _validate_diagnosis(result, history)
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_VISIBLE
    assert validated.candidates_considered == []


def test_non_diagnosed_status_unchanged():
    """The validator only touches diagnosed results."""
    for status in ("refused", "timeout", "decision_failed", "iteration_limit"):
        result = InvestigationResult(status=status)
        validated = _validate_diagnosis(result, [])
        assert validated is result  # same object, untouched


def test_evidence_and_thought_are_preserved_on_refusal():
    """The audit trail matters — a refusal still carries what the
    agent was thinking."""
    result = InvestigationResult(
        status=STATUS_DIAGNOSED,
        null_source="code_context",
        evidence="code_context is a parameter and may be None",
        confidence=0.95,
        thought="I think code_context is the null source.",
        iterations=4,
    )
    history = [_read_file_obs(
        "  137  def generate_fix(self, code_context=None):\n"
        "  138      pass\n"
    )]
    validated = _validate_diagnosis(result, history)
    assert validated.status == STATUS_REFUSED
    assert validated.thought == "I think code_context is the null source."
    assert validated.iterations == 4
