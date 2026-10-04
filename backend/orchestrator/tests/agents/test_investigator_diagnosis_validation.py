"""
Tests for the post-hoc diagnosis validator.

The validator checks that a diagnosis is grounded in the agent's own
tool-call history:

    1. The agent actually read the crash line (some observation
       covers it).
    2. The diagnosed symbol appears in the AST statement that
       encloses the crash line within that observation.

Two refusal reasons:
    crash_line_not_observed          — no observation covers the line
    null_source_not_in_crash_statement — the symbol is not in the stmt

All tests are pure functions of (InvestigationResult, history,
crash_file, crash_line). No LLM, no network, no filesystem.
"""
import ast
import pytest

from src.agents.investigator import (
    REFUSAL_REASON_NOT_IN_STATEMENT,
    REFUSAL_REASON_NOT_OBSERVED,
    _find_observation_at_crash,
    _narrowest_statement_at,
    _strip_line_prefixes,
    _symbol_in_ast,
    _symbol_in_crash_statement,
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


def _read_file_obs(
    lines: list[str], start_line: int, end_line: int | None = None
) -> dict:
    """
    Build a read_file observation with the tool's line-number prefix
    format: `NNNNN  <content>`. `lines` is the raw content.
    """
    if end_line is None:
        end_line = start_line + len(lines) - 1
    numbered = "\n".join(
        f"{start_line + i:5d}  {line}" for i, line in enumerate(lines)
    )
    return {
        "iteration": 1,
        "tool": "read_file",
        "args": {"path": "test.py"},
        "ok": True,
        "result": numbered,
        "error": None,
        "truncated": False,
        "metadata": {"start_line": start_line, "end_line": end_line},
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
])
def test_symbol_leaf(symbol, expected):
    assert _symbol_leaf(symbol) == expected


# ---------------------------------------------------------------------------
# _strip_line_prefixes
# ---------------------------------------------------------------------------

def test_strip_line_prefixes_basic():
    text = "    1  x = 1\n    2  y = 2"
    assert _strip_line_prefixes(text) == ["x = 1", "y = 2"]


def test_strip_line_prefixes_preserves_blank_lines():
    text = "    1  x = 1\n    2  \n    3  y = 2"
    assert _strip_line_prefixes(text) == ["x = 1", "", "y = 2"]


def test_strip_line_prefixes_tolerates_unaligned():
    """A line without a prefix passes through."""
    text = "    1  x = 1\nno prefix"
    assert _strip_line_prefixes(text) == ["x = 1", "no prefix"]


# ---------------------------------------------------------------------------
# _find_observation_at_crash
# ---------------------------------------------------------------------------

def test_find_obs_covering_crash_line():
    obs = _read_file_obs(["a = 1", "b = 2"], start_line=10)
    # Window covers 10-11
    assert _find_observation_at_crash([obs], 10) is obs
    assert _find_observation_at_crash([obs], 11) is obs
    assert _find_observation_at_crash([obs], 12) is None
    assert _find_observation_at_crash([obs], 9) is None


def test_find_obs_skips_failed_observation():
    obs = {
        "iteration": 1, "tool": "read_file", "args": {}, "ok": False,
        "result": "", "error": "not_a_file", "truncated": False,
        "metadata": {"start_line": 10, "end_line": 20},
    }
    assert _find_observation_at_crash([obs], 15) is None


def test_find_obs_skips_search_codebase():
    """Only read_file and read_symbol carry window metadata."""
    obs = {
        "iteration": 1, "tool": "search_codebase", "args": {}, "ok": True,
        "result": "a.py:5: x = 1", "error": None, "truncated": False,
        "metadata": {},
    }
    assert _find_observation_at_crash([obs], 5) is None


def test_find_obs_returns_first_match():
    obs_a = _read_file_obs(["a"], start_line=1)
    obs_b = _read_file_obs(["b"], start_line=1)
    assert _find_observation_at_crash([obs_a, obs_b], 1) is obs_a


# ---------------------------------------------------------------------------
# _narrowest_statement_at
# ---------------------------------------------------------------------------

