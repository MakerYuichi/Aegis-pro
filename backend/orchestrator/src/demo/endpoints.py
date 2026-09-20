from datetime import datetime, timezone
from typing import Any
import hashlib
import time
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from loguru import logger

from src.config import settings
from src.demo.incident_generator import generate_incident_from_analysis
from src.demo.repo_parser import parse_repo_input, supported_shapes
from src.demo.session_service import record_session, count_successful_tries
from src.demo import github_fetcher
from src.demo.github_fetcher import (
    GitHubRepoNotFoundError,
    GitHubRateLimitError,
    GitHubNetworkError,
    GitHubFetchError,
)
from src.demo.file_selector import select_target_file
from src.demo.risk_analyzer import analyze_file


router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

SESSION_COOKIE = "demo_session_id"
SESSION_MAX_AGE = 60 * 60 * 4  # 4 hours

# Timing limit (Redis token bucket): 20 requests per hour, 1 per 3 seconds.
RATE_MAX = 20
RATE_WINDOW_SECONDS = 3600
RATE_MIN_INTERVAL_SECONDS = 3

# Try cap: 3 successful analyses per session, then signup_required.
MAX_TRIES = 3


class GenerateRequest(BaseModel):
    repo_url: str


# ── Aegis-pro default ────────────────────────────────────────────────────

_AEGIS_DEFAULT = {
    "incident_id": "INC-DEMO-AEGIS-0001",
    "service_name": "aegis-pro",
    "severity": "P0",
    "status": "active",
    "title": "UPI Payment Failure — NullPointerException in Reference Resolution",
    "description": (
        "This is the AEGIS PRO sample incident. It shows the full analysis "
        "AEGIS produces for a real failure — paste a GitHub repo URL below "
        "to see the same pipeline against your own project."
    ),
    "stack_trace": (
        "java.lang.NullPointerException: Cannot invoke "
        "\"String.length()\" because the return value of "
        "\"com.makeryuichi.aegis.PaymentProcessor.getReferenceId()\" is null\n"
        "\tat com.makeryuichi.aegis.PaymentProcessor.processUpiPayment"
        "(PaymentProcessor.java:442)\n"
        "\tat com.makeryuichi.aegis.PaymentController.handle"
        "(PaymentController.java:118)"
    ),
    "exception_type": "NullPointerException",
    "file_path": "src/main/java/com/makeryuichi/aegis/PaymentProcessor.java",
    "line_number": 442,
    "root_cause": (
        "A recent refactor removed the null guard on the UPI gateway "
        "response. The gateway intermittently returns a response without "
        "a reference id on failure, and the downstream code assumes it "
        "is always present."
    ),
    "suggested_fix": (
        "Restore the null guard before accessing getReferenceId(). "
        "Fall back to request.getTransactionId() when the gateway omits "
        "the reference."
    ),
    "rollback_command": "kubectl rollout undo deploy/aegis-pro -n production",
    "confidence_score": 0.95,
    "declared_at": "2026-09-16T10:00:00Z",
    "affected_services": ["aegis-pro", "auth", "ledger", "database"],
    "extra_metadata": {
        "simulated": True,
        "demo_default": True,
        "rag_context_used": False,
        "github": {
            "blame": {
                "commit_hash": "a3f9d21c",
                "author": "eng-lead@makeryuichi.dev",
                "author_avatar": None,
                "message": "refactor(upi): simplify response handling",
                "line": 442,
                "file": "src/main/java/com/makeryuichi/aegis/PaymentProcessor.java",
                "pr_number": 127,
                "pr_title": "refactor(upi): simplify response handling",
                "pr_url": "https://github.com/MakerYuichi/Aegis-pro/pull/127",
                "pr_author": "eng-lead@makeryuichi.dev",
                "contributors": [
                    {
                        "username": "eng-lead@makeryuichi.dev",
                        "role": "author",
                        "avatar": None,
                        "url": None,
                    }
                ],
            },
            "related_prs": [
                {
                    "number": 127,
                    "title": "refactor(upi): simplify response handling",
                    "author": "eng-lead@makeryuichi.dev",
                    "url": "https://github.com/MakerYuichi/Aegis-pro/pull/127",
                    "merged_at": "2026-09-14T18:32:00Z",
                    "files": ["src/main/java/com/makeryuichi/aegis/PaymentProcessor.java"],
                    "relevance_score": 0.93,
                    "reason": (
                        "PR #127 removed the null guard on the UPI gateway "
                        "response at line 442."
                    ),
                },
                {
                    "number": 125,
                    "title": "feat(ledger): add idempotency key to entries",
                    "author": "eng-lead@makeryuichi.dev",
                    "url": "https://github.com/MakerYuichi/Aegis-pro/pull/125",
                    "merged_at": "2026-09-12T09:21:00Z",
                    "files": ["src/main/java/com/makeryuichi/aegis/LedgerEntry.java"],
                    "relevance_score": 0.41,
                    "reason": "PR #125 touched LedgerEntry, not the reference-id path.",
                },
            ],
        },
        "code_context": {
            "file_path": "src/main/java/com/makeryuichi/aegis/PaymentProcessor.java",
            "line_number": 442,
            "total_lines": 612,
            "code_snippet": (
                " 435     UpiResponse upiResponse = upiGateway.initiate(request);\n"
                " 436\n"
                " 437     LedgerEntry entry = new LedgerEntry();\n"
                " 438     entry.setAmount(request.getAmount());\n"
                " 439     entry.setCurrency(request.getCurrency());\n"
                " 440\n"
                " 441\n"
                " 442 >>>     entry.setReference(upiResponse.getReferenceId());\n"
                " 443\n"
                " 444     ledgerClient.record(entry);"
            ),
            "simulated": True,
        },
        "auto_fix": {
            "status": "pr_draft",
            "approved": False,
            "requires_approval": True,
            "mode": "pr_draft",
            "approval_url": "/approve/INC-DEMO-AEGIS-0001",
            "fix_preview": (
                "@@ -441,3 +441,5 @@\n"
                "-        entry.setReference(upiResponse.getReferenceId());\n"
                "+        String ref = upiResponse != null\n"
                "+            ? upiResponse.getReferenceId()\n"
                "+            : request.getTransactionId();\n"
                "+        entry.setReference(ref);"
            ),
            "explanation": (
                "Add a null guard before accessing getReferenceId(). "
                "Fall back to the request-scoped transaction id when the "
                "gateway omits the reference."
            ),
            "pr": {
                "status": "pr_draft",
                "approval_required": True,
                "approval_url": "/approve/INC-DEMO-AEGIS-0001",
            },
        },
    },
}


