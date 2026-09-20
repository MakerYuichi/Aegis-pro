from datetime import datetime, timezone
from typing import Any, Optional
import json

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.database import get_db
from src.demo.repo_parser import ParseResult


RETENTION_DAYS = 30


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

        session = await get_db()
        async with session:
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
