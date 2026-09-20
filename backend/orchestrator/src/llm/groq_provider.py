from typing import Optional
from loguru import logger
from groq import AsyncGroq

from src.config import settings
from src.llm.base import LLMProvider, LLMResponse, LLMProviderError


class GroqProvider(LLMProvider):
    """Groq provider with internal model-level fallback list."""

    name = "groq"

    DEFAULT_MODELS = [
        "groq/compound",
        "groq/compound-mini",
        "openai/gpt-oss-120b",
    ]

    def __init__(self):
        self._client: Optional[AsyncGroq] = None
        self._models = self.DEFAULT_MODELS

    def is_configured(self) -> bool:
        return bool(settings.GROQ_API_KEY)

    def _client_instance(self) -> AsyncGroq:
        if self._client is None:
            self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        return self._client

    @staticmethod
    def _native_response_format(response_format: str) -> Optional[dict]:
        """
        Map our cross-provider response_format to Groq's native format.

        Groq follows OpenAI's JSON mode: both objects and arrays must be
        requested as {"type": "json_object"}. The caller is responsible for
        knowing whether the content is an object or an array.
        """
        if response_format in ("json_object", "json_array"):
            return {"type": "json_object"}
        return None

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

        native_format = self._native_response_format(response_format)

        last_error: Optional[Exception] = None
        for model in self._models:
            try:
                logger.info(f"🔄 Groq trying model: {model}")
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if native_format:
                    kwargs["response_format"] = native_format

                resp = await self._client_instance().chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                return LLMResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
                )
            except Exception as e:
                logger.warning(f"❌ Groq model {model} failed: {e}")
                last_error = e
                continue

        raise LLMProviderError(f"All Groq models failed. Last error: {last_error}")
