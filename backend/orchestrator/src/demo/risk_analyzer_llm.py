from dataclasses import dataclass, field
from typing import Literal, Optional

from loguru import logger

from src.services.llm_service import LLMService


# How many lines of the file to send. Files longer than this are
# truncated with a note. 500 lines covers most handlers, controllers,
# and service modules; the ones that exceed it are usually generated.
_MAX_LINES = 500

_CATEGORIES = {
    "null_access",
    "timeout",
    "race_condition",
    "resource_leak",
    "auth",
    "serialization",
    "validation",
    "configuration",
    "other",
}


@dataclass(frozen=True)
class RiskFinding:
    line_number: int
    line_content: str
    title: str
    root_cause: str
    suggested_fix: str
    severity: Literal["P0", "P1", "P2"]
    exception_type: str
    confidence: float
    category: str
    blast_radius_reason: str
    related_lines: list[int] = field(default_factory=list)


_SYSTEM_PROMPT = """You are a senior site reliability engineer reviewing a \
source file for production risks. Your job is to identify the SINGLE most \
likely production failure in this file.

Be specific. Reference the actual code on the line. Do not invent imports, \
calls, or variables that do not appear in the file. If the file looks \
healthy, pick the highest-risk line anyway and explain why it is the most \
fragile — this is a demo of incident detection, not a code review.

Return ONLY valid JSON with exactly these keys:
{
  "line_number": <int>,
  "line_content": "<verbatim line from the file>",
  "title": "<one-line description, max 100 chars>",
  "root_cause": "<2-3 sentences explaining why this line will fail>",
  "suggested_fix": "<1-2 sentences describing the fix>",
  "severity": "P0" | "P1" | "P2",
  "exception_type": "<language-appropriate exception class>",
  "confidence": <float 0.0-1.0>,
  "category": "null_access" | "timeout" | "race_condition" |
              "resource_leak" | "auth" | "serialization" |
              "validation" | "configuration" | "other",
  "blast_radius_reason": "<1 sentence on what else would break>",
  "related_lines": [<int>, ...]
}
"""


def _build_user_prompt(
    file_path: str,
    file_content: str,
    language: str,
    repo_context: Optional[dict] = None,
) -> str:
    lines = file_content.split("\n")
    truncated = len(lines) > _MAX_LINES
    excerpt = "\n".join(lines[:_MAX_LINES])
    if truncated:
        excerpt += f"\n\n... [file truncated at line {_MAX_LINES} of {len(lines)}]"

    header = f"File: {file_path}\nLanguage: {language}\n"
    if repo_context:
        repo_name = repo_context.get("full_name")
        if repo_name:
            header += f"Repository: {repo_name}\n"
        primary_lang = repo_context.get("language")
        if primary_lang and primary_lang != language:
            header += f"Repo primary language: {primary_lang}\n"

    # Line numbers make it easier for the LLM to reference the right line.
    numbered = "\n".join(
        f"{i + 1:4d}  {line}" for i, line in enumerate(excerpt.split("\n"))
    )

    return f"""{header}
Source (line-numbered):

{numbered}

Identify the single most likely production failure in this file.
"""


def _validate(raw: dict) -> RiskFinding:
    """
    Validate the LLM's JSON. Raises ValueError on anything malformed so
    the caller can fall back or surface an error.
    """
    required = {
        "line_number", "line_content", "title", "root_cause",
        "suggested_fix", "severity", "exception_type", "confidence",
        "category", "blast_radius_reason",
    }
    missing = required - set(raw.keys())
    if missing:
        raise ValueError(f"LLM output missing keys: {missing}")

    line_number = int(raw["line_number"])
    if line_number < 1:
        raise ValueError(f"line_number must be >= 1, got {line_number}")

    severity = str(raw["severity"]).upper()
    if severity not in ("P0", "P1", "P2"):
        raise ValueError(f"invalid severity: {raw['severity']}")

    confidence = float(raw["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence out of range: {confidence}")

    category = str(raw["category"]).lower()
    if category not in _CATEGORIES:
        # Don't fail on an unknown category — downgrade to "other".
        logger.warning(f"Unknown risk category '{category}', using 'other'")
        category = "other"

    related = raw.get("related_lines") or []
    if not isinstance(related, list):
        related = []
    related_lines = [int(x) for x in related if isinstance(x, (int, float))]

    return RiskFinding(
        line_number=line_number,
        line_content=str(raw["line_content"]).strip(),
        title=str(raw["title"]).strip()[:100],
        root_cause=str(raw["root_cause"]).strip(),
        suggested_fix=str(raw["suggested_fix"]).strip(),
        severity=severity,
        exception_type=str(raw["exception_type"]).strip(),
        confidence=confidence,
        category=category,
        blast_radius_reason=str(raw["blast_radius_reason"]).strip(),
        related_lines=related_lines,
    )


async def analyze_file_with_llm(
    file_path: str,
    file_content: str,
    language: str,
    repo_context: Optional[dict] = None,
) -> Optional[RiskFinding]:
    """
    Ask the configured LLM chain for one specific production risk in this
    file. Returns None if the LLM is unavailable or returns unparseable
    output — the caller decides what to do with that.
    """
    llm = LLMService()
    if not llm.chain:
        logger.warning("No LLM chain configured; cannot analyze file")
        return None

    system = _SYSTEM_PROMPT
    prompt = _build_user_prompt(file_path, file_content, language, repo_context)

    try:
        content = await llm.complete_raw(
            prompt=prompt,
            system=system,
            temperature=0.1,
            max_tokens=800,
            response_format="json_object",
        )
    except Exception as e:
        logger.warning(f"LLM call failed during risk analysis: {e}")
        return None

    if not content:
        logger.warning("LLM returned no content for risk analysis")
        return None

    import json
    import re

    # Providers may wrap the JSON in prose. Extract the first { ... } block.
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.warning("LLM output contained no JSON object")
        return None

    try:
        raw = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"LLM output was not valid JSON: {e}")
        return None

    try:
        return _validate(raw)
    except (ValueError, KeyError, TypeError) as e:
        logger.warning(f"LLM output failed validation: {e}")
        return None
