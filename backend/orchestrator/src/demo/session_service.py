from datetime import datetime, timezone
from typing import Any, Optional
import json

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.database import get_db_session
from src.demo.repo_parser import ParseResult


RETENTION_DAYS = 30

# Successful analyses per session before the demo asks for signup.
# Failed parses and "not code" responses don't count against this — see
# count_successful_tries.
MAX_SUCCESSFUL_TRIES = 3


async def record_session(
    session_id: str,
    raw_input: str,
    parsed: ParseResult,
    incident_payload: Optional[dict[str, Any]] = None,
) -> None:
    """
    Log one /demo/generate call. Never raises — logging failures must not
    break the demo. If DEMO_MODE is off, this is a no-op.
    """
    if not settings.DEMO_MODE:
        return

    try:
        payload_json = json.dumps(incident_payload) if incident_payload else None
        incident_id = incident_payload.get("incident_id") if incident_payload else None

        async with get_db_session() as session:
            # Retention: delete old rows opportunistically. Cheap because
            # the table is small and the index is on created_at.
            await session.execute(
                text(
                    "DELETE FROM demo_sessions "
                    "WHERE created_at < NOW() - (:days || ' days')::interval"
                ),
                {"days": str(RETENTION_DAYS)},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO demo_sessions (
                        session_id, raw_input, parsed_org, parsed_repo,
                        language_inferred, parse_ok, error_reason,
                        incident_payload, incident_id
                    ) VALUES (
                        :session_id, :raw_input, :parsed_org, :parsed_repo,
                        :language_inferred, :parse_ok, :error_reason,
                        CAST(:incident_payload AS jsonb), :incident_id
                    )
                    """
                ),
                {
                    "session_id": session_id,
                    "raw_input": raw_input[:2000] if raw_input else None,
                    "parsed_org": parsed.org if parsed.ok else None,
                    "parsed_repo": parsed.repo if parsed.ok else None,
                    "language_inferred": parsed.language_hint if parsed.ok else None,
                    "parse_ok": parsed.ok,
                    "error_reason": parsed.reason if not parsed.ok else None,
                    "incident_payload": payload_json,
                    "incident_id": incident_id,
                },
            )
            await session.commit()
            logger.debug(f"📝 Demo session logged: {session_id} ok={parsed.ok}")
    except Exception as e:
        # Never let session logging break the demo.
        logger.warning(f"⚠️ Failed to record demo session: {e}")


async def count_successful_tries(session_id: str) -> int:
    if not settings.DEMO_MODE:
        return 0

    try:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM demo_sessions
                    WHERE session_id = :sid
                      AND parse_ok = true
                      AND incident_id IS NOT NULL
                    """
                ),
                {"sid": session_id},
            )
            return int(result.scalar() or 0)
    except Exception as e:
        logger.warning(f"⚠️ Failed to count demo tries: {e}")
        return 0

# ── Phase 10: demo-to-dashboard continuity ──────────────────────────────

async def link_to_user(session_id: str, email: str) -> bool:
    """
    Attach a signed-in user's email to their demo session.

    Idempotent — calling twice with the same (session_id, email) is a
    no-op. Calling with a different email overwrites: the same browser
    may be used by two people, and the last sign-in wins.

    Returns True if a row was updated, False if no row matched.
    Never raises — the dashboard card is non-essential, and a failed
    link must not break the sign-in flow.
    """
    if not settings.DEMO_MODE:
        return False
    if not email:
        return False

    try:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE demo_sessions
                    SET user_email = :email
                    WHERE session_id = :sid
                    """
                ),
                {"email": email.lower(), "sid": session_id},
            )
            await session.commit()
            matched = result.rowcount > 0
            if matched:
                logger.debug(f"🔗 Linked {session_id} to {email}")
            return matched
    except Exception as e:
        logger.warning(f"⚠️ Failed to link demo session {session_id}: {e}")
        return False


async def list_for_user(email: str, limit: int = 10) -> list[dict]:
    """
    Return this user's linked demo sessions, newest first.

    Only rows with parse_ok = true and a non-null parsed_org/parsed_repo
    are returned — those are the ones the dashboard card can act on.

    Never raises — returns [] on error.
    """
    if not settings.DEMO_MODE:
        return []
    if not email:
        return []

    try:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, session_id, parsed_org, parsed_repo,
                           language_inferred, incident_id, created_at
                    FROM demo_sessions
                    WHERE user_email = :email
                      AND parse_ok = true
                      AND parsed_org IS NOT NULL
                      AND parsed_repo IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"email": email.lower(), "limit": limit},
            )
            rows = result.fetchall()
            return [
                {
                    "id": r[0],
                    "session_id": r[1],
                    "parsed_org": r[2],
                    "parsed_repo": r[3],
                    "language_inferred": r[4],
                    "incident_id": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning(f"⚠️ Failed to list demo sessions for {email}: {e}")
        return []


async def mark_onboarding_interest(email: str, session_id: str | None) -> bool:
    """
    Record that a user clicked "Connect it now" for their demo session.

    Writes onboarding_clicked_at on the matching row. If session_id is
    None, marks the user's most recent linked session instead — that's
    the one the dashboard card was showing.

    Never raises — the click is a lead signal, not a transactional
    requirement.
    """
    if not settings.DEMO_MODE:
        return False
    if not email:
        return False

    try:
        async with get_db_session() as session:
            if session_id:
                result = await session.execute(
                    text(
                        """
                        UPDATE demo_sessions
                        SET onboarding_clicked_at = NOW()
                        WHERE session_id = :sid
                          AND user_email = :email
                        """
                    ),
                    {"sid": session_id, "email": email.lower()},
                )
            else:
                result = await session.execute(
                    text(
                        """
                        UPDATE demo_sessions
                        SET onboarding_clicked_at = NOW()
                        WHERE id = (
                            SELECT id FROM demo_sessions
                            WHERE user_email = :email
                              AND parse_ok = true
                              AND parsed_org IS NOT NULL
                            ORDER BY created_at DESC
                            LIMIT 1
                        )
                        """
                    ),
                    {"email": email.lower()},
                )
            await session.commit()
            matched = result.rowcount > 0
            if matched:
                logger.info(f"📩 Onboarding interest recorded for {email}")
            return matched
    except Exception as e:
        logger.warning(f"⚠️ Failed to record onboarding interest for {email}: {e}")
        return False
