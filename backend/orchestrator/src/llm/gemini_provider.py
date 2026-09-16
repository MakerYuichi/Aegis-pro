from typing import Optional
from loguru import logger

from src.config import settings
from src.llm.base import LLMProvider, LLMResponse, LLMProviderError

try:
    import google.generativeai as genai
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False


class GeminiProvider(LLMProvider):
    name = "gemini"

    DEFAULT_MODEL = "models/gemini-3.5-flash-lite"

    def __init__(self):
        self._model = None
        self._model_name = self.DEFAULT_MODEL

    def is_configured(self) -> bool:
        return bool(settings.GOOGLE_API_KEY) and _GEMINI_AVAILABLE

    def _model_instance(self):
        if self._model is None:
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            self._model = genai.GenerativeModel(self._model_name)
        return self._model

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        if not _GEMINI_AVAILABLE:
            raise LLMProviderError("google-generativeai SDK not installed")

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        try:
            # The genai SDK is synchronous; wrap it to keep the async contract.
            import asyncio
            resp = await asyncio.to_thread(
                self._model_instance().generate_content,
                full_prompt,
            )
            content = getattr(resp, "text", "") or ""
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            raise LLMProviderError(f"Gemini provider error: {e}") from e

        return LLMResponse(
            content=content,
            provider=self.name,
            model=self._model_name,
        )
