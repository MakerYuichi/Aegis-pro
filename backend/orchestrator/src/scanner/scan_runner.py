"""Orchestrate the Phase 1 scanner into a list of gated findings.

This is the composition layer. It runs the four Phase 1 modules in
sequence and applies the terminal-kind gate that Phase 1 documented
but did not enforce:

    select_files    → rank files
    match_patterns  → find suspicious shapes
    build_chain     → trace each symbol across files
    score_finding   → score each finding
    gate            → two output streams

The gate:

    terminal_kind == "Optional"          → REPORT
        The chain traced to a function whose return annotation says
        the value can be None. Confirmed risk.

    terminal_kind == "Unknown"           → INVESTIGATOR
        The chain traced, but the terminal function has no return
        annotation. Genuinely ambiguous. In scan mode the agent
        reasons about these; in manual mode they go to a queue.

    terminal_kind in {None, "Concrete"}  → DROP
        None means the chain never resolved. Concrete means the
        annotation says the value can't be None. Neither is a
        finding.

    requires_chain is False              → REPORT
        Standalone smells (bare except, mutable default arg) don't
        need a chain. They go to the report with their base score.

The runner does not filter based on `requires_chain` before
building the chain. Whether a pattern needs a chain is the
matcher's classification; the gate is applied after scoring.

Scope: Python-only. Non-Python files are skipped by the pattern
matcher, and the runner inherits that scope silently — the matcher
returns [] for them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from src.scanner.candidate import (
    CHAIN_TRACED,
    PatternMatch,
    ScanCandidate,
    ChainResult,
)
from src.scanner.call_chain_builder import build_chain
from src.scanner.file_selector import select_files
from src.scanner.pattern_matcher import match_patterns
from src.scanner.signal_scorer import score_finding
from src.scanner.pyright_runner import run_pyright
from src.scanner.ingestion_filter import should_keep
from src.scanner.variety_shuffler import variety_shuffle


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ScanOutcome:
    """One candidate that survived the gate.

    `destination` is "report" or "investigator" — the two output
    streams. The `score` is the same value `score_finding` produced;
    the gate doesn't re-score, only routes.

    `reasoning` is the human-readable explanation from the scorer,
    with the gate's destination attached as a prefix so a report can
    show "REPORT: <reasoning>" or "INVESTIGATE: <reasoning>."
    """
    destination: str                  # "report" | "investigator"
    candidate: ScanCandidate
    match: PatternMatch
    chain: ChainResult | None
    score: float
    reasoning: str


@dataclass
class ScanResult:
    """Everything a scan produced.

    `report` and `investigator_queue` are the two gated output
    streams. `dropped` is a count per reason, for telemetry.

    `repo` and `files_scanned` describe the input. `duration_ms` is
    wall time for the whole scan.
    """
    repo: str
    files_scanned: int
    report: list[ScanOutcome] = field(default_factory=list)
    investigator_queue: list[ScanOutcome] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0

    @property
    def total_candidates(self) -> int:
        return len(self.report) + len(self.investigator_queue)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "files_scanned": self.files_scanned,
            "report": [self._outcome_dict(o) for o in self.report],
            "investigator_queue": [
                self._outcome_dict(o) for o in self.investigator_queue
            ],
            "dropped": self.dropped,
            "duration_ms": self.duration_ms,
            "counts": {
                "report": len(self.report),
                "investigator": len(self.investigator_queue),
                "dropped_total": sum(self.dropped.values()),
            },
        }

    @staticmethod
    def _outcome_dict(o: ScanOutcome) -> dict:
        return {
            "destination": o.destination,
            "score": round(o.score, 4),
            "reasoning": o.reasoning,
            "candidate": o.candidate.to_dict(),
        }


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

def run_scan(
    repo_dir: Path | str,
    *,
    top_n: int = 25,
    since_days: int = 30,
    max_candidates: int = 100,
) -> ScanResult:
    """Run the Phase 1 scanner and gate its findings.

    Args:
        repo_dir:       path to the repo root.
        top_n:          max files to scan (from file_selector).
        since_days:     churn window for file_selector.
        max_candidates: hard cap on the number of candidates scored.
                        Protects against a pathological repo where
                        every file fires every pattern.

    Returns a ScanResult with two gated lists and a dropped count.
    Never raises — a scan of an empty or unreadable repo returns an
    empty result, not an exception.
    """
    import time
    start = time.monotonic()

    repo_path = Path(repo_dir).resolve()
    result = ScanResult(
        repo=str(repo_path),
        files_scanned=0,
    )

    if not repo_path.is_dir():
        logger.warning(f"scan_runner: not a directory: {repo_path}")
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    files = select_files(repo_path, top_n=top_n, since_days=since_days)
    result.files_scanned = len(files)
    if not files:
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    dropped = Counter()

    # ── Phase 1: collect every candidate from every file ─────────
    #
    # The cap is applied in Phase 3, not here. Collecting first is
    # what makes the cap fair across files. If we cap during the
    # file loop, files that come first in the selector's churn
    # order (models.py, utils.py) consume the entire budget before
    # later files are even scanned. requests/status_codes.py is
    # file #19 of 20 in the selector; without this two-phase
    # structure its Pyright finding is dropped before it exists.
    #
    # Collection is cheap: match_patterns is AST-walking (milliseconds)
    # and run_pyright is one subprocess per file (~0.17s on this
    # repo). No chain building, no scoring, no LLM.
    all_matches: list[tuple[Path, PatternMatch]] = []
    for f in files:
        for m in match_patterns(repo_path / f.path, f.path):
            all_matches.append((repo_path / f.path, m))
        for m in run_pyright(repo_path / f.path, f.path):
            all_matches.append((repo_path / f.path, m))

    # ── Phase 2: ingestion filter ───────────────────────────────
    #
    # Deterministic drop of provably-safe candidates. Same rules
    # as before, applied to the full collected set.
    survivors: list[tuple[Path, PatternMatch]] = []
    for file_path, m in all_matches:
        if not should_keep(m, repo_path):
            dropped["ingestion_filtered"] += 1
            continue
        survivors.append((file_path, m))

    # ── Phase 3: cap with per-file diversity guarantee ─────────
    #
    # Guarantee every file contributes at least one candidate
    # before the cap fires. Then fill remaining slots in file
    # iteration order. This is stronger than a plain slice or a
    # round-robin shuffle: even a file with only one candidate
    # (like requests/status_codes.py at position 19 of 20) is
    # guaranteed a slot, regardless of how many candidates the
    # earlier files produced.
    #
    # Rationale for diversity-first over round-robin: with 20
    # files and a cap of 100, round-robin gives each file ~5
    # slots, but only if all files have ~5 candidates. A file
    # with one candidate is overserved by round-robin; a file
    # with 50 candidates is underserved. Diversity-first
    # guarantees one slot per file — the minimum that makes
    # the cap fair — then distributes the remainder by
    # iteration order, which preserves the selector's ranking.
    if max_candidates > 0 and len(survivors) > max_candidates:
        # Group survivors by file, preserving within-file order.
        by_file: dict[str, list[tuple[Path, PatternMatch]]] = {}
        file_order: list[str] = []  # first-seen order of file paths
        for fp, m in survivors:
            key = str(fp)
            if key not in by_file:
                by_file[key] = []
                file_order.append(key)
            by_file[key].append((fp, m))

        # Round 1: one candidate from each file, in file order.
        # This is what guarantees diversity.
        guaranteed: list[tuple[Path, PatternMatch]] = []
        for key in file_order:
            if by_file[key]:
                guaranteed.append(by_file[key].pop(0))

        # If guaranteed alone exceeds the cap (more files with
        # candidates than max_candidates), truncate. This only
        # happens when max_candidates < number of files, which
        # is a configuration problem, but truncate honestly.
        if len(guaranteed) >= max_candidates:
            for _ in guaranteed[max_candidates:]:
                dropped["max_candidates_reached"] += 1
            survivors = guaranteed[:max_candidates]
        else:
            # Round 2+: fill remaining slots from leftover
            # candidates, preserving file iteration order.
            remaining_slots = max_candidates - len(guaranteed)
            leftovers: list[tuple[Path, PatternMatch]] = []
            for key in file_order:
                leftovers.extend(by_file[key])
            for _ in leftovers[remaining_slots:]:
                dropped["max_candidates_reached"] += 1
            survivors = guaranteed + leftovers[:remaining_slots]

    # ── Phase 4: score and gate ─────────────────────────────────
    for file_path, m in survivors:
        outcome = _score_and_gate(repo_path, m)

        if outcome is None:
            dropped[_drop_reason(repo_path, m)] += 1
            continue

        if outcome.destination == "report":
            result.report.append(outcome)
        else:
            result.investigator_queue.append(outcome)

    # Sort each stream by score descending, so the top finding is
    # first. The report and the queue sort independently.
    result.report.sort(key=lambda o: -o.score)
    result.investigator_queue.sort(key=lambda o: -o.score)

    # Variety shuffle: round-robin across files so the queue is not
    # starved by the top-churn files. Same scores, different order.
    # `status_codes.py:116` becomes the second item processed even
    # though 10 `models.py` candidates outrank it.
    result.report = variety_shuffle(result.report)
    result.investigator_queue = variety_shuffle(result.investigator_queue)

    result.dropped = dict(dropped)
    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result


def _score_and_gate(
    repo_path: Path, match: PatternMatch
) -> ScanOutcome | None:
    """Score one match and apply the gate.

    Returns a ScanOutcome for report/investigator, or None when the
    gate drops the candidate.
    """
    if not match.requires_chain:
        # Standalone smell — no chain needed. Score directly.
        score, reason = score_finding(match, _empty_chain())
        return ScanOutcome(
            destination="report",
            candidate=_as_candidate(match, None, score, reason),
            match=match,
            chain=None,
            score=score,
            reasoning=f"REPORT: {reason}",
        )

    chain = build_chain(repo_path, match.file, match.line, match.symbol)
    score, reason = score_finding(match, chain)

    if chain.terminal_kind == "Optional":
        return ScanOutcome(
            destination="report",
            candidate=_as_candidate(match, chain, score, reason),
            match=match,
            chain=chain,
            score=score,
            reasoning=f"REPORT: {reason}",
        )

    if chain.terminal_kind in ("Unknown", None):
        return ScanOutcome(
            destination="investigator",
            candidate=_as_candidate(match, chain, score, reason),
            match=match,
            chain=chain,
            score=score,
            reasoning=f"INVESTIGATE: {reason}",
        )

    return None


def _drop_reason(repo_path: Path, match: PatternMatch) -> str:
    """Compute a drop reason for telemetry.

    Called only for matches that _score_and_gate dropped. Rebuilds
    the chain to classify — that's wasteful, but it's the cleanest
    way to keep _score_and_gate focused on the happy path. If this
    shows up in profiles, refactor to return the reason from the
    gate.
    """
    if not match.requires_chain:
        return "standalone_reported"
    chain = build_chain(repo_path, match.file, match.line, match.symbol)
    if chain.terminal_kind == "Concrete":
        return "concrete_terminal"
    if chain.terminal_kind is None:
        return "no_terminal_kind"
    if chain.status != CHAIN_TRACED:
        return "untraceable"
    return "unknown_dropped"


def _empty_chain() -> ChainResult:
    """An empty ChainResult for standalone patterns.

    Standalone patterns don't need a chain, but score_finding still
    wants one. This is the honest no-chain input: status untraceable,
    no links. score_finding's `requires_chain=False` branch reads
    the match, not the chain, so the empty chain is inert.
    """
    return ChainResult(status="untraceable")


def _as_candidate(
    match: PatternMatch,
    chain: ChainResult | None,
    score: float,
    reasoning: str,
) -> ScanCandidate:
    """Build a ScanCandidate from a match and (optionally) a chain."""
    return ScanCandidate(
        root_file=match.file,
        root_line=match.line,
        symbol=match.symbol,
        pattern=match.pattern,
        chain=list(chain.chain) if chain else [],
        chain_status=chain.status if chain else "untraceable",
        chain_depth=chain.depth if chain else 0,
        score=score,
        reasoning=reasoning,
        metadata={
            "confidence": match.confidence,
            "terminal_kind": chain.terminal_kind if chain else None,
            "branch_count": chain.branch_count if chain else 0,
        },
    )
