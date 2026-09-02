from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from src.services.incident_service import IncidentService
from src.services.github_service import GitHubService
from src.websocket import manager
from loguru import logger
import json
import httpx
from datetime import datetime

router = APIRouter()

@router.post("/webhook/alert")
async def auto_discover_incident(request: Request, background_tasks: BackgroundTasks):
    """
    Auto-detect incidents from monitoring tools (Prometheus, DataDog, etc.)
    """
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        logger.info(f"📨 Webhook alert received: {body_str[:500]}")
        
        # Parse the alert
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            return {"error": "invalid json"}
        
        # Extract alert details
        service_name = data.get('service') or data.get('service_name')
        message = data.get('message') or data.get('alert') or "Auto-detected incident"
        stack_trace = data.get('stack_trace') or data.get('error') or data.get('logs')
        
        if not service_name:
            return {"error": "missing service name"}
        
        logger.info(f"🔍 Auto-detected incident for service: {service_name}")
        
        # Auto-create incident
        incident_service = IncidentService()
        result = await incident_service.declare_incident(
            service_name=service_name,
            message=f"[Auto-Detected] {message}",
            stack_trace=stack_trace
        )
        
        logger.info(f"✅ Auto-created incident: {result['incident_id']}")
        
        # Broadcast via WebSocket
        await manager.broadcast({
            "type": "new_incident",
            "data": result,
            "auto_detected": True
        })
        
        # Notify via Slack (if configured)
        if data.get('notify_slack', True):
            background_tasks.add_task(notify_slack, result)
        
        return {
            "status": "created",
            "incident_id": result['incident_id'],
            "auto_detected": True
        }
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def notify_slack(incident: dict):
    """Send Slack notification for auto-detected incident"""
    try:
        # Check if Slack is configured
        from src.config import settings
        if not settings.SLACK_BOT_TOKEN:
            return
        
        # Build Slack message
        message = {
            "text": f"🚨 [AUTO-DETECTED] Incident {incident['incident_id']}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🚨 Auto-Detected Incident {incident['incident_id']}", "emoji": True}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Service:*\n{incident['service']}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{incident['severity']}"},
                        {"type": "mrkdwn", "text": f"*Root Cause:*\n{incident['root_cause'][:200]}"},
                        {"type": "mrkdwn", "text": f"*Confidence:*\n{(incident['confidence'] * 100):.0f}%"}
                    ]
                }
            ]
        }
        
        # Send to Slack
        webhook_url = f"https://hooks.slack.com/services/xxx/xxx/xxx"  # Configure this
        
        async with httpx.AsyncClient() as client:
            await client.post(webhook_url, json=message)
            
    except Exception as e:
        logger.error(f"Slack notification error: {e}")

@router.get("/webhook/status")
async def webhook_status():
    return {
        "status": "active",
        "endpoint": "/webhook/alert",
        "method": "POST",
        "auto_detection": "enabled",
        "supported_services": ["Prometheus", "DataDog", "Custom"]
    }
