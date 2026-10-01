"""Deterministic tools for the Investigator agent.

These functions read from a checked-out repo on disk. They do not call
an LLM, do not call GitHub, and are safe to unit-test with a fixture
repo. The Investigator agent decides which to invoke; this layer only
executes.

Path convention: every tool takes `repo` as an absolute path to a
working tree on disk. Resolving "which repo" is the caller's job —
the tool layer does not know about GitHub, cloning, or the pipeline's
service model.
"""
from src.agents.tools.repo_tools import (
    read_file,
    read_symbol,
    search_codebase,
    ToolResult,
)

__all__ = ["read_file", "read_symbol", "search_codebase", "ToolResult"]