# ── Timing helpers ───────────────────────────────────────────────────────

class _Timer:
    """Collect per-stage timings as ms. Attach to the response's meta block."""

    def __init__(self):
        self._start = time.perf_counter()
        self._stages: dict[str, int] = {}

    def stage(self, name: str) -> "_StageTimer":
        """Context manager: records elapsed ms for a named stage."""
        return _StageTimer(self, name)

    def _record(self, name: str, ms: int) -> None:
        self._stages[name] = ms

    def total_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)

    def snapshot(self) -> dict[str, int]:
        return {**self._stages, "total_ms": self.total_ms()}


class _StageTimer:
    def __init__(self, timer: _Timer, name: str):
        self._timer = timer
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "_StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        ms = int((time.perf_counter() - self._start) * 1000)
        self._timer._record(self._name, ms)


# ── Helpers ──────────────────────────────────────────────────────────────

def _require_demo_mode() -> None:
    if not settings.DEMO_MODE:
        # 404, not 403 — the route simply does not exist in production.
        raise HTTPException(status_code=404, detail="Not found")


def _get_or_create_session(request: Request, response: Response) -> str:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        sid = uuid.uuid4().hex
        response.set_cookie(
            SESSION_COOKIE,
            sid,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return sid


async def _check_rate_limit(session_id: str) -> None:
    """
    Redis token bucket. Fail-open: if Redis is unreachable, allow the
    request and log a warning. The demo must never break because of a
    rate limiter.
    """
    try:
        client = redis.from_url(settings.REDIS_URL)
        try:
            last_key = f"demo:last:{session_id}"
            last = await client.get(last_key)
            now = datetime.now(timezone.utc).timestamp()

            if last is not None:
                elapsed = now - float(last)
                if elapsed < RATE_MIN_INTERVAL_SECONDS:
                    raise HTTPException(
                        status_code=429,
                        detail="Slow down. Try again in a moment.",
                        headers={"Retry-After": str(int(RATE_MIN_INTERVAL_SECONDS - elapsed) + 1)},
                    )

            count_key = f"demo:count:{session_id}"
            count = await client.incr(count_key)
            if count == 1:
                await client.expire(count_key, RATE_WINDOW_SECONDS)
            if count > RATE_MAX:
                ttl = await client.ttl(count_key)
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {ttl}s.",
                    headers={"Retry-After": str(max(ttl, 1))},
                )

            await client.set(last_key, str(now), ex=RATE_WINDOW_SECONDS)
        finally:
            await client.aclose()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"⚠️ Demo rate limiter unavailable ({e}); allowing request")
        return


