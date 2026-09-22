"""
Tests for GitHubService LLM integration.

Verifies that GitHubService uses the LLM chain abstraction rather than
direct provider clients.
"""
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
    Situation: GitHubService scores PR candidates.
    Expected: Uses LLM chain abstraction, not direct provider clients.
    Function: src.services.github_service.GitHubService._score_candidates_with_llm_service
    """
    monkeypatch.setenv("GITHUB_TOKEN", "")  # Avoid real GitHub calls

    from src.services import github_service as gs_mod
    from src.services.llm_service import LLMService

    # Fake LLMService with a chain that returns a valid scoring array
    class FakeLLMService(LLMService):
        def __init__(self):
            canned = (
                '[{"number": 42, "score": 0.91, "reason": "modified exact line"},'
                '{"number": 43, "score": 0.45, "reason": "unrelated"}]'
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
