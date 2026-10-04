"""Score a finding after its chain is built.

This is the *second* scorer in the pipeline. It answers a different
question from `file_selector`:

    file_selector  (Step 2)  → "which files should we look at?"
    signal_scorer  (Step 5)  → "is this finding worth surfacing?"

The two are not the same function with different arguments. They
run at different moments, on different inputs, for different
purposes.

The scoring function:

    score = base(pattern, confidence)
          + chain_bonus(depth)
          + terminal_bonus(kind)
          + blame_bonus(age)
          + coverage_bonus(coverage_proxy)

Chain depth is the largest term because a multi-file bug is
inherently more interesting than a single-file smell. A finding
that spans three files is a logic bug; a finding that names one
line is a lint.

Base scores by confidence:
    high   → 0.8
    medium → 0.5
    low    → 0.2

Chain bonus (additive in the total):
    depth 1 → 0.0
    depth 2 → 0.15
    depth 3+ → 0.25

Terminal kind bonus:
    Optional → 0.15  (the suspicion is confirmed by the type)
    Concrete → -0.10 (the type says it can't be None — penalize)
    Unknown  → 0.0

Blame bonus (only when blame is provided):
    recent  (< 30 days)  → +0.10  (fresh code, riskier)
    old     (>= 30 days) → -0.05  (survived production)
    None                 →  0.0   (no signal)

Coverage bonus (only when coverage_proxy is provided):
    True   → -0.15  (tested — less likely to be a latent bug)
    False  → +0.05  (untested — more likely)
    None   →  0.0   (no signal)

The blame and coverage terms are optional. When the caller
doesn't have the data, they contribute 0.0 and the score is
identical to the pre-2B behavior. This means the scorer can be
called incrementally — a caller that only has a chain gets the
old score, a caller with blame + coverage gets the sharper score.

Both signals are single, well-scoped inputs rather than
sub-scorers the scorer fetches itself. Same discipline as
_realign_diff taking file_lines as an argument rather than reading
the workdir, and record_* taking plain dicts rather than reaching
into a session. The scorer is a pure function; the caller does
I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.scanner.candidate import (
    CHAIN_TRACED,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_UNTRACEABLE,
    ChainResult,
    PatternMatch,
)


# ---------------------------------------------------------------------------
# Base scores
# ---------------------------------------------------------------------------

_CONFIDENCE_BASE: dict[str, float] = {
    "high": 0.8,
    "medium": 0.5,
    "low": 0.2,
}


# Blame recency threshold. A commit within this window is "fresh"
# code — recently touched, less time to have had bugs shaken out.
_BLAME_RECENT_DAYS = 30
_BLAME_RECENT_BONUS = 0.10
_BLAME_OLD_PENALTY = -0.05


# Coverage proxy adjustments. A symbol exercised by tests is less
# likely to hide a latent bug; one with no test reference is more
# likely.
_COVERAGE_TESTED_PENALTY = -0.15
_COVERAGE_UNTESTED_BONUS = 0.05


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_finding(
    match: PatternMatch,
    chain: ChainResult,
    *,
    blame: dict | None = None,
    coverage_proxy: bool | None = None,
) -> tuple[float, str]:
    """Compute a score and a one-sentence reasoning for a finding.

    Returns (score, reasoning). Score is clamped to [0.0, 1.0].

    Args:
        match:           the PatternMatch the finding came from
        chain:           the ChainResult from build_chain for the
                         match's (file, line, symbol)
        blame:           optional. {author, commit_hash, timestamp}
                         where timestamp is an ISO-8601 string or a
                         datetime. Used for the recency signal.
                         Pass None when the caller has no blame.
        coverage_proxy:  optional. True when the symbol appears in a
                         test file, False when it does not, None
                         when the caller didn't check. This is a
                         *proxy* — a name-in-tests search, not real
                         coverage data. Named accordingly so no
                         consumer mistakes it for ground truth.

    When the chain is untraced, only the base score and the optional
    bonuses contribute. A low-confidence suspicion with no chain and
    no blame/coverage signal stays low.
    """
    base = _CONFIDENCE_BASE.get(match.confidence, 0.2)

    if chain.status != CHAIN_TRACED or not chain.chain:
        # No chain. Base score plus the optional signals.
        if match.requires_chain:
            score = base * 0.5
        else:
            score = base
        score += _blame_bonus(blame)
        score += _coverage_bonus(coverage_proxy)
        score = max(0.0, min(1.0, score))
        return score, _reason_no_chain(match, chain, blame, coverage_proxy)

    depth = chain.depth
    chain_bonus = _chain_bonus(depth)
    terminal_bonus = _terminal_bonus(chain.terminal_kind)
    blame_bonus = _blame_bonus(blame)
    coverage_bonus = _coverage_bonus(coverage_proxy)

    score = base + chain_bonus + terminal_bonus + blame_bonus + coverage_bonus
    score = max(0.0, min(1.0, score))

    return score, _reason_with_chain(
        match, chain, depth, blame, coverage_proxy
    )


# ---------------------------------------------------------------------------
# Bonuses
# ---------------------------------------------------------------------------

def _chain_bonus(depth: int) -> float:
    if depth <= 1:
        return 0.0
    if depth == 2:
        return 0.15
    return 0.25


def _terminal_bonus(kind: str | None) -> float:
    if kind == "Optional":
        return 0.15
    if kind == "Concrete":
        return -0.10
    return 0.0


def _blame_bonus(blame: dict | None) -> float:
    """Recency signal from git blame.

    A recently-touched line is riskier than one that has survived
    production for months. The caller provides the timestamp as
    either an ISO-8601 string or a datetime; anything unparseable
    contributes 0.0.
    """
    if not blame:
        return 0.0

    ts = blame.get("timestamp")
    if ts is None:
        return 0.0

    age_days = _age_in_days(ts)
    if age_days is None:
        return 0.0

    if age_days < _BLAME_RECENT_DAYS:
        return _BLAME_RECENT_BONUS
    return _BLAME_OLD_PENALTY


def _coverage_bonus(coverage_proxy: bool | None) -> float:
    """Symbol-level coverage signal.

    True  → the symbol name appears in a test file. Tested code is
            less likely to hide a latent bug; penalize.
    False → the symbol name does not appear in any test file.
            Untested code is more likely to hide one; boost.
    None  → the caller didn't check. No signal.
    """
    if coverage_proxy is True:
        return _COVERAGE_TESTED_PENALTY
    if coverage_proxy is False:
        return _COVERAGE_UNTESTED_BONUS
    return 0.0


def _age_in_days(ts) -> float | None:
    """Parse a timestamp and return its age in days, or None.

    Accepts ISO-8601 strings and datetime objects. A timezone-naive
    datetime is treated as UTC — the same convention the rest of the
    pipeline uses for stored timestamps.
    """
    if isinstance(ts, str):
        try:
            # Handle trailing 'Z' (which fromisoformat rejects
            # before Python 3.11).
            normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    elif isinstance(ts, datetime):
        parsed = ts
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - parsed
    return delta.total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Reasoning strings
# ---------------------------------------------------------------------------

def _reason_no_chain(
    match: PatternMatch,
    chain: ChainResult,
    blame: dict | None,
    coverage_proxy: bool | None,
) -> str:
    """Reasoning for a finding whose chain didn't trace."""
    if not match.requires_chain:
        base = (
            f"{match.pattern} at {match.file}:{match.line} — "
            f"standalone smell, no chain needed."
        )
    elif chain.status == CHAIN_UNSUPPORTED_LANGUAGE:
        base = (
            f"{match.pattern} at {match.file}:{match.line} — chain "
            f"tracing is Python-only, so the symbol {match.symbol!r} "
            f"could not be traced. Suspicion recorded, not confirmed."
        )
    elif chain.status == CHAIN_UNTRACEABLE:
        base = (
            f"{match.pattern} at {match.file}:{match.line} — could "
            f"not trace {match.symbol!r} to an origin. Suspicion "
            f"recorded, not confirmed."
        )
    else:
        base = (
            f"{match.pattern} at {match.file}:{match.line} — "
            f"suspicion recorded."
        )

    return base + _signal_suffix(blame, coverage_proxy)


