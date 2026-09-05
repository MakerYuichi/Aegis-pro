import asyncio
import sys
sys.path.insert(0, "/app")
from src.database import get_db
from src.models import Incident
from sqlalchemy import select, update
from loguru import logger

async def fix_update_method():
    try:
        session = await get_db()
        try:
            # Test if update works
            result = await session.execute(
                update(Incident)
                .where(Incident.incident_id == "INC-20260905-68E54D")
                .values(extra_metadata={"test": "test"})
                .returning(Incident.incident_id)
            )
            await session.commit()
            row = result.fetchone()
            if row:
                logger.info(f"✅ Update works! Found: {row[0]}")
            else:
                logger.error("❌ Update failed - incident not found")
        except Exception as e:
            logger.error(f"❌ Error: {e}")
        finally:
            await session.close()
    except Exception as e:
        logger.error(f"❌ Session error: {e}")

asyncio.run(fix_update_method())
