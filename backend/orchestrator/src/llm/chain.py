from typing import Iterable
from loguru import logger

from src.llm.base import LLMProvider, LLMResponse, LLMProviderError


class LLMChain:
    """
    Runs providers in order. Returns the first successful response.
    Raises LLMProviderError only if every provider in the chain fails.
    """

    def __init__(self, providers: Iterable[LLMProvider]):
        self._providers = [p for p in providers if p is not None]

    def __bool__(self) -> bool:
        return bool(self._providers)

    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse | None:
        errors = []
        for provider in self._providers:
            try:
                logger.info(f"🔄 Trying provider: {provider.name}")
                resp = await provider.complete(
                    prompt=prompt,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                logger.info(f"✅ Provider {provider.name} succeeded ({resp.model})")
                return resp
            except LLMProviderError as e:
                logger.warning(f"❌ Provider {provider.name} failed: {e}")
                errors.append(f"{provider.name}: {e}")
            except Exception as e:
                logger.exception(f"❌ Provider {provider.name} raised unexpectedly")
                errors.append(f"{provider.name}: {e}")

        logger.error(f"All providers failed: {errors}")
        return None