def _reason_with_chain(
    match: PatternMatch,
    chain: ChainResult,
    depth: int,
    blame: dict | None,
    coverage_proxy: bool | None,
) -> str:
    """Reasoning for a finding whose chain traced."""
    files = list(dict.fromkeys(link.file for link in chain.chain))
    branch_count = chain.branch_count

    if depth == 1 and branch_count == 0:
        base = (
            f"{match.pattern} at {match.file}:{match.line} — "
            f"single-file chain, {chain.terminal_kind or 'Unknown'} "
            f"terminal at {chain.chain[-1].file}:{chain.chain[-1].line}."
        )
    elif branch_count > 0:
        base = (
            f"{match.pattern} at {match.file}:{match.line} spans "
            f"{depth} files across {branch_count} branches. "
            f"Worst-case terminal: {chain.terminal_kind or 'Unknown'}."
        )
    else:
        file_list = " → ".join(files)
        base = (
            f"{match.pattern} at {match.file}:{match.line} spans "
            f"{depth} files ({file_list}). Terminal type: "
            f"{chain.terminal_kind or 'Unknown'}."
        )

    return base + _signal_suffix(blame, coverage_proxy)


def _signal_suffix(
    blame: dict | None, coverage_proxy: bool | None
) -> str:
    """Append the blame and coverage signals to a reasoning string.

    Empty when neither signal is present, so the old reasoning
    strings are unchanged for callers that don't pass the new
    arguments.
    """
    parts: list[str] = []

    if blame:
        age_days = _age_in_days(blame.get("timestamp"))
        if age_days is not None:
            if age_days < _BLAME_RECENT_DAYS:
                parts.append(
                    f"recently touched ({int(age_days)}d ago)"
                )
            else:
                parts.append(
                    f"stable ({int(age_days)}d untouched)"
                )

    if coverage_proxy is True:
        parts.append("symbol referenced in tests")
    elif coverage_proxy is False:
        parts.append("no test reference found")

    if not parts:
        return ""

    return " " + "; ".join(parts) + "."
