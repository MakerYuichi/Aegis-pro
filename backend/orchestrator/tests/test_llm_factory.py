"""
Tests for src/llm/factory.py.

Covers:
  - _load: provider loading, unknown provider error
  - get_provider: single provider loading with defaults
  - get_provider_chain: chain building from settings, fallback handling
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.llm.base import LLMProvider, LLMProviderError
from src.llm.chain import LLMChain
from src.llm.factory import _load, get_provider, get_provider_chain


class _TestProvider:
    name = "test"
    def is_configured(self) -> bool: return True
    async def complete(self, **kwargs):
        from src.llm.base import LLMResponse
        return LLMResponse(content="test", provider="test", model="t-1")


class _UnconfiguredProvider:
    name = "unconfigured"
    def is_configured(self) -> bool: return False
    async def complete(self, **kwargs):
        from src.llm.base import LLMResponse
        return LLMResponse(content="test", provider="unconfigured", model="u-1")


# ---------------------------------------------------------------------------
# _load
# ---------------------------------------------------------------------------

def test_load_known_provider():
    """
    Situation: Load known provider (mock).
    Expected: Returns provider instance.
    Function: src.llm.factory._load
    """
    provider = _load("mock")
    assert provider.name == "mock"
    assert provider.is_configured() is True


def test_load_unknown_provider():
    """
    Situation: Load unknown provider name.
    Expected: Raises LLMProviderError.
    Function: src.llm.factory._load
    """
    with pytest.raises(LLMProviderError, match="Unknown LLM provider"):
        _load("nonexistent")


def test_load_case_insensitive():
    """
    Situation: Load provider with mixed case.
    Expected: Normalizes to lowercase.
    Function: src.llm.factory._load
    """
    provider = _load("Mock")
    assert provider.name == "mock"


def test_load_whitespace_trimmed():
    """
    Situation: Load provider with whitespace.
    Expected: Trims whitespace.
    Function: src.llm.factory._load
    """
    provider = _load("  mock  ")
    assert provider.name == "mock"


def test_load_unconfigured_provider():
    """
    Situation: Provider exists but is_configured() returns False.
    Expected: Raises LLMProviderError.
    Function: src.llm.factory._load
    """
    with patch("src.llm.factory._REGISTRY", {"test": ("tests.test_llm_factory", "_UnconfiguredProvider")}):
        with pytest.raises(LLMProviderError, match="not configured"):
            _load("test")


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------

def test_get_provider_with_name():
    """
    Situation: Request specific provider by name.
    Expected: Returns that provider.
    Function: src.llm.factory.get_provider
    """
    provider = get_provider("mock")
    assert provider.name == "mock"


def test_get_provider_default():
    """
    Situation: No name specified, no LLM_PROVIDER set.
    Expected: Returns default (groq).
    Function: src.llm.factory.get_provider
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = None
        provider = get_provider()
        assert provider.name == "groq"


def test_get_provider_from_settings():
    """
    Situation: LLM_PROVIDER set in settings.
    Expected: Returns configured provider.
    Function: src.llm.factory.get_provider
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        provider = get_provider()
        assert provider.name == "mock"


# ---------------------------------------------------------------------------
# get_provider_chain
# ---------------------------------------------------------------------------

def test_get_provider_chain_primary_only():
    """
    Situation: Only primary provider configured.
    Expected: Returns chain with single provider.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = ""
        
        chain = get_provider_chain()
        
        assert isinstance(chain, LLMChain)
        assert chain.provider_names() == ["mock"]


def test_get_provider_chain_with_fallbacks():
    """
    Situation: Primary + fallbacks configured.
    Expected: Returns chain with all providers.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = "mock,mock"
        
        chain = get_provider_chain()
        
        # Deduplicates primary
        assert chain.provider_names() == ["mock"]


def test_get_provider_chain_skips_unconfigured():
    """
    Situation: Some providers unconfigured.
    Expected: Skips unconfigured, uses configured.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = "groq,gemini"
        
        # If groq/gemini are unconfigured, they should be skipped
        chain = get_provider_chain()
        
        assert "mock" in chain.provider_names()


def test_get_provider_chain_no_providers_raises():
    """
    Situation: No providers configured.
    Expected: Raises LLMProviderError.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "groq"
        settings.LLM_FALLBACKS = ""
        
        # Mock the load to fail for groq
        with patch("src.llm.factory._load", side_effect=LLMProviderError("not configured")):
            with pytest.raises(LLMProviderError, match="No LLM providers"):
                get_provider_chain()


def test_get_provider_chain_deduplicates_fallbacks():
    """
    Situation: Fallback list includes primary.
    Expected: Deduplicates primary in chain.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = "mock,gemini"
        
        chain = get_provider_chain()
        
        # mock should appear only once
        assert chain.provider_names().count("mock") == 1


def test_get_provider_chain_whitespace_in_fallbacks():
    """
    Situation: Fallback list has whitespace.
    Expected: Trims whitespace from provider names.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = "  mock  ,  gemini  "
        
        chain = get_provider_chain()
        
        # Should still work after trimming
        assert "mock" in chain.provider_names()


def test_get_provider_chain_empty_fallbacks():
    """
    Situation: Fallbacks is empty string.
    Expected: Uses only primary.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = ""
        
        chain = get_provider_chain()
        
        assert chain.provider_names() == ["mock"]


def test_get_provider_chain_comma_only_fallbacks():
    """
    Situation: Fallbacks is just commas.
    Expected: Uses only primary.
    Function: src.llm.factory.get_provider_chain
    """
    with patch("src.llm.factory.settings") as settings:
        settings.LLM_PROVIDER = "mock"
        settings.LLM_FALLBACKS = ",,,"
        
        chain = get_provider_chain()
        
        assert chain.provider_names() == ["mock"]
