"""
Tests for the Investigator agent loop.

The only method mocked is `_decide`. Everything else — parsing,
tool dispatch, the loop, the terminal results — runs for real against
the mini_python fixture repo.

No LLM call is made anywhere in this file.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.investigator import (
    DEFAULT_CONFIDENCE,
    REFUSAL_REASON_NOT_OBSERVED,
    THOUGHT_MAX_CHARS,
    InvestigatorAgent,
)
from src.agents.investigator_models import (
    STATUS_DECISION_FAILED,
    STATUS_DIAGNOSED,
    STATUS_ITERATION_LIMIT,
    STATUS_REFUSED,
    STATUS_TIMEOUT,
    InvestigatorAction,
    InvestigatorContext,
)

FIXTURE_REPO = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "repos"
    / "mini_python"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo() -> str:
    assert FIXTURE_REPO.is_dir(), f"fixture repo missing: {FIXTURE_REPO}"
    return str(FIXTURE_REPO)


@pytest.fixture
def context(repo) -> InvestigatorContext:
    """The #105 case A shape: null source is identifiable."""
    return InvestigatorContext(
        service_name="incident-service",
        message="AttributeError: NoneType has no attribute 'search_similar_outcomes'",
        repo=repo,
        stack_trace=(
            "AttributeError: 'NoneType' object has no attribute "
            "'search_similar_outcomes'\n"
            "    at IncidentService.declare_incident(incident_service.py:34)"
        ),
        exception_type="AttributeError",
        file_path="incident_service.py",
        line_number=34,
                code_window={
            "start_line": 30,
            "end_line": 35,
            "snippet": (
                "   30          self.rag = get_rag_service()\n"
                "   31          self.timeout = 30\n"
                "   32  \n"
                "   33      async def declare_incident(self, service_name: str, message: str):\n"
                "   34          outcome = await self.rag.search_similar_outcomes(message, service_name)\n"
                "   35          return outcome\n"
            ),
        },
        blame={"author": "eng@acme.com", "commit_hash": "abc1234",
               "message": "wire up rag lookup"},
        related_prs=[
            {"number": 42, "title": "Add RAG lookup to declare_incident",
             "reason": "touched incident_service.py"},
        ],
        blast_radius={"root": "incident-service",
                      "affected": ["incident-service"], "count": 1},
    )


@pytest.fixture
def agent(repo) -> InvestigatorAgent:
    """InvestigatorAgent with a stub LLM. `_decide` is overridden per test."""
    llm = MagicMock()
    llm.complete_raw_detailed = AsyncMock(return_value=None)
    return InvestigatorAgent(llm_service=llm, repo_root=repo)


def _scripted_decide(*actions: InvestigatorAction | None):
    """
    Return an async function that yields the given actions in order,
    then raises StopIteration if called more times than supplied.
    """
    remaining = list(actions)

    async def _decide(context, history, iteration):
        if not remaining:
            return None
        return remaining.pop(0)

    return _decide


# ---------------------------------------------------------------------------
# diagnose terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diagnose_after_one_tool_call(agent, context):
    """
    Agent reads the crash site, then diagnoses. The validator
    accepts because the observation covers the crash line and
    `self.rag` appears in the crash statement.
    """
    agent._decide = _scripted_decide(
        InvestigatorAction(
            action="read_file",
            thought="Read the failing method.",
            args={"path": "incident_service.py"},
        ),
        InvestigatorAction(
            action="diagnose",
            thought="self.rag is assigned from get_rag_service(), which can return None.",
            args={
                "null_source": "self.rag",
                "evidence": "self.rag.search_similar_outcomes at the crash line",
                "confidence": 0.85,
            },
        ),
    )

    result = await agent.investigate(context)

    assert result.status == STATUS_DIAGNOSED
    assert result.null_source == "self.rag"
    assert result.confidence == 0.85
    assert result.iterations == 2
    assert len(result.history) == 1
    assert result.history[0]["tool"] == "read_file"
    assert result.history[0]["ok"] is True


@pytest.mark.asyncio
async def test_diagnose_after_five_tool_calls(agent, context):
    """
    Agent uses several iterations on tools, reads the crash site,
    then diagnoses. The diagnose is the terminal; the observation
    of the crash site grounds the diagnosis.
    """
    agent._decide = _scripted_decide(
        InvestigatorAction(action="search_codebase", thought="find rag",
                           args={"pattern": "get_rag_service"}),
        InvestigatorAction(action="read_symbol", thought="check self.rag",
                           args={"path": "incident_service.py",
                                 "symbol_name": "self.rag"}),
        InvestigatorAction(action="read_file", thought="read crash site",
                           args={"path": "incident_service.py"}),
        InvestigatorAction(action="read_symbol", thought="check def",
                           args={"path": "incident_service.py",
                                 "symbol_name": "get_rag_service"}),
        InvestigatorAction(
            action="diagnose",
            thought="Confirmed: self.rag can be None.",
            args={"null_source": "self.rag",
                  "evidence": "get_rag_service returns None on failure",
                  "confidence": 0.9},
        ),
    )

    result = await agent.investigate(context)

    assert result.status == STATUS_DIAGNOSED
    assert result.iterations == 5
    assert len(result.history) == 4


