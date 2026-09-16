import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.llm.base import LLMResponse, LLMProviderError
from src.llm.chain import LLMChain


class _StubProvider:
    name = "stub"
    def is_configured(self) -> bool: return True
    def __init__(self, content: str):
        self._content = content
    async def complete(self, **kwargs) -> LLMResponse:
        return LLMResponse(content=self._content, provider="stub", model="s-1")


@pytest.mark.asyncio
async def test_github_service_uses_llm_chain_for_pr_scoring(monkeypatch):
    """
    Regression test: GitHubService must not reach into LLMService.client,
    .gemini_client, .openrouter_api_key, or .models. It must go through
    the LLMService.complete_raw() abstraction.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "")  # Avoid real GitHub calls

    from src.services import github_service as gs_mod
    from src.services.llm_service import LLMService

    # Fake LLMService with a chain that returns a valid scoring array
    class FakeLLMService(LLMService):
        def __init__(self):
            canned = (
                '[{"number": 42, "score": 0.91, "reason": "modified exact line"},'
                ' {"number": 43, "score": 0.45, "reason": "unrelated"}]'
            )
            self.chain = LLMChain([_StubProvider(canned)])

    with patch.object(gs_mod, "LLMService", FakeLLMService):
        service = gs_mod.GitHubService()
        candidates = [
            {"number": 42, "title": "fix null check", "files": ["a.py"], "author": "x"},
            {"number": 43, "title": "docs", "files": ["b.md"], "author": "y"},
        ]
        scored = await service._score_candidates_with_llm_service(
            candidates, "a.py", 10
        )
        assert len(scored) == 2
        assert scored[0]["number"] == 42
        assert scored[0]["relevance_score"] == 0.91
