from typing import Optional
from sqlalchemy import text
from src.database import get_db
from loguru import logger
import json


class OnCallService:
    def __init__(self):
        logger.info("✅ OnCallService initialized")

    def _row_to_person(self, row) -> dict:
        return {
            "id": row[0],
            "service_name": row[1],
            "name": row[2],
            "slack_handle": row[3],
            "email": row[4],
            "phone": row[5],
            "role": row[6],
            "is_active": row[7] if len(row) > 7 else True,
        }

    async def get_on_call(self, service_name: str) -> dict:
        """Get current on-call engineers for a service."""
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("""
                        SELECT
                            id,
                            service_name,
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
                    return await self._fallback_from_service(service_name)

                on_call = {"primary": None, "secondary": None, "tertiary": None}
                for row in rows:
                    person = {
                        "id": row[0],
                        "name": row[2],
                        "slack": row[3],
                        "email": row[4],
                        "phone": row[5],
                    }
                    if row[6] in on_call:
                        on_call[row[6]] = person
                return on_call

        except Exception as e:
            logger.error(f"Error getting on-call: {e}")
            return await self._fallback_from_service(service_name)

    async def _fallback_from_service(self, service_name: str) -> dict:
        try:
            session = await get_db()
            async with session:
                result = await session.execute(
                    text("SELECT on_call FROM services WHERE name = :name"),
                    {"name": service_name}
                )
                row = result.fetchone()
                handles = []
                if row and row[0]:
                    handles = row[0] if isinstance(row[0], list) else json.loads(row[0])
                roles = ["primary", "secondary", "tertiary"]
                on_call = {"primary": None, "secondary": None, "tertiary": None}
                for i, handle in enumerate(handles[:3]):
                    on_call[roles[i]] = {
                        "name": handle,
                        "slack": handle,
                        "email": None,
                        "phone": None,
                    }
                if not handles:
                    return {"error": f"No on-call schedule found for {service_name}"}
                return on_call
        except Exception as e:
            logger.error(f"On-call fallback error: {e}")
            return {"error": str(e)}

    async def list_roster(self, service_name: Optional[str] = None) -> list:
        """List on-call people, optionally filtered by service."""
        try:
            session = await get_db()
            async with session:
                if service_name:
                    result = await session.execute(
                        text("""
                            SELECT id, service_name, engineer_name, slack_handle, email, phone, role, is_active
                            FROM oncall_rotations
                            WHERE is_active = TRUE AND service_name = :service_name
                            ORDER BY service_name,
                                CASE role WHEN 'primary' THEN 1 WHEN 'secondary' THEN 2 WHEN 'tertiary' THEN 3 ELSE 4 END
                        """),
                        {"service_name": service_name}
                    )
                else:
                    result = await session.execute(
                        text("""
                            SELECT id, service_name, engineer_name, slack_handle, email, phone, role, is_active
                            FROM oncall_rotations
                            WHERE is_active = TRUE
                            ORDER BY service_name,
                                CASE role WHEN 'primary' THEN 1 WHEN 'secondary' THEN 2 WHEN 'tertiary' THEN 3 ELSE 4 END
                        """)
                    )
                rows = result.fetchall()
                if rows:
                    return [self._row_to_person(row) for row in rows]
        except Exception as e:
            logger.error(f"Error listing on-call roster: {e}")

        return await self._roster_from_services(service_name)

    async def _roster_from_services(self, service_name: Optional[str] = None) -> list:
        try:
            session = await get_db()
            async with session:
                if service_name:
                    result = await session.execute(
                        text("SELECT name, on_call FROM services WHERE name = :name"),
                        {"name": service_name}
                    )
                else:
                    result = await session.execute(text("SELECT name, on_call FROM services ORDER BY name"))
                roster = []
                roles = ["primary", "secondary", "tertiary"]
                for row in result.fetchall():
                    handles = row[1] if isinstance(row[1], list) else (json.loads(row[1]) if row[1] else [])
                    for i, handle in enumerate(handles):
                        roster.append({
                            "id": f"{row[0]}-{handle}",
                            "service_name": row[0],
                            "name": handle.lstrip("@").title() if isinstance(handle, str) else str(handle),
                            "slack_handle": handle,
                            "email": None,
                            "phone": None,
                            "role": roles[i] if i < 3 else "secondary",
                            "is_active": True,
                        })
                return roster
        except Exception as e:
            logger.error(f"Roster from services error: {e}")
            return []

    async def add_member(self, member: dict) -> dict:
        session = await get_db()
        async with session:
            result = await session.execute(
                text("""
                    INSERT INTO oncall_rotations
                        (service_name, engineer_name, slack_handle, email, phone, role, is_active)
                    VALUES
                        (:service_name, :engineer_name, :slack_handle, :email, :phone, :role, TRUE)
                    RETURNING id
                """),
                {
                    "service_name": member["service_name"],
                    "engineer_name": member["name"],
                    "slack_handle": member.get("slack_handle") or f"@{member['name'].split()[0].lower()}",
                    "email": member.get("email"),
                    "phone": member.get("phone"),
                    "role": member.get("role") or "secondary",
                }
            )
            member_id = result.scalar()
            await session.execute(
                text("""
                    UPDATE services
                    SET on_call = (
                        SELECT COALESCE(jsonb_agg(DISTINCT handle), '[]'::jsonb)
                        FROM (
                            SELECT jsonb_array_elements_text(COALESCE(on_call, '[]'::jsonb)) AS handle
                            FROM services WHERE name = :service_name
                            UNION
                            SELECT :slack_handle
                        ) handles
                    )
                    WHERE name = :service_name
                """),
                {
                    "service_name": member["service_name"],
                    "slack_handle": member.get("slack_handle") or f"@{member['name'].split()[0].lower()}",
                }
            )
            await session.commit()
            return {"id": member_id, "status": "created"}

    async def remove_member(self, member_id: int) -> dict:
        session = await get_db()
        async with session:
            await session.execute(
                text("UPDATE oncall_rotations SET is_active = FALSE WHERE id = :id"),
                {"id": member_id}
            )
            await session.commit()
            return {"id": member_id, "status": "removed"}

    async def get_escalation_policy(self, service_name: str, severity: str) -> list:
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