# ---------------------------------------------------------------------------
# refuse terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refuse_after_one_tool_call(agent, context):
    """
    Agent reads one file, then refuses. Result carries reason and
    candidates_considered.
    """
    agent._decide = _scripted_decide(
        InvestigatorAction(
            action="read_file",
            thought="Reading the failing line's file.",
            args={"path": "incident_service.py"},
        ),
        InvestigatorAction(
            action="refuse",
            thought="Cannot identify the null source from what I have.",
            args={
                "reason": "no_null_source_visible",
                "candidates_considered": ["self.rag",
                                          "return of search_similar_outcomes"],
            },
        ),
    )

    result = await agent.investigate(context)

    assert result.status == STATUS_REFUSED
    assert result.reason == "no_null_source_visible"
    assert result.candidates_considered == [
        "self.rag", "return of search_similar_outcomes"
    ]
    assert result.iterations == 2
    assert result.null_source is None


@pytest.mark.asyncio
async def test_refuse_with_empty_candidates(agent, context):
    """A refuse without candidates is valid; the list is just empty."""
    agent._decide = _scripted_decide(
        InvestigatorAction(
            action="refuse",
            thought="No idea.",
            args={"reason": "file_not_in_repo", "candidates_considered": []},
        ),
    )
    result = await agent.investigate(context)
    assert result.status == STATUS_REFUSED
    assert result.candidates_considered == []


# ---------------------------------------------------------------------------
# non-terminal loop outcomes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iteration_limit(agent, context):
    """
    Agent keeps calling tools and never diagnoses. Result is
    iteration_limit after max_iterations.
    """
    # Five tool calls, no terminal.
    agent._decide = _scripted_decide(*[
        InvestigatorAction(
            action="search_codebase",
            thought=f"search {i}",
            args={"pattern": f"needle{i}"},
        )
        for i in range(5)
    ])

    result = await agent.investigate(context, max_iterations=5)

    assert result.status == STATUS_ITERATION_LIMIT
    assert result.iterations == 5
    assert len(result.history) == 5


@pytest.mark.asyncio
async def test_timeout_after_first_slow_iteration(agent, context):
    """
    Time budget is exceeded while the first tool call runs. The
    second iteration's top-of-loop check stops the loop; the first
    iteration's observation is retained in history because it
    completed.

    The check runs at the loop boundary, not inside `_decide` — so
    the first call is never interrupted. That's the right behavior:
    cancelling an in-flight LLM call would leave no clean recovery
    path. The cost is one extra iteration's worth of work.
    """
    async def slow_decide(context, history, iteration):
        import asyncio
        await asyncio.sleep(0.1)
        return InvestigatorAction(
            action="search_codebase", thought="x", args={"pattern": "x"}
        )

    agent._decide = slow_decide
    result = await agent.investigate(
        context, max_iterations=5, time_budget_seconds=0.01
    )

    assert result.status == STATUS_TIMEOUT
    assert result.iterations == 1
    assert len(result.history) == 1
    assert result.history[0]["tool"] == "search_codebase"

@pytest.mark.asyncio
async def test_timeout_before_first_iteration(agent, context):
    """
    Time budget is already exhausted when investigate() is entered.
    The first iteration's top-of-loop check fires immediately, and
    zero iterations run.

    Constructed by monkeypatching time.monotonic so the first call
    reads as already past the budget, without actually sleeping.
    """
    import src.agents.investigator as inv_module

    call_count = {"n": 0}

    def fake_monotonic():
        call_count["n"] += 1
        # First call: the start time. Second call: the loop's first
        # check. Return values 100 seconds apart.
        return 1000.0 if call_count["n"] == 1 else 1100.0

    async def never_called(context, history, iteration):
        raise AssertionError("_decide should not have been called")

    agent._decide = never_called

    with patch.object(inv_module.time, "monotonic", fake_monotonic):
        result = await agent.investigate(
            context, max_iterations=5, time_budget_seconds=1.0
        )

    assert result.status == STATUS_TIMEOUT
    assert result.iterations == 0
    assert result.history == []

@pytest.mark.asyncio
async def test_decision_failed_on_unparseable_response(agent, context):
    """
    `_decide` returns None — the parser gave up. Loop stops with
    decision_failed.
    """
    agent._decide = _scripted_decide(None)
    result = await agent.investigate(context)
    assert result.status == STATUS_DECISION_FAILED
    assert result.iterations == 0