def test_narrowest_statement_finds_innermost():
    src = (
        "def f():\n"
        "    if x:\n"
        "        return a.b.c()\n"
    )
    tree = ast.parse(src)
    stmt = _narrowest_statement_at(tree, 3)
    assert isinstance(stmt, ast.Return)


def test_narrowest_statement_handles_multiline():
    src = (
        "result = foo(\n"
        "    bar,\n"
        "    baz,\n"
        ")\n"
    )
    tree = ast.parse(src)
    # Any line of the call should land in the same statement.
    for line in (1, 2, 3, 4):
        stmt = _narrowest_statement_at(tree, line)
        assert stmt is not None
        assert ast.unparse(stmt).startswith("result = foo(")


def test_narrowest_statement_returns_none_for_blank():
    tree = ast.parse("x = 1\n")
    # Line 2 doesn't exist in the source; no node covers it.
    assert _narrowest_statement_at(tree, 2) is None


# ---------------------------------------------------------------------------
# _symbol_in_ast
# ---------------------------------------------------------------------------

def test_symbol_in_ast_matches_attribute():
    tree = ast.parse("await self.rag.search(x)")
    assert _symbol_in_ast(tree, "self.rag") is True


def test_symbol_in_ast_matches_bare_name_argument():
    """The argument case: `query` never dot-accessed but appears as Name."""
    tree = ast.parse("await self.rag.search_similar_outcomes(query)")
    assert _symbol_in_ast(tree, "query") is True


def test_symbol_in_ast_does_not_match_substring():
    tree = ast.parse("x = storagerag.get('x')")
    assert _symbol_in_ast(tree, "self.rag") is False
    assert _symbol_in_ast(tree, "rag") is False


def test_symbol_in_ast_absent():
    tree = ast.parse("x = 1")
    assert _symbol_in_ast(tree, "code_context") is False


# ---------------------------------------------------------------------------
# _symbol_in_crash_statement
# ---------------------------------------------------------------------------

def test_crash_statement_finds_self_rag():
    """The self.rag case: dereferenced at the crash line."""
    obs = _read_file_obs(
        [
            "async def declare_incident(self, service_name, message):",
            "    outcome = await self.rag.search_similar_outcomes(message, service_name)",
            "    return outcome",
        ],
        start_line=40,
    )
    # Crash line 41 is the search_similar_outcomes call.
    assert _symbol_in_crash_statement(obs, 41, "self.rag") is True


def test_crash_statement_rejects_code_context():
    """The #110 case: code_context is a parameter of an outer def,
    not in the crash statement."""
    obs = _read_file_obs(
        [
            "async def generate_fix(self, incident_data, code_context=None):",
            "    service_name = incident_data.get('service_name')",
            "    file_path = incident_data.get('file_path')",
        ],
        start_line=137,
    )
    # Crash line 139 is the file_path = incident_data.get(...) line.
    assert _symbol_in_crash_statement(obs, 139, "code_context") is False
    # But incident_data IS in the crash statement.
    assert _symbol_in_crash_statement(obs, 139, "incident_data") is True


def test_crash_statement_handles_argument_case():
    """query is passed as an argument — Name node within the call."""
    obs = _read_file_obs(
        [
            "async def handler(self, query):",
            "    outcome = await self.rag.search_similar_outcomes(query)",
            "    return outcome",
        ],
        start_line=10,
    )
    # Line 11: the call. query appears as an argument.
    assert _symbol_in_crash_statement(obs, 11, "query") is True


def test_crash_statement_handles_multiline_call():
    obs = _read_file_obs(
        [
            "result = foo(",
            "    bar,",
            "    code_context,",
            ")",
        ],
        start_line=100,
    )
    # Any line of the call should find code_context in the statement.
    for line in (100, 101, 102, 103):
        assert _symbol_in_crash_statement(obs, line, "code_context") is True


