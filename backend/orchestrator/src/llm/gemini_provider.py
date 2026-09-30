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
        response_format: str = "text",
    ) -> LLMResponse:
        if not _GEMINI_AVAILABLE:
            raise LLMProviderError("google-generativeai SDK not installed")

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        # Note: response_format is accepted for interface parity but not
        # forwarded to the Gemini SDK today. The caller is responsible for
        # parsing JSON out of the text response. See issue #22 (SDK migration)
        # for a path that adds native structured-output support.

        try:
            # The genai SDK is synchronous; wrap it to keep the async contract.
            import asyncio
            resp = await asyncio.to_thread(
                self._model_instance().generate_content,
                full_prompt,
            )
            content = getattr(resp, "text", "") or ""
            finish_reason = _normalize_gemini_finish_reason(resp)
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            raise LLMProviderError(f"Gemini provider error: {e}") from e

        return LLMResponse(
            content=content,
            provider=self.name,
            model=self._model_name,
            finish_reason=finish_reason,
        )

def _normalize_gemini_finish_reason(resp) -> Optional[str]:
    """
    Map Gemini's finish_reason enum to the same vocabulary the
    OpenAI-compatible providers use.

    Gemini returns a protos.Candidate.FinishReason enum whose names
    are STOP, MAX_TOKENS, SAFETY, RECITATION, OTHER. The caller
    (LLMService.complete_raw and its consumers) should be able to
    check finish_reason == "length" uniformly across providers,
    so we translate here.

    Returns None if the response has no candidates or the enum
    isn't readable — some SDK shapes are inconsistent.
    """
    try:
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            return None
        raw_reason = getattr(candidates[0], "finish_reason", None)
        if raw_reason is None:
            return None
        # Enum values have a .name attribute; sometimes it's already
        # a string on some SDK versions.
        name = getattr(raw_reason, "name", None) or str(raw_reason)
        return {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop",
        }.get(name, name.lower())
    except Exception:
        return None
