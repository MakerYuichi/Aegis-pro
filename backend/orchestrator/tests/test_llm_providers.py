import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.llm.base import LLMResponse, LLMProviderError
from src.llm.mock_provider import MockProvider
from src.llm.chain import LLMChain


# ── MockProvider ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_provider_returns_canned_response():
    p = MockProvider(canned_response='{"severity": "P0"}')
    resp = await p.complete("analyze this")
    assert isinstance(resp, LLMResponse)
    assert resp.provider == "mock"
    assert resp.content == '{"severity": "P0"}'


@pytest.mark.asyncio
async def test_mock_provider_default_response_is_valid_json():
    p = MockProvider()
    resp = await p.complete("anything")
    parsed = json.loads(resp.content)
    for key in ("severity", "title", "root_cause", "suggested_fix", "confidence"):
        assert key in parsed


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
    chain = LLMChain([_FailingProvider(), _WorkingProvider()])
    resp = await chain.complete("hi")
    assert resp is not None
    assert resp.content == "ok"
    assert resp.provider == "working"


@pytest.mark.asyncio
async def test_chain_returns_none_if_all_fail():
    chain = LLMChain([_FailingProvider(), _FailingProvider()])
    resp = await chain.complete("hi")
    assert resp is None


def test_chain_exposes_provider_names():
    chain = LLMChain([_WorkingProvider(), _FailingProvider()])
    assert chain.provider_names() == ["working", "failing"]


# ── Provider internals (smoke tests) ─────────────────────────

@pytest.mark.asyncio
async def test_groq_provider_iterates_models_on_failure(monkeypatch):
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
        
# ── #21 regression: json_array shape ─────────────────────────
@pytest.mark.asyncio
async def test_mock_provider_returns_array_for_json_array_format():
    """Regression for #21: PR scoring expects a JSON array, not an object."""
    import json
    from src.llm.mock_provider import MockProvider

    p = MockProvider()
    resp = await p.complete("score these PRs", response_format="json_array")
    parsed = json.loads(resp.content)
    assert isinstance(parsed, list)
    assert len(parsed) > 0
    assert "number" in parsed[0]
    assert "score" in parsed[0]


@pytest.mark.asyncio
async def test_mock_provider_returns_object_by_default():
    """Default response_format is 'text' — object shape preserved for incidents."""
    import json
    from src.llm.mock_provider import MockProvider

    p = MockProvider()
    resp = await p.complete("analyze this incident")
    parsed = json.loads(resp.content)
    assert isinstance(parsed, dict)
    assert "severity" in parsed