def test_crash_statement_returns_false_on_parse_error():
    """A window that cuts through a block falls back to line text."""
    obs = _read_file_obs(
        [
            "    if x:",   # indented, would fail parse standalone
            "        y = 1",
        ],
        start_line=1,
    )
    # The window doesn't parse as a module. Fallback to text match
    # on the crash line: `x` is present.
    assert _symbol_in_crash_statement(obs, 1, "x") is True
    assert _symbol_in_crash_statement(obs, 1, "nonexistent") is False


# ---------------------------------------------------------------------------
# _validate_diagnosis — integration
# ---------------------------------------------------------------------------

def test_grounded_diagnosis_passes():
    result = _diagnosed("self.rag")
    history = [_read_file_obs(
        [
            "async def declare_incident(self, service_name, message):",
            "    outcome = await self.rag.search_similar_outcomes(message, service_name)",
            "    return outcome",
        ],
        start_line=40,
    )]
    validated = _validate_diagnosis(
        result, history, crash_file="incident_service.py", crash_line=41,
    )
    assert validated.status == STATUS_DIAGNOSED


def test_code_context_diagnosis_refused_as_not_in_statement():
    """The #110 case, end to end."""
    result = _diagnosed("code_context", confidence=0.95)
    history = [_read_file_obs(
        [
            "async def generate_fix(self, incident_data, code_context=None):",
            "    service_name = incident_data.get('service_name')",
            "    file_path = incident_data.get('file_path')",
        ],
        start_line=137,
    )]
    validated = _validate_diagnosis(
        result,
        history,
        crash_file="autofix_service.py",
        crash_line=139,
    )
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_IN_STATEMENT
    assert validated.candidates_considered == ["code_context"]
    # Audit trail preserved.
    assert validated.thought == result.thought
    assert validated.iterations == result.iterations
    assert validated.history == history


def test_no_observation_refused_as_not_observed():
    """The agent never read the crash line."""
    result = _diagnosed("self.rag")
    history = [_read_file_obs(["x = 1"], start_line=1)]
    validated = _validate_diagnosis(
        result,
        history,
        crash_file="incident_service.py",
        crash_line=100,  # far outside the observation
    )
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_OBSERVED
    assert validated.candidates_considered == ["self.rag"]


def test_no_crash_site_refused_as_not_observed():
    """crash_file / crash_line is None — no site to validate against."""
    result = _diagnosed("self.rag")
    validated = _validate_diagnosis(
        result, [], crash_file=None, crash_line=None,
    )
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_OBSERVED


def test_empty_symbol_refused():
    result = _diagnosed("   ")
    history = [_read_file_obs(["x = 1"], start_line=1)]
    validated = _validate_diagnosis(
        result, history, crash_file="test.py", crash_line=1,
    )
    assert validated.status == STATUS_REFUSED
    assert validated.reason == REFUSAL_REASON_NOT_IN_STATEMENT


def test_non_diagnosed_status_untouched():
    for status in ("refused", "timeout", "decision_failed", "iteration_limit"):
        result = InvestigationResult(status=status)
        validated = _validate_diagnosis(
            result, [], crash_file="test.py", crash_line=1,
        )
        assert validated is result


def test_argument_case_passes_validation():
    """query is passed as an argument, never dot-accessed. Should pass."""
    result = _diagnosed("query")
    history = [_read_file_obs(
        [
            "async def handler(self, query):",
            "    outcome = await self.rag.search_similar_outcomes(query)",
            "    return outcome",
        ],
        start_line=10,
    )]
    validated = _validate_diagnosis(
        result, history, crash_file="handler.py", crash_line=11,
    )
    assert validated.status == STATUS_DIAGNOSED


def test_multiline_call_passes_from_any_line():
    result = _diagnosed("code_context")
    history = [_read_file_obs(
        [
            "result = foo(",
            "    bar,",
            "    code_context,",
            ")",
        ],
        start_line=100,
    )]
    # Crash line 102 is the argument line itself.
    validated = _validate_diagnosis(
        result, history, crash_file="test.py", crash_line=102,
    )
    assert validated.status == STATUS_DIAGNOSED
