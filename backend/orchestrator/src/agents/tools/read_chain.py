"""Read all files in a call chain in one observation.

This is a specialization of `read_file`. Where `read_file` reads
one file at a given line, `read_chain` reads every (file, line)
pair in a chain and returns their contents as one observation.

Design notes:

- Reuses the existing line-windowing logic from `read_file`. The
  window format (`NNNNN  content`) and the ±context_lines default
  match, so the agent's view is consistent whichever tool it calls.

- Caps per-file size (MAX_CHARS_PER_FILE) and total files
  (MAX_FILES). Files past MAX_FILES are noted as
  "+N more files, truncated — call read_file for X, Y" so the
  observation is honest about what it's not showing.

- No network. No writes. Pure function of (repo, chain).
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.agents.tools.repo_tools import (
    ToolResult,
    _safe_resolve,
    _find_by_basename,
)


# Per-file character cap. Matches read_file's MAX_FILE_CHARS/2 —
# a chain shows N files, so each gets a smaller budget to keep the
# total observation bounded.
MAX_CHARS_PER_FILE = 2000

# Max files included in one chain read.
MAX_FILES = 5

# Lines of context around each link's line.
DEFAULT_CONTEXT_LINES = 20


async def read_chain(
    repo: str,
    chain: list[dict],
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> ToolResult:
    """Read every file in a chain in one observation.

    `chain` is a list of {"file": str, "line": int} dicts, in
    traversal order. Each entry corresponds to one ChainLink.

    Returns a ToolResult whose `result` is a concatenation of
    per-file windows, each prefixed with a header:

        === file.py:42 (context 22-62) ===
           22  <line>
           23  <line>
        ...

    Files past MAX_FILES are replaced with a one-line note listing
    their paths, so the agent knows what it's missing.
    """
    args = {
        "chain_length": len(chain),
        "context_lines": context_lines,
    }

    if not chain:
        return ToolResult(
            ok=False,
            tool="read_chain",
            args=args,
            error="empty_chain",
        )

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return ToolResult(
            ok=False, tool="read_chain", args=args, error="repo_not_found",
        )

    sections: list[str] = []
    truncated_files: list[str] = []

    for i, link in enumerate(chain):
        if i >= MAX_FILES:
            truncated_files.append(f"{link.get('file', '?')}:{link.get('line', '?')}")
            continue

        section = _read_link(
            repo_path=repo_path,
            file_path=link.get("file", ""),
            line_number=link.get("line", 0),
            context_lines=context_lines,
        )
        if section is not None:
            sections.append(section)

    if truncated_files:
        sections.append(
            f"\n=== +{len(truncated_files)} more files, truncated ===\n"
            f"Call read_file directly for:\n  "
            + "\n  ".join(truncated_files)
        )

    if not sections:
        return ToolResult(
            ok=False,
            tool="read_chain",
            args=args,
            error="no_files_read",
        )

    return ToolResult(
        ok=True,
        tool="read_chain",
        args=args,
        result="\n\n".join(sections),
        truncated=bool(truncated_files),
        metadata={
            "files_included": min(len(chain), MAX_FILES),
            "files_truncated": len(truncated_files),
        },
    )


def _read_link(
    *,
    repo_path: Path,
    file_path: str,
    line_number: int,
    context_lines: int,
) -> str | None:
    """Read one link's window. Returns the formatted section, or None."""
    resolved, _reason = _safe_resolve(str(repo_path), file_path)
    if resolved is None or not resolved.is_file():
        hint = _find_by_basename(str(repo_path), file_path)
        if hint:
            resolved, _ = _safe_resolve(str(repo_path), hint)
        if resolved is None or not resolved.is_file():
            return f"=== {file_path}:{line_number} === (file not found)\n"

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"=== {file_path}:{line_number} === (read failed)\n"

    lines = text.splitlines()
    total = len(lines)

    start = max(1, line_number - context_lines)
    end = min(total, line_number + context_lines)

    window = lines[start - 1 : end]
    numbered = "\n".join(
        f"{start + i:5d}  {line}" for i, line in enumerate(window)
    )
    if len(numbered) > MAX_CHARS_PER_FILE:
        numbered = numbered[:MAX_CHARS_PER_FILE] + "\n[... truncated]"

    return f"=== {file_path}:{line_number} (lines {start}-{end} of {total}) ===\n{numbered}"
