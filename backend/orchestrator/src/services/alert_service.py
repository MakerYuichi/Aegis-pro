from typing import Optional
from loguru import logger
from src.services.slack_service import SlackService
from src.services.oncall_service import OnCallService

class AlertService:
    def __init__(self):
        self.slack = SlackService()
        self.oncall = OnCallService()
        logger.info("✅ AlertService initialized (Slack only)")

    def _engineer_list(self, on_call: Optional[dict]) -> list:
        if not on_call or on_call.get("error"):
            return []
        people = []
        for role in ("primary", "secondary", "tertiary"):
            person = on_call.get(role)
            if person:
                people.append({**person, "role": role})
        return people

    async def send_alerts(self, incident_data: dict, on_call: Optional[dict], escalation: Optional[list] = None) -> dict:
        """Page on-call for a declared incident (Slack only)."""
        incident_id = incident_data.get("incident_id", "unknown")
        title = incident_data.get("title") or incident_data.get("message") or "Incident declared"
        severity = incident_data.get("severity", "P1")
        service_name = incident_data.get("service_name", "unknown")

        recipients = self._engineer_list(on_call)
        if not recipients and escalation:
            for step in escalation:
                recipients.append({
                    "name": step.get("engineer"),
                    "slack": step.get("slack"),
                    "email": step.get("email"),
                    "phone": step.get("phone"),
                    "role": f"escalation-{step.get('level')}",
                })

        text = (
            f"🚨 *{severity}* incident `{incident_id}` on *{service_name}*\n"
            f"{title}\n"
            f"On-call: {', '.join(p.get('slack') or p.get('name') or 'unknown' for p in recipients) or 'none registered'}"
        )

        results = []
        for person in recipients:
            results.append(await self.alert_person(
                slack_handle=person.get("slack") or person.get("name"),
                message=text,
                incident_id=incident_id,
                channel="incident",
            ))

        if not recipients:
            results.append(await self.alert_person(
                slack_handle="#incidents",
                message=text,
                incident_id=incident_id,
                channel="incident",
            ))

        logger.info(f"📢 Alerts dispatched for {incident_id} to {len(recipients)} on-call engineer(s)")
        return {
            "status": "sent",
            "recipients": [p.get("slack") or p.get("name") for p in recipients],
            "slack": results,
        }

    async def alert_person(
        self,
        slack_handle: str,
        message: str,
        incident_id: Optional[str] = None,
        channel: str = "direct",
    ) -> dict:
        """Send an alert to a specific Slack handle or channel."""
        handle = slack_handle or "unknown"
        payload = {
            "text": message,
            "channel": handle,
            "username": "AEGIS PRO",
        }
        sent = await self.slack.send_message(payload)
        logger.info(f"📣 Alert to {handle} ({channel}) incident={incident_id} sent={sent}")
        return {
            "status": "sent" if sent else "failed",
            "target": handle,
            "incident_id": incident_id,
            "mock": not self.slack.enabled,
        }

    async def alert_everyone(self, message: str, service_name: Optional[str] = None) -> dict:
        """Page every active on-call engineer, optionally scoped to a service."""
        roster = await self.oncall.list_roster(service_name)
        unique = {}
        for person in roster:
            key = person.get("slack_handle") or person.get("name")
            if key:
                unique[key] = person

        results = []
        for handle, person in unique.items():
            results.append(await self.alert_person(
                slack_handle=handle,
                message=message,
                channel="broadcast",
            ))

        return {
            "status": "sent",
            "count": len(results),
            "targets": list(unique.keys()),
            "results": results,
        }
