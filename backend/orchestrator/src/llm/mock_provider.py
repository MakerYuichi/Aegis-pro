from typing import Optional
from src.llm.base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    """
    Deterministic provider for tests, CI, and DEMO_MODE.

    Unlike LLMService._intelligent_mock (which is the runtime last-resort
    fallback when every real provider fails), this provider never touches
    the network and always returns a valid response. Use it when you need
    reproducibility, not realism.
    """

    name = "mock"

    DEFAULT_RESPONSE = (
        '{"severity": "P2", '
        '"title": "Mock incident", '
        '"root_cause": "NullPointerException at PaymentProcessor.java:442", '
        '"suggested_fix": "Add a null guard before accessing upiResponse", '
        '"rollback_command": "kubectl rollout undo deploy/payment-api -n production", '
        '"confidence": 0.85}'
    )

    def __init__(self, canned_response: Optional[str] = None):
        self._canned = canned_response or self.DEFAULT_RESPONSE

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        return LLMResponse(
            content=self._canned,
            provider=self.name,
            model="mock-model",
        )
