from fastapi import APIRouter, Request, HTTPException, Response, BackgroundTasks
from src.config import settings
from src.services.incident_service import IncidentService
from loguru import logger
import json

router = APIRouter()

@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack events - with immediate response"""
    try:
        # Get the raw body
        body = await request.body()
        body_str = body.decode('utf-8')
        
        logger.info(f"Slack request received (first 200 chars): {body_str[:200]}")
        
        # Try to parse JSON
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {body_str[:200]}")
            return Response(content='{"error":"invalid json"}', media_type="application/json")
        
        # Handle URL verification challenge
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            logger.info(f"URL verification challenge: {challenge}")
            return {"challenge": challenge}
        
        # Handle slash command - respond immediately
        if data.get("command") == "/incident":
            logger.info(f"Slash command: {data.get('text', '')}")
            
            # Send immediate acknowledgment
            background_tasks.add_task(
                process_slack_command,
                data=data
            )
            
            # Return empty response - Slack will wait for the webhook
            return Response(content='', media_type="application/json")
        
        # Handle other events
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Slack error: {e}")
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json")

async def process_slack_command(data: dict):
    """Process Slack slash command in background"""
    try:
        # Parse command: /incident service-name "message"
        parts = data.get('text', '').split(' ', 1)
        service_name = parts[0] if parts else None
        message = parts[1] if len(parts) > 1 else "Incident reported"
        
        if not service_name:
            logger.warning("No service name provided in Slack command")
            return
        
        # Declare incident
        incident_service = IncidentService()
        result = await incident_service.declare_incident(
            service_name=service_name,
            message=message,
            stack_trace=None
        )
        
        # Get the response URL from the request
        response_url = data.get('response_url')
        if response_url:
            # Send response via webhook
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": f"🚨 Incident {result['incident_id']} declared for {service_name}\n\n"
                                  f"*Severity:* {result['severity']}\n"
                                  f"*Root Cause:* {result['root_cause'][:300]}\n"
                                  f"*Suggested Fix:* {result['suggested_fix'][:200]}\n"
                                  f"*Rollback Command:* `{result['rollback_command']}`"}
                )
        else:
            logger.error("No response_url in Slack command")
            
    except Exception as e:
        logger.error(f"Error processing Slack command: {e}")

@router.get("/slack/status")
async def slack_status():
    return {
        "status": "configured",
        "message": "Slack integration is ready",
        "bot_token": "✅ Set" if settings.SLACK_BOT_TOKEN else "❌ Missing"
    }
