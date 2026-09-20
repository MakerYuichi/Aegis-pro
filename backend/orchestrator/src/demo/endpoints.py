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
    "severity": "P1",
    "status": "active",
    "title": "Potential TypeError when service.on_call is undefined",
    "description": (
        "This is a real analysis of the AEGIS PRO codebase. The Services page "
        "assumes every service object has an on_call array. If the API ever "
        "omits the field, the page crashes. Paste a public GitHub repo URL "
        "below to see the same pipeline run against your own project."
    ),
    "stack_trace": (
        "TypeError: Cannot read properties of undefined (reading 'length')\n"
        "\tat frontend/src/pages/ServicesPage.tsx:260\n"
        "\t    {service.on_call.length > 0 ? service.on_call.join(', ') : 'No one assigned'}"
    ),
    "exception_type": "TypeError",
    "file_path": "frontend/src/pages/ServicesPage.tsx",
    "line_number": 260,
    "root_cause": (
        "The component assumes that every service object includes an "
        "on_call array. If the API response omits this field or returns "
        "null/undefined, accessing .length throws a TypeError and breaks "
        "the entire Services page rendering."
    ),
    "suggested_fix": (
        "Default on_call to an empty array when undefined, e.g. "
        "(service.on_call ?? []).length > 0 ? (service.on_call ?? []).join(', ') "
        ": 'No one assigned' — or ensure the API always returns an array."
    ),
    "rollback_command": "kubectl rollout undo deploy/aegis-pro -n production",
    "confidence_score": 0.78,
    "declared_at": "2026-09-21T02:51:18Z",
    "affected_services": ["aegis-pro", "auth", "ledger"],
    "extra_metadata": {
        "simulated": True,
        "demo_default": True,
        "rag_context_used": False,
        "demo_quality": {
            "confidence": "high",
            "real_file": True,
            "category": "null_access",
            "blast_radius_reason": (
                "A single missing on_call field will cause the whole "
                "Services page to crash, affecting all users viewing the page."
            ),
            "related_lines": [259, 260, 261],
        },
        "github": {
            "blame": {
                "commit_hash": "b0ae93c3",
                "author": "MakerYuichi",
                "author_avatar": None,
                "message": "feat(auth): wire Auth0 into React frontend (closes #11)",
                "line": 260,
                "file": "frontend/src/pages/ServicesPage.tsx",
                "pr_number": 17,
                "pr_title": "feat(auth): add Auth0 authentication to React frontend",
                "pr_url": "https://github.com/MakerYuichi/Aegis-pro/pull/17",
                "pr_author": "MakerYuichi",
                "contributors": [
                    {"username": "MakerYuichi", "role": "author", "avatar": None, "url": None},
                    {"username": "dependabot[bot]", "role": "contributor", "avatar": None, "url": None},
                ],
            },
            "related_prs": [
                {
                    "number": 17,
                    "title": "feat(auth): add Auth0 authentication to React frontend",
                    "author": "MakerYuichi",
                    "url": "https://github.com/MakerYuichi/Aegis-pro/pull/17",
                    "merged_at": "2026-09-16T00:00:00Z",
                    "relevance_score": 0.80,
                    "reason": (
                        "PR #17 modified ServicesPage.tsx, which contains "
                        "the failing line 260, and likely introduced "
                        "changes near that area (authentication logic)."
                    ),
                },
            ],
            "recent_prs": [],
        },
        "code_context": {
            "file_path": "frontend/src/pages/ServicesPage.tsx",
            "line_number": 260,
            "total_lines": 300,
            "code_snippet": (
                " 254                     {/* Owner & Dependencies */}\n"
                " 255                     <div className=\"flex items-center justify-between text-sm\">\n"
                " 256                       <div className=\"flex items-center gap-2\">\n"
                " 257                         <User className=\"w-4 h-4 text-light-muted dark:text-dark-muted\" />\n"
                " 258                         <span className=\"text-light-muted dark:text-dark-muted\">On-Call:</span>\n"
                " 259                         <span className=\"text-light-text dark:text-dark-text\">\n"
                " 260 >>>                       {service.on_call.length > 0 ? service.on_call.join(', ') : 'No one assigned'}\n"
                " 261                         </span>"
            ),
            "simulated": False,
        },
        "auto_fix": {
            "status": "pr_draft",
            "approved": False,
            "requires_approval": True,
            "mode": "pr_draft",
            "approval_url": "/approve/INC-DEMO-AEGIS-0001",
            "fix_preview": (
                "@@ -260,1 +260,1 @@\n"
                "- {service.on_call.length > 0 ? service.on_call.join(', ') : 'No one assigned'}\n"
                "+ {(service.on_call ?? []).length > 0 ? (service.on_call ?? []).join(', ') : 'No one assigned'}"
            ),
            "explanation": (
                "Default on_call to an empty array when undefined."
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

    # ── Fetch the file, commits, contributors ───────────────────────────
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
        with timer.stage("fetch_recent_prs_ms"):
            recent_prs = await github_fetcher.fetch_recent_prs(org, repo)
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

    # ── Fetch and score related PRs (uses the risk's line number) ───────
    try:
        with timer.stage("fetch_file_prs_ms"):
            related_prs = await github_fetcher.fetch_related_prs(
                org, repo, candidate.path, risk.line_number, per_commit_prs=10
            )
    except GitHubFetchError as e:
        logger.warning(f"Related PRs fetch failed: {e}")
        related_prs = []

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
            recent_prs=recent_prs,
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
