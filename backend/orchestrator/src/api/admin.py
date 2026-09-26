"""
Admin endpoints — demo session activity, stats, and replay.

All routes require an authenticated user whose email is in ADMIN_EMAILS.
See src/auth.py::require_admin for the access check.

The data source is the demo_sessions table, written by /api/v1/demo/generate
and /api/v1/demo/regenerate. See database/migrations/006_create_demo_sessions.sql.

Auth failures return 403 (not 404) so the frontend can distinguish
"you're not an admin" from "this endpoint doesn't exist."
"""
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.auth import require_admin
from src.database import get_db_session
from sqlalchemy import text


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me")
async def admin_me(claims: dict = Depends(require_admin)):
    """
    Confirm the caller is an admin. The frontend calls this once after
    login to decide whether to show the admin navbar link.

    Returns 403 for non-admins (via require_admin). A 200 means admin.
    """
    email = claims.get("email") or claims.get("https://aegis-pro/email") or ""
    return {"is_admin": True, "email": email}


@router.get("/demo-sessions")
async def list_demo_sessions(
    limit: int = 50,
    claims: dict = Depends(require_admin),
):
    """
    Recent demo sessions, newest first.

    This is the lead signal: which orgs pasted a URL, which parsed, which
    failed and why. One row per /demo/generate or /demo/regenerate call.
    """
    limit = max(1, min(limit, 500))

    async with get_db_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, session_id, raw_input, parsed_org, parsed_repo,
                       language_inferred, parse_ok, error_reason,
                       incident_id, created_at, last_seen_at
                FROM demo_sessions
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        rows = result.fetchall()

    return {
        "sessions": [
            {
                "id": row[0],
                "session_id": row[1],
                "raw_input": row[2],
                "parsed_org": row[3],
                "parsed_repo": row[4],
                "language_inferred": row[5],
                "parse_ok": row[6],
                "error_reason": row[7],
                "incident_id": row[8],
                "created_at": row[9].isoformat() if row[9] else None,
                "last_seen_at": row[10].isoformat() if row[10] else None,
            }
            for row in rows
        ],
        "count": len(rows),
        "limit": limit,
    }


@router.get("/demo-stats")
async def demo_stats(
    days: int = 30,
    claims: dict = Depends(require_admin),
):
    """
    Aggregate demo activity over a trailing window.

    Returns total sessions, sessions by day, top orgs pasted, and a
    breakdown of parse failures by reason. The parse-failure breakdown
    is the product signal: if unsupported_host dominates, add support
    for that host.
    """
    days = max(1, min(days, 365))

    async with get_db_session() as session:
        total = (await session.execute(
            text(
                """
                SELECT COUNT(*) FROM demo_sessions
                WHERE created_at >= NOW() - make_interval(days => :days)
                """
            ),
            {"days": days},
        )).scalar() or 0

        by_day_rows = (await session.execute(
            text(
                """
                SELECT DATE(created_at) AS day, COUNT(*)
                FROM demo_sessions
                WHERE created_at >= NOW() - make_interval(days => :days)
                GROUP BY day
                ORDER BY day DESC
                """
            ),
            {"days": days},
        )).fetchall()

        top_orgs_rows = (await session.execute(
            text(
                """
                SELECT parsed_org, COUNT(*) AS n
                FROM demo_sessions
                WHERE created_at >= NOW() - make_interval(days => :days)
                  AND parsed_org IS NOT NULL
                GROUP BY parsed_org
                ORDER BY n DESC
                LIMIT 20
                """
            ),
            {"days": days},
        )).fetchall()

        failure_rows = (await session.execute(
            text(
                """
                SELECT error_reason, COUNT(*) AS n
                FROM demo_sessions
                WHERE created_at >= NOW() - make_interval(days => :days)
                  AND parse_ok = false
                  AND error_reason IS NOT NULL
                GROUP BY error_reason
                ORDER BY n DESC
                """
            ),
            {"days": days},
        )).fetchall()

        failure_total = sum(row[1] for row in failure_rows)

    return {
        "window_days": days,
        "total_sessions": total,
        "sessions_by_day": [
            {"date": row[0].isoformat(), "count": row[1]} for row in by_day_rows
        ],
        "top_orgs": [
            {"org": row[0], "count": row[1]} for row in top_orgs_rows
        ],
        "parse_failures": {
            "total": failure_total,
            "by_reason": [
                {"reason": row[0], "count": row[1]} for row in failure_rows
            ],
        },
    }


@router.get("/demo-sessions/{session_id}")
async def demo_session_detail(
    session_id: str,
    claims: dict = Depends(require_admin),
):
    """
    Full replay of one session.

    A session can contain multiple calls (the buyer pastes a URL, gets
    an incident, then uses the file dropdown to regenerate). This returns
    every call in order, with the decoded incident payload so an operator
    can see exactly what the buyer saw.
    """
    async with get_db_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, raw_input, parsed_org, parsed_repo,
                       language_inferred, parse_ok, error_reason,
                       incident_payload, incident_id, created_at
                FROM demo_sessions
                WHERE session_id = :sid
                ORDER BY created_at ASC
                """
            ),
            {"sid": session_id},
        )
        rows = result.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")

    calls = [
        {
            "id": row[0],
            "raw_input": row[1],
            "parsed_org": row[2],
            "parsed_repo": row[3],
            "language_inferred": row[4],
            "parse_ok": row[5],
            "error_reason": row[6],
            "incident_payload": row[7],
            "incident_id": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
        }
        for row in rows
    ]

    return {
        "session_id": session_id,
        "first_seen": calls[0]["created_at"],
        "last_seen": calls[-1]["created_at"],
        "call_count": len(calls),
        "calls": calls,
    }
