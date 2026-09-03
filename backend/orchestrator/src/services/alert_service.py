from loguru import logger
from src.services.slack_service import SlackService
from src.services.twilio_service import TwilioService

class AlertService:
    def __init__(self):
        self.slack = SlackService()
        self.twilio = TwilioService()
        logger.info("✅ AlertService initialized")
    
    async def send_alerts(self, incident: dict, on_call: dict, escalation: list = None) -> dict:
        severity = incident.get('severity', 'P1')
        service_name = incident.get('service_name', 'unknown')
        incident_id = incident.get('incident_id', 'unknown')
        
        alerts_sent = []
        primary = on_call.get('primary') if on_call else {}
        secondary = on_call.get('secondary') if on_call else {}
        
        if severity == 'P0':
            logger.info(f"🚨 P0 Incident {incident_id}: Sending CRITICAL alerts")
            
            # 1. Slack alert
            slack_msg = self._build_slack_message(incident, urgent=True)
            await self.slack.send_message(slack_msg)
            alerts_sent.append({"channel": "slack", "type": "urgent"})
            
            # 2. SMS to primary (mock or real)
            if primary and primary.get('phone'):
                sms_msg = f"🚨 P0 ALERT: {incident.get('title', 'Unknown')} - {service_name}"
                await self.twilio.send_sms(primary['phone'], sms_msg)
                alerts_sent.append({"channel": "sms", "recipient": primary.get('name', 'Unknown')})
            else:
                logger.info(f"📱 [MOCK] SMS would go to: {primary.get('name', 'No one')} (no phone configured)")
                alerts_sent.append({"channel": "sms", "recipient": primary.get('name', 'No phone configured'), "mock": True})
            
            # 3. Phone call to primary (mock or real)
            if primary and primary.get('phone'):
                call_msg = f"Critical incident {incident_id} in {service_name}. Severity P0. Please check Slack immediately."
                await self.twilio.make_call(primary['phone'], call_msg)
                alerts_sent.append({"channel": "phone_call", "recipient": primary.get('name', 'Unknown')})
            else:
                logger.info(f"📞 [MOCK] Call would go to: {primary.get('name', 'No one')} (no phone configured)")
                alerts_sent.append({"channel": "phone_call", "recipient": primary.get('name', 'No phone configured'), "mock": True})
            
        elif severity == 'P1':
            logger.info(f"⚠️ P1 Incident {incident_id}: Sending HIGH alerts")
            
            # 1. Slack alert
            slack_msg = self._build_slack_message(incident, urgent=False)
            await self.slack.send_message(slack_msg)
            alerts_sent.append({"channel": "slack", "type": "standard"})
            
            # 2. SMS to primary (mock or real)
            if primary and primary.get('phone'):
                sms_msg = f"⚠️ P1: {incident.get('title', 'Unknown')} - {service_name}"
                await self.twilio.send_sms(primary['phone'], sms_msg)
                alerts_sent.append({"channel": "sms", "recipient": primary.get('name', 'Unknown')})
            else:
                logger.info(f"📱 [MOCK] SMS would go to: {primary.get('name', 'No one')}")
                alerts_sent.append({"channel": "sms", "recipient": primary.get('name', 'No phone configured'), "mock": True})
            
        else:
            logger.info(f"ℹ️ P2 Incident {incident_id}: Sending LOW alerts")
            slack_msg = self._build_slack_message(incident, urgent=False)
            await self.slack.send_message(slack_msg)
            alerts_sent.append({"channel": "slack", "type": "standard"})
        
        return {
            "status": "alerts_sent",
            "severity": severity,
            "alerts": alerts_sent,
            "primary_on_call": primary.get('name') if primary else None,
            "mock_mode": not any([
                self.slack.enabled,
                self.twilio.enabled
            ])
        }
    
    def _build_slack_message(self, incident: dict, urgent: bool = False) -> dict:
        severity_emoji = {'P0': '🚨', 'P1': '⚠️', 'P2': 'ℹ️'}.get(incident.get('severity', 'P1'), '🔔')
        urgency_text = " @here" if urgent else ""
        
        return {
            "text": f"{severity_emoji} {incident.get('severity', 'P1')} Incident {incident.get('incident_id', 'Unknown')}{urgency_text}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{severity_emoji} {incident.get('severity', 'P1')} Incident {incident.get('incident_id', 'Unknown')}"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Service:*\n{incident.get('service_name', 'Unknown')}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{incident.get('severity', 'P1')}"},
                        {"type": "mrkdwn", "text": f"*Root Cause:*\n{incident.get('root_cause', 'Unknown')[:200]}"},
                        {"type": "mrkdwn", "text": f"*Rollback Command:*\n`{incident.get('rollback_command', 'N/A')}`"}
                    ]
                }
            ]
        }
