from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Normalized response across all providers."""
    content: str
    provider: str
    model: str
    raw: Optional[dict] = None


class LLMProviderError(Exception):
    """Raised when a provider fails. Callers catch this, not SDK-specific errors."""


class LLMProvider(ABC):
    """Contract every LLM provider must fulfill."""

    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        """
        Send a prompt, return a normalized response.

        response_format:
            "text"        — free-form text (default)
            "json_object" — caller expects a single JSON object
            "json_array"  — caller expects a JSON array

        Providers that support native JSON mode (Groq, OpenAI, Azure)
        may honor this parameter. Providers that don't (Ollama, Gemini)
        should ignore it — the caller is still responsible for parsing.

        May raise LLMProviderError. Callers that want fallback behavior
        should use `LLMChain` (see chain.py) instead of calling this directly.
        """
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required credentials/config are present."""
        ...
