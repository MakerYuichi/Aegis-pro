"""
Tests for LLM providers, chain, and factory.

Covers:
  - MockProvider: canned responses, default responses, format handling
  - LLMChain: fallback behavior, provider selection, error handling
  - Factory: provider loading, chain building, configuration
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.llm.base import LLMResponse, LLMProviderError
from src.llm.mock_provider import MockProvider
from src.llm.chain import LLMChain


# ── MockProvider ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_provider_returns_canned_response():
    """
    Situation: MockProvider with canned response.
    Expected: Returns canned response.
    Function: src.llm.mock_provider.MockProvider.complete
    """
    p = MockProvider(canned_response='{"severity": "P0"}')
    resp = await p.complete("analyze this")
    assert isinstance(resp, LLMResponse)
    assert resp.provider == "mock"
    assert resp.content == '{"severity": "P0"}'


@pytest.mark.asyncio
async def test_mock_provider_default_response_is_valid_json():
    """
    Situation: MockProvider without canned response.
    Expected: Returns default incident analysis JSON.
    Function: src.llm.mock_provider.MockProvider.complete
    """
    p = MockProvider()
    resp = await p.complete("anything")
    parsed = json.loads(resp.content)
    for key in ("severity", "title", "root_cause", "suggested_fix", "confidence"):
        assert key in parsed


@pytest.mark.asyncio
async def test_mock_provider_is_configured():
    """
    Situation: Check if MockProvider is configured.
    Expected: Always returns True.
    Function: src.llm.mock_provider.MockProvider.is_configured
    """
    p = MockProvider()
    assert p.is_configured() is True


# ── LLMChain ─────────────────────────────────────────────────

class _FailingProvider:
    name = "failing"
    def is_configured(self) -> bool: return True
    async def complete(self, **kwargs):
        raise LLMProviderError("simulated failure")


class _WorkingProvider:
    name = "working"
    def is_configured(self) -> bool: return True
    async def complete(self, **kwargs):
        return LLMResponse(content="ok", provider="working", model="w-1")


@pytest.mark.asyncio
async def test_chain_falls_through_to_second_provider():
    """
    Situation: First provider fails, second succeeds.
    Expected: Returns response from second provider.
    Function: src.llm.chain.LLMChain.complete
    """
    chain = LLMChain([_FailingProvider(), _WorkingProvider()])
    resp = await chain.complete("hi")
    assert resp is not None
    assert resp.content == "ok"
    assert resp.provider == "working"


@pytest.mark.asyncio
async def test_chain_returns_none_if_all_fail():
    """
    Situation: All providers fail.
    Expected: Returns None.
    Function: src.llm.chain.LLMChain.complete
    """
    chain = LLMChain([_FailingProvider(), _FailingProvider()])
    resp = await chain.complete("hi")
    assert resp is None


def test_chain_exposes_provider_names():
    """
    Situation: Chain with multiple providers.
    Expected: Returns list of provider names.
    Function: src.llm.chain.LLMChain.provider_names
    """
    chain = LLMChain([_WorkingProvider(), _FailingProvider()])
    assert chain.provider_names() == ["working", "failing"]


def test_chain_bool_true_with_providers():
    """
    Situation: Chain with providers.
    Expected: Evaluates to True.
    Function: src.llm.chain.LLMChain.__bool__
    """
    chain = LLMChain([_WorkingProvider()])
    assert bool(chain) is True


def test_chain_bool_false_without_providers():
    """
    Situation: Chain with no providers.
    Expected: Evaluates to False.
    Function: src.llm.chain.LLMChain.__bool__
    """
    chain = LLMChain([])
    assert bool(chain) is False


@pytest.mark.asyncio
async def test_chain_filters_none_providers():
    """
    Situation: Chain initialized with None values.
    Expected: Filters out None values.
    Function: src.llm.chain.LLMChain.__init__
    """
    chain = LLMChain([None, _WorkingProvider(), None])
    assert len(chain._providers) == 1
    assert chain._providers[0].name == "working"


@pytest.mark.asyncio
async def test_chain_passes_parameters_to_provider():
    """
    Situation: Chain called with custom parameters.
    Expected: Passes prompt, system, temperature, max_tokens, response_format to provider.
    Function: src.llm.chain.LLMChain.complete
    """
    class ParamTrackingProvider:
        name = "tracker"
        def is_configured(self) -> bool: return True
        def __init__(self):
            self.received_kwargs = {}
        async def complete(self, prompt, system=None, temperature=0.2, max_tokens=2048, response_format="text", **kwargs):
            self.received_kwargs = {
                "prompt": prompt,
                "system": system,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
                "kwargs": kwargs
            }
            return LLMResponse(content="ok", provider="tracker", model="t-1")
    
    provider = ParamTrackingProvider()
    chain = LLMChain([provider])
    resp = await chain.complete("hi", temperature=0.5, max_tokens=1000)
    
    assert provider.received_kwargs["temperature"] == 0.5
    assert provider.received_kwargs["max_tokens"] == 1000
    assert provider.received_kwargs["prompt"] == "hi"


# ── Provider internals (smoke tests) ─────────────────────────

@pytest.mark.asyncio
async def test_groq_provider_iterates_models_on_failure(monkeypatch):
    """
    Situation: Groq provider with model iteration.
    Expected: Falls through to second model on failure.
    Function: src.llm.groq_provider.GroqProvider.complete
    """
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    import importlib
    from src import config
    importlib.reload(config)

    from src.llm import groq_provider as gp
    importlib.reload(gp)

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "groq-ok"
    mock_resp.model_dump = lambda: {"id": "x"}

    with patch.object(gp, "AsyncGroq") as MockGroq:
        instance = MockGroq.return_value
        # First call fails, second succeeds
        instance.chat.completions.create = AsyncMock(
            side_effect=[Exception("model A down"), mock_resp]
        )
        p = gp.GroqProvider()
        resp = await p.complete("hi")
        assert resp.content == "groq-ok"
        assert instance.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_ollama_provider_posts_to_generate_endpoint(monkeypatch):
    """
    Situation: Ollama provider called.
    Expected: Posts to generate endpoint.
    Function: src.llm.ollama_provider.OllamaProvider.complete
    """
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    import importlib
    from src import config
    importlib.reload(config)

    from src.llm import ollama_provider as op
    importlib.reload(op)

    with patch("httpx.AsyncClient") as MockClient:
        mock_post = AsyncMock()
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json = lambda: {"response": "ollama-ok", "model": "llama3.1"}
        MockClient.return_value.__aenter__.return_value.post = mock_post

        p = op.OllamaProvider()
        resp = await p.complete("hi")
        assert resp.content == "ollama-ok"
        assert mock_post.call_args[0][0].endswith("/api/generate")


# ── Response format handling ─────────────────────────────────

@pytest.mark.asyncio
async def test_mock_provider_returns_array_for_json_array_format():
    """
    Situation: Request with json_array format.
    Expected: Returns JSON array.
    Function: src.llm.mock_provider.MockProvider.complete
    """
    p = MockProvider()
    resp = await p.complete("score these PRs", response_format="json_array")
    parsed = json.loads(resp.content)
    assert isinstance(parsed, list)
    assert len(parsed) > 0
    assert "number" in parsed[0]
    assert "score" in parsed[0]


@pytest.mark.asyncio
async def test_mock_provider_returns_object_by_default():
    """
    Situation: Default response_format (text).
    Expected: Returns JSON object for incidents.
    Function: src.llm.mock_provider.MockProvider.complete
    """
    p = MockProvider()
    resp = await p.complete("analyze this incident")
    parsed = json.loads(resp.content)
    assert isinstance(parsed, dict)
    assert "severity" in parsed


@pytest.mark.asyncio
async def test_mock_provider_respects_json_object_format():
    """
    Situation: Request with json_object format.
    Expected: Returns JSON object.
    Function: src.llm.mock_provider.MockProvider.complete
    """
    p = MockProvider()
    resp = await p.complete("analyze", response_format="json_object")
    parsed = json.loads(resp.content)
    assert isinstance(parsed, dict)
