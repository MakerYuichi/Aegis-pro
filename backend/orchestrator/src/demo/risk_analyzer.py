from typing import Optional

from loguru import logger

from src.demo.risk_analyzer_llm import RiskFinding, analyze_file_with_llm


__all__ = ["RiskFinding", "analyze_file"]


async def analyze_file(
    file_path: str,
    file_content: str,
    language: str,
    repo_context: Optional[dict] = None,
) -> Optional[RiskFinding]:
    """
    Analyze one file for its single most likely production risk.

    Returns a RiskFinding with the exact line, verbatim content, root
    cause, fix, and confidence. Returns None if the LLM is unavailable or
    the output cannot be validated.
    """
    logger.debug(f"Analyzing {file_path} ({language}) for production risks")
    return await analyze_file_with_llm(file_path, file_content, language, repo_context)
