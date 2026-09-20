import json
from unittest.mock import AsyncMock, patch

import pytest

from src.demo import risk_analyzer_llm as ra
from src.demo.risk_analyzer_llm import RiskFinding


_GOOD_FINDING = {
    "line_number": 87,
    "line_content": "response = client.get(url).json()",
    "title": "Unguarded JSON parse on upstream response",
    "root_cause": (
        "The response body is parsed without checking status_code or "
        "wrapping in try/except. A non-JSON 4xx/5xx body raises here."
    ),
    "suggested_fix": (
        "Check response.status_code before parsing, or wrap in try/except "
        "and handle the non-JSON case explicitly."
    ),
    "severity": "P1",
    "exception_type": "JSONDecodeError",
    "confidence": 0.83,
    "category": "serialization",
    "blast_radius_reason": (
        "Any caller that invokes this handler will receive a 500 during "
        "an upstream incident, compounding the outage."
    ),
    "related_lines": [86, 88],
}


def _mock_complete_raw(return_value):
    """Patch LLMService.complete_raw to return a fixed string."""
    return patch(
        "src.services.llm_service.LLMService.complete_raw",
        new=AsyncMock(return_value=return_value),
    )


def _mock_chain_present():
    """Patch LLMService so `chain` is truthy."""
    return patch(
        "src.services.llm_service.LLMService.__init__",
        return_value=None,
    )


@pytest.mark.asyncio
async def test_valid_finding_parses_correctly():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()  # truthy
        instance.complete_raw = AsyncMock(return_value=json.dumps(_GOOD_FINDING))

        result = await ra.analyze_file_with_llm(
            "src/handlers/upstream.py",
            "def handler(url):\n    response = client.get(url).json()\n",
            "Python",
        )
    assert isinstance(result, RiskFinding)
    assert result.line_number == 87
    assert result.line_content == "response = client.get(url).json()"
    assert result.severity == "P1"
    assert result.category == "serialization"
    assert result.related_lines == [86, 88]
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_no_chain_returns_none():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = None
        result = await ra.analyze_file_with_llm(
            "src/x.py", "pass\n", "Python"
        )
    assert result is None


@pytest.mark.asyncio
async def test_llm_exception_returns_none():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(side_effect=RuntimeError("boom"))
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_empty_content_returns_none():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value="")
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_no_json_in_output_returns_none():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value="No JSON here at all.")
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_malformed_json_returns_none():
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value='{"line_number": 87,')  # truncated
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_missing_required_key_returns_none():
    partial = dict(_GOOD_FINDING)
    del partial["suggested_fix"]
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value=json.dumps(partial))
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_invalid_severity_returns_none():
    bad = dict(_GOOD_FINDING, severity="URGENT")
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value=json.dumps(bad))
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_confidence_out_of_range_returns_none():
    bad = dict(_GOOD_FINDING, confidence=1.5)
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value=json.dumps(bad))
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is None


@pytest.mark.asyncio
async def test_unknown_category_downgrades_to_other():
    variant = dict(_GOOD_FINDING, category="flibbertigibbet")
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value=json.dumps(variant))
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is not None
    assert result.category == "other"


@pytest.mark.asyncio
async def test_json_wrapped_in_prose_is_extracted():
    """Providers sometimes wrap JSON in prose. We extract the first object."""
    wrapped = f"Here is the analysis:\n\n{json.dumps(_GOOD_FINDING)}\n\nHope that helps!"
    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(return_value=wrapped)
        result = await ra.analyze_file_with_llm("src/x.py", "pass\n", "Python")
    assert result is not None
    assert result.line_number == 87


@pytest.mark.asyncio
async def test_long_file_is_truncated_in_prompt():
    """A 2000-line file gets truncated to 500 with a note."""
    long_file = "\n".join(f"line {i}" for i in range(2000))
    captured = {}

    async def fake_complete(prompt, system=None, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(_GOOD_FINDING)

    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(side_effect=fake_complete)
        await ra.analyze_file_with_llm("src/x.py", long_file, "Python")

    assert "truncated at line 500 of 2000" in captured["prompt"]


@pytest.mark.asyncio
async def test_short_file_not_truncated():
    short = "\n".join(f"line {i}" for i in range(100))
    captured = {}

    async def fake_complete(prompt, system=None, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(_GOOD_FINDING)

    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(side_effect=fake_complete)
        await ra.analyze_file_with_llm("src/x.py", short, "Python")

    assert "truncated" not in captured["prompt"]


@pytest.mark.asyncio
async def test_prompt_contains_line_numbers():
    file_content = "def a():\n    pass\n\ndef b():\n    return 1\n"
    captured = {}

    async def fake_complete(prompt, system=None, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(_GOOD_FINDING)

    with patch("src.demo.risk_analyzer_llm.LLMService") as MockLLM:
        instance = MockLLM.return_value
        instance.chain = object()
        instance.complete_raw = AsyncMock(side_effect=fake_complete)
        await ra.analyze_file_with_llm("src/x.py", file_content, "Python")

    prompt = captured["prompt"]
    # Every line of the source appears with its number somewhere in the prompt.
    assert "def a():" in prompt
    assert "def b():" in prompt
    # Line 1 shows up before line 5
    assert prompt.index("def a():") < prompt.index("def b():")
    # The source is inside a "Source (line-numbered):" section
    assert "Source (line-numbered):" in prompt


@pytest.mark.asyncio
async def test_public_entry_delegates_to_llm():
    """The public analyze_file wrapper calls the LLM path."""
    with patch(
        "src.demo.risk_analyzer.analyze_file_with_llm",
        new=AsyncMock(return_value=None),
    ) as mock_llm:
        from src.demo.risk_analyzer import analyze_file
        result = await analyze_file("src/x.py", "pass\n", "Python")
    assert result is None
    mock_llm.assert_awaited_once()
