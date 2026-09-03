from sqlalchemy import text
from src.database import get_db
from loguru import logger
from datetime import datetime

class OnCallService:
    def __init__(self):
        logger.info("✅ OnCallService initialized")
    
    async def get_on_call(self, service_name: str) -> dict:
        """Get current on-call engineers for a service"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT 
                            engineer_name,
                            slack_handle,
                            email,
                            phone,
                            role,
                            is_active
                        FROM oncall_rotations
                        WHERE service_name = :service_name
                        AND is_active = TRUE
                        ORDER BY 
                            CASE role
                                WHEN 'primary' THEN 1
                                WHEN 'secondary' THEN 2
                                WHEN 'tertiary' THEN 3
                                ELSE 4
                            END
                    """),
                    {"service_name": service_name}
                )
                rows = result.fetchall()
                
                if not rows:
                    return {"error": f"No on-call schedule found for {service_name}"}
                
                on_call = {
                    "primary": None,
                    "secondary": None,
                    "tertiary": None
                }
                
                for row in rows:
                    if row[4] == 'primary':
                        on_call["primary"] = {
                            "name": row[0],
                            "slack": row[1],
                            "email": row[2],
                            "phone": row[3]
                        }
                    elif row[4] == 'secondary':
                        on_call["secondary"] = {
                            "name": row[0],
                            "slack": row[1],
                            "email": row[2],
                            "phone": row[3]
                        }
                    elif row[4] == 'tertiary':
                        on_call["tertiary"] = {
                            "name": row[0],
                            "slack": row[1],
                            "email": row[2],
                            "phone": row[3]
                        }
                
                return on_call
                
        except Exception as e:
            logger.error(f"Error getting on-call: {e}")
            return {"error": str(e)}
    
    async def get_escalation_policy(self, service_name: str, severity: str) -> list:
        """Get escalation policy for a service and severity"""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT 
                            escalation_level,
                            engineer_name,
                            slack_handle,
                            email,
                            phone,
                            wait_time_minutes
                        FROM escalation_policies
                        WHERE service_name = :service_name
                        AND severity = :severity
                        ORDER BY escalation_level ASC
                    """),
                    {"service_name": service_name, "severity": severity}
                )
                rows = result.fetchall()
                
                return [
                    {
                        "level": row[0],
                        "engineer": row[1],
                        "slack": row[2],
                        "email": row[3],
                        "phone": row[4],
                        "wait_time": row[5]
                    }
                    for row in rows
                ]
                
        except Exception as e:
            logger.error(f"Error getting escalation policy: {e}")
            return []
