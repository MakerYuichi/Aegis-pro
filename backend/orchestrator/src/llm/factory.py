from loguru import logger

from src.config import settings
from src.llm.base import LLMProvider, LLMProviderError
from src.llm.chain import LLMChain


_REGISTRY = {
    "groq": ("src.llm.groq_provider", "GroqProvider"),
    "gemini": ("src.llm.gemini_provider", "GeminiProvider"),
    "openrouter": ("src.llm.openrouter_provider", "OpenRouterProvider"),
    "ollama": ("src.llm.ollama_provider", "OllamaProvider"),
    "azure": ("src.llm.azure_provider", "AzureOpenAIProvider"),
    "mock": ("src.llm.mock_provider", "MockProvider"),
}


def _load(name: str) -> LLMProvider:
    name = name.strip().lower()
    if name not in _REGISTRY:
        raise LLMProviderError(f"Unknown LLM provider: '{name}'. Known: {list(_REGISTRY)}")

    module_path, class_name = _REGISTRY[name]
    import importlib
    module = importlib.import_module(module_path)
    provider_cls = getattr(module, class_name)
    provider = provider_cls()

    if not provider.is_configured():
        raise LLMProviderError(
            f"Provider '{name}' is not configured. Check your .env for required keys."
        )
    return provider


def get_provider(name: str | None = None) -> LLMProvider:
    """Return a single provider by name (or the configured primary)."""
    return _load(name or settings.LLM_PROVIDER or "groq")


def get_provider_chain() -> LLMChain:
    """
    Build the fallback chain from settings:

      LLM_PROVIDER  — primary provider
      LLM_FALLBACKS — comma-separated list tried in order if primary fails

    Unconfigured providers are skipped silently.
    """
    primary_name = (settings.LLM_PROVIDER or "groq").strip().lower()
    fallback_names = [
        n.strip().lower()
        for n in (settings.LLM_FALLBACKS or "").split(",")
        if n.strip()
    ]

    ordered = [primary_name] + [n for n in fallback_names if n != primary_name]

    providers: list[LLMProvider] = []
    for name in ordered:
        try:
            providers.append(_load(name))
            logger.info(f"✅ LLM provider available: {name}")
        except LLMProviderError as e:
            logger.warning(f"⚠️ Skipping provider '{name}': {e}")

    if not providers:
        raise LLMProviderError(
            "No LLM providers are configured. "
            "Set at least one of GROQ_API_KEY, GOOGLE_API_KEY, "
            "OPENROUTER_API_KEY, or LLM_PROVIDER=mock for DEMO_MODE."
        )

    logger.info(f"🧠 LLM chain ready: {' → '.join(p.name for p in providers)}")
    return LLMChain(providers)
