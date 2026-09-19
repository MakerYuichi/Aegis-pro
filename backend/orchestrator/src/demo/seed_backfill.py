"""
Backfill embeddings for demo-seeded incidents.

Runs on startup when DEMO_MODE=true. Scopes the query to incidents with
extra_metadata->>'demo_seed' = 'true' so it never touches incidents a buyer
actually declared during a demo session.

Idempotent: only backfills where embedding IS NULL.
"""

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.database import get_db


async def backfill_demo_embeddings(rag_service) -> int:
    """
    Embed every demo-seeded incident that has no embedding yet.

    Returns the number of incidents embedded. Returns 0 when DEMO_MODE is
    false, when there is nothing to backfill, or when the DB query fails.
    """
    if not settings.DEMO_MODE:
        return 0

    try:
        session = await get_db()
        async with session:
            result = await session.execute(
                text(
                    """
                    SELECT incident_id, title, description, stack_trace
                    FROM incidents
                    WHERE embedding IS NULL
                      AND extra_metadata->>'demo_seed' = 'true'
                    """
                )
            )
            rows = result.fetchall()
    except Exception as e:
        logger.warning(f"⚠️ Demo embedding backfill query failed: {e}")
        return 0

    if not rows:
        logger.info("📚 Demo embedding backfill: 0 incidents to embed")
        return 0

    for row in rows:
        await rag_service.store_incident(
            {
                "incident_id": row[0],
                "title": row[1] or "",
                "description": row[2] or "",
                "stack_trace": row[3] or "",
            }
        )

    logger.info(f"📚 Demo embedding backfill: embedded {len(rows)} incidents")
    return len(rows)
