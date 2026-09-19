from typing import Optional
from loguru import logger
import httpx

from src.config import settings
from src.llm.base import LLMProvider, LLMResponse, LLMProviderError


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider with internal model-level fallback list."""

    name = "openrouter"

    DEFAULT_FALLBACKS = [
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "cohere/north-mini-code:free",
        "z-ai/glm-5.2:free",
    ]

    def __init__(self):
        self._primary = settings.OPENROUTER_MODEL or "google/gemma-4-31b-it:free"
        self._models = [self._primary] + self.DEFAULT_FALLBACKS

    def is_configured(self) -> bool:
        return bool(settings.OPENROUTER_API_KEY)

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "AEGIS PRO",
        }

        # Note: response_format is accepted for interface parity but not
        # forwarded to OpenRouter. Support varies by underlying model, and
        # sending it unconditionally can produce 400s on models that don't
        # support native JSON mode. The caller parses JSON from text.
        # If a specific model is known to support it, add it to an allowlist.

        last_error: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model in self._models:
                try:
                    logger.info(f"🔄 OpenRouter trying model: {model}")
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    if resp.status_code != 200:
                        last_error = Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                        logger.warning(f"❌ OpenRouter model {model} failed: {last_error}")
                        continue
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return LLMResponse(
                        content=content,
                        provider=self.name,
                        model=model,
                        raw=data,
                    )
                except Exception as e:
                    logger.warning(f"❌ OpenRouter model {model} error: {e}")
                    last_error = e
                    continue

        raise LLMProviderError(f"All OpenRouter models failed. Last error: {last_error}")
