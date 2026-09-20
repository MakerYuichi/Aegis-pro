from datetime import datetime, timezone
from typing import Any
import hashlib
import secrets
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from loguru import logger

from src.config import settings
from src.demo.incident_generator import generate_incident
from src.demo.repo_parser import parse_repo_input, supported_shapes
from src.demo.session_service import record_session


router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

SESSION_COOKIE = "demo_session_id"
SESSION_MAX_AGE = 60 * 60 * 4  # 4 hours

# Rate limit: 20 generate calls per session per hour, max 1 per 3 seconds.
RATE_MAX = 20
RATE_WINDOW_SECONDS = 3600
RATE_MIN_INTERVAL_SECONDS = 3


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
            # Minimum interval between calls.
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

            # Window count.
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


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/default")
async def demo_default(response: Response):
    _require_demo_mode()
    # Ensure the session cookie is set even on first load, so /generate
    # uses the same session id.
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

    await _check_rate_limit(session_id)

    parsed = parse_repo_input(request_body.repo_url)

    if not parsed.ok:
        await record_session(session_id, request_body.repo_url, parsed, None)
        return {
            "error": parsed.reason,
            "reason": parsed.reason,
            "detail": parsed.detail,
            "supported_shapes": supported_shapes(),
        }

    seed = int(
        hashlib.sha256(
            f"{parsed.org}/{parsed.repo}/{session_id}".encode()
        ).hexdigest()[:12],
        16,
    )
    incident = generate_incident(parsed, seed)

    await record_session(session_id, request_body.repo_url, parsed, incident)

    return {
        "incident": incident,
        "parsed": {
            "host": parsed.host,
            "org": parsed.org,
            "repo": parsed.repo,
            "language_hint": parsed.language_hint,
        },
    }


@router.post("/reset")
async def demo_reset(response: Response):
    _require_demo_mode()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "reset"}