# ---------------------------------------------------------------------------
# parsing rules — thought cap and confidence fallback
# ---------------------------------------------------------------------------

def test_thought_is_truncated_to_200_chars(agent):
    """
    The prompt asks for short thoughts. The parser enforces.
    """
    long_thought = "x" * 500
    raw = (
        '{"thought": "' + long_thought + '", '
        '"next_step": "refuse", '
        '"parameters": {"reason": "too_long"}}'
    )
    action = agent._parse_action(raw)
    assert action is not None
    assert len(action.thought) == THOUGHT_MAX_CHARS
    assert action.thought == "x" * THOUGHT_MAX_CHARS


def test_diagnose_without_confidence_defaults_to_0_7(agent):
    raw = (
        '{"thought": "found it", '
        '"next_step": "diagnose", '
        '"parameters": {"null_source": "self.rag", "evidence": "e"}}'
    )
    action = agent._parse_action(raw)
    assert action is not None
    assert action.args["confidence"] == DEFAULT_CONFIDENCE


def test_diagnose_confidence_clamped(agent):
    raw = (
        '{"thought": "t", "next_step": "diagnose", '
        '"parameters": {"null_source": "x", "confidence": 5.0}}'
    )
    action = agent._parse_action(raw)
    assert action is not None
    assert action.args["confidence"] == 1.0


def test_diagnose_without_null_source_is_rejected(agent):
    raw = '{"thought": "t", "next_step": "diagnose", "parameters": {}}'
    assert agent._parse_action(raw) is None


def test_invalid_action_kind_is_rejected(agent):
    raw = '{"thought": "t", "next_step": "explode", "parameters": {}}'
    assert agent._parse_action(raw) is None


def test_args_must_be_a_dict(agent):
    raw = '{"thought": "t", "next_step": "read_file", "parameters": "foo.py"}'
    assert agent._parse_action(raw) is None


def test_refuse_candidates_coerced_to_string_list(agent):
    raw = (
        '{"thought": "t", "next_step": "refuse", '
        '"parameters": {"reason": "r", '
        '"candidates_considered": ["a", 42, null, "b"]}}'
    )
    action = agent._parse_action(raw)
    assert action is not None
    assert action.args["candidates_considered"] == ["a", "b"]


# ---------------------------------------------------------------------------
# tool error is an observation, not a crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_error_becomes_observation_and_loop_continues(agent, context):
    """
    A read_file on a missing path returns ok=False. The loop
    continues — the agent reaches the diagnose action. But the
    diagnosis has no evidence (the only observation failed), so the
    validator refuses with crash_line_not_observed.
    """
    agent._decide = _scripted_decide(
        InvestigatorAction(
            action="read_file",
            thought="Read a file that doesn't exist.",
            args={"path": "nonexistent.py"},
        ),
        InvestigatorAction(
            action="diagnose",
            thought="Diagnosing without evidence.",
            args={"null_source": "self.rag", "evidence": "from context"},
        ),
    )
    result = await agent.investigate(context)

    assert len(result.history) == 1
    assert result.history[0]["ok"] is False
    assert "not_a_file" in result.history[0]["error"]

    assert result.status == STATUS_REFUSED
    assert result.reason == REFUSAL_REASON_NOT_OBSERVED


# ---------------------------------------------------------------------------
# history ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_carries_tool_calls_in_order(agent, context):
    agent._decide = _scripted_decide(
        InvestigatorAction(action="search_codebase", thought="one",
                           args={"pattern": "get_rag_service"}),
        InvestigatorAction(action="read_symbol", thought="two",
                           args={"path": "incident_service.py",
                                 "symbol_name": "self.rag"}),
        InvestigatorAction(action="read_file", thought="three",
                           args={"path": "utils.py"}),
        InvestigatorAction(action="refuse", thought="done",
                           args={"reason": "test", "candidates_considered": []}),
    )
    result = await agent.investigate(context)

    assert result.status == STATUS_REFUSED
    tools = [obs["tool"] for obs in result.history]
    assert tools == ["search_codebase", "read_symbol", "read_file"]
    iterations = [obs["iteration"] for obs in result.history]
    assert iterations == [1, 2, 3]

@pytest.mark.asyncio
async def test_cleanup_repo_removes_path_under_base_dir():
    """A path under _base_dir() is ours to delete."""
    from src.agents.repo_clone import _base_dir, cleanup_repo

    target = _base_dir() / "inv-test-cleanup"
    target.mkdir(parents=True, exist_ok=True)
    (target / "file.txt").write_text("x")
    assert target.exists()

    cleanup_repo(str(target))

    assert not target.exists()