def _error_payload(reason: str, detail: str) -> dict:
    """Uniform error response shape for the frontend."""
    return {
        "error": reason,
        "reason": reason,
        "detail": detail,
        "supported_shapes": supported_shapes(),
    }


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/default")
async def demo_default(response: Response):
    _require_demo_mode()
    response.set_cookie(
        SESSION_COOKIE,
        uuid.uuid4().hex,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return _AEGIS_DEFAULT


@router.post("/generate")
async def demo_generate(
    request_body: GenerateRequest,
    request: Request,
    response: Response,
):
    _require_demo_mode()
    session_id = _get_or_create_session(request, response)

    timer = _Timer()

    # ── Try cap (checked first, before any external call) ───────────────
    with timer.stage("try_check_ms"):
        tries_used = await count_successful_tries(session_id)
    if tries_used >= MAX_TRIES:
        return {
            "signup_required": True,
            "reason": "signup_required",
            "detail": (
                f"You've seen {MAX_TRIES} real analyses. Sign up to run "
                "AEGIS PRO on your own stack with your own credentials."
            ),
            "tries_remaining": 0,
        }

    # ── Timing limit (Redis token bucket, fail-open) ────────────────────
    await _check_rate_limit(session_id)

    # ── Parse the URL ───────────────────────────────────────────────────
    with timer.stage("parse_ms"):
        parsed = parse_repo_input(request_body.repo_url)
    if not parsed.ok:
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(parsed.reason, parsed.detail)

    org = parsed.org
    repo = parsed.repo

    # ── Fetch repo metadata + tree (cached) ─────────────────────────────
    try:
        with timer.stage("fetch_meta_ms"):
            repo_meta = await github_fetcher.fetch_repo_metadata(org, repo)
        with timer.stage("fetch_tree_ms"):
            tree = await github_fetcher.fetch_tree(
                org, repo, repo_meta["default_branch"]
            )
    except GitHubRepoNotFoundError:
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "not_found",
            f"GitHub doesn't have a public repo at {org}/{repo}. "
            "Check the URL, or try a different repo.",
        )
    except GitHubRateLimitError as e:
        retry = "a few minutes" if not e.reset_epoch else "a few minutes"
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "rate_limited",
            f"GitHub's public API is rate-limited right now. Try again in {retry}.",
        )
    except (GitHubNetworkError, GitHubFetchError) as e:
        logger.warning(f"GitHub fetch failed: {e}")
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "github_unavailable",
            "Couldn't reach GitHub right now. Try again in a moment.",
        )

    # ── Select the target file ──────────────────────────────────────────
    language = repo_meta.get("language") or parsed.language_hint
    with timer.stage("select_file_ms"):
        candidate = select_target_file(tree, language)

    if candidate is None:
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "empty_repo",
            "This repository appears to be completely empty. "
            "Try a repo with active code configurations to launch the simulation.",
        )

    if candidate.confidence == "fallback":
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "not_code",
            "This repository doesn't contain code that can fail. "
            "AEGIS PRO analyzes source files — READMEs, configs, and docs "
            "don't produce incidents.",
        )

    # ── Fetch the file, commits, contributors, PRs ──────────────────────
    try:
        with timer.stage("fetch_file_ms"):
            file_content = await github_fetcher.fetch_file_content(
                org, repo, candidate.path
            )
        with timer.stage("fetch_commits_ms"):
            file_commits = await github_fetcher.fetch_file_commits(
                org, repo, candidate.path
            )
        with timer.stage("fetch_contributors_ms"):
            contributors = await github_fetcher.fetch_contributors(org, repo)
        with timer.stage("fetch_prs_ms"):
            related_prs = await github_fetcher.fetch_recent_prs(org, repo)
    except GitHubFetchError as e:
        logger.warning(f"GitHub fetch failed for {candidate.path}: {e}")
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "github_unavailable",
            "Couldn't fetch the file from GitHub right now. Try again in a moment.",
        )

    # ── Analyze the file for risks ──────────────────────────────────────
    with timer.stage("analyze_ms"):
        risk = await analyze_file(
            file_path=candidate.path,
            file_content=file_content["content"],
            language=language,
            repo_context=repo_meta,
        )

    if risk is None:
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "no_risk_found",
            "We couldn't identify a specific production failure in this "
            "repo. This is rare — it usually means the file is too small "
            "or too clean. Try a different repo.",
        )

    # ── Generate the incident ───────────────────────────────────────────
    seed = int(
        hashlib.sha256(
            f"{org}/{repo}/{session_id}".encode()
        ).hexdigest()[:12],
        16,
    )

    with timer.stage("generate_ms"):
        incident = await generate_incident_from_analysis(
            parsed=parsed,
            seed=seed,
            repo_meta=repo_meta,
            target_file=candidate.path,
            file_content=file_content["content"],
            risk=risk,
            related_prs=related_prs,
            file_commits=file_commits,
            contributors=contributors,
        )

    if incident is None:
        # Shouldn't happen given the checks above, but guard anyway.
        await record_session(session_id, request_body.repo_url, parsed, None)
        return _error_payload(
            "generation_failed",
            "Something went wrong building the incident. Try again.",
        )

    await record_session(session_id, request_body.repo_url, parsed, incident)

    return {
        "incident": incident,
        "parsed": {
            "host": parsed.host,
            "org": parsed.org,
            "repo": parsed.repo,
            "language_hint": parsed.language_hint,
        },
        "meta": {
            "tries_remaining": MAX_TRIES - tries_used - 1,
            "timings": timer.snapshot(),
        },
    }


@router.post("/reset")
async def demo_reset(response: Response):
    _require_demo_mode()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "reset"}
