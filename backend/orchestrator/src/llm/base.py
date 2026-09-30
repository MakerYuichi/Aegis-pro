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
    content: str
    provider: str
    model: str
    raw: Optional[dict] = None
    # Provider-reported reason the generation stopped. Normalized
    # across providers to a small set: "stop" (natural end),
    # "length" (token limit hit), "content_filter", "tool_calls",
    # or None when the provider doesn't report it.
    #
    # This field exists because "the diff looked truncated" is an
    # inference from the shape of the output; finish_reason is the
    # provider telling you directly. See the fix-pipeline debugging
    # for why that distinction matters — six rounds of "corrupt
    # patch" errors looked identical whether the cause was a
    # malformed diff or a truncated one.
    finish_reason: Optional[str] = None


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
