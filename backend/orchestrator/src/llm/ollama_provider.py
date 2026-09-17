from typing import Optional
from loguru import logger
import httpx

from src.config import settings
from src.llm.base import LLMProvider, LLMResponse, LLMProviderError


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self):
        self._base_url = (settings.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
        self._model = settings.OLLAMA_MODEL or "llama3.1"

    def is_configured(self) -> bool:
        return bool(self._base_url)

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system

        # Ollama supports format: "json" for structured output. It does not
        # distinguish object vs array — both produce valid JSON. Map both
        # json_* values to "json".
        if response_format in ("json_object", "json_array"):
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            raise LLMProviderError(f"Ollama provider error: {e}") from e

        return LLMResponse(
            content=data.get("response", ""),
            provider=self.name,
            model=self._model,
            raw=data,
        )
