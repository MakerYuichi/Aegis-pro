from typing import Optional
from loguru import logger
from openai import AsyncAzureOpenAI

from src.config import settings
from src.llm.base import LLMProvider, LLMResponse, LLMProviderError


class AzureOpenAIProvider(LLMProvider):
    name = "azure"

    def __init__(self):
        self._client: Optional[AsyncAzureOpenAI] = None
        self._deployment = settings.AZURE_OPENAI_DEPLOYMENT or ""

    def is_configured(self) -> bool:
        return all([
            settings.AZURE_OPENAI_API_KEY,
            settings.AZURE_OPENAI_ENDPOINT,
            settings.AZURE_OPENAI_DEPLOYMENT,
        ])

    def _client_instance(self) -> AsyncAzureOpenAI:
        if self._client is None:
            self._client = AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=settings.AZURE_OPENAI_API_VERSION or "2024-10-21",
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = await self._client_instance().chat.completions.create(
                model=self._deployment,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}")
            raise LLMProviderError(f"Azure provider error: {e}") from e

        return LLMResponse(
            content=resp.choices[0].message.content or "",
            provider=self.name,
            model=self._deployment,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )
