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

    # Incident analysis: single JSON object
    DEFAULT_OBJECT_RESPONSE = (
        '{"severity": "P2", '
        '"title": "Mock incident", '
        '"root_cause": "NullPointerException at PaymentProcessor.java:442", '
        '"suggested_fix": "Add a null guard before accessing upiResponse", '
        '"rollback_command": "kubectl rollout undo deploy/payment-api -n production", '
        '"confidence": 0.85}'
    )

    # PR scoring: JSON array of scored candidates
    DEFAULT_ARRAY_RESPONSE = (
        '[{"number": 42, "score": 0.91, "reason": "modified exact line"}, '
        '{"number": 43, "score": 0.45, "reason": "unrelated"}]'
    )

    # Backwards-compat alias — existing tests reference DEFAULT_RESPONSE
    DEFAULT_RESPONSE = DEFAULT_OBJECT_RESPONSE

    def __init__(
        self,
        canned_response: Optional[str] = None,
        canned_array_response: Optional[str] = None,
    ):
        self._canned_object = canned_response or self.DEFAULT_OBJECT_RESPONSE
        self._canned_array = canned_array_response or self.DEFAULT_ARRAY_RESPONSE

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        if response_format == "json_array":
            content = self._canned_array
        else:
            # "text" and "json_object" both return the object shape.
            # If a caller wants text, this canned object is still valid text.
            content = self._canned_object

        return LLMResponse(
            content=content,
            provider=self.name,
            model="mock-model",
        )
