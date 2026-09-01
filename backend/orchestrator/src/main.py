from fastapi import APIRouter, Request, HTTPException, Response
from src.config import settings
from src.services.incident_service import IncidentService
from loguru import logger
import json

router = APIRouter()

@router.post("/slack/events")
async def slack_events(request: Request):
    """Handle Slack events - including URL verification and commands"""
    try:
        # Get the raw body
        body = await request.body()
        body_str = body.decode('utf-8')
        
        logger.info(f"Raw Slack request: {body_str[:500]}")
        
        # Try to parse JSON
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {body_str[:200]}")
            return {"error": "invalid json"}
        
        # Handle URL verification challenge
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            logger.info(f"URL verification challenge: {challenge}")
            return {"challenge": challenge}
        
        # Handle slash command
        if data.get("command") == "/incident":
            logger.info(f"Slash command received: {data.get('text', '')}")
            
            # Parse command: /incident service-name "message"
            parts = data.get('text', '').split(' ', 1)
            service_name = parts[0] if parts else None
            message = parts[1] if len(parts) > 1 else "Incident reported"
            
            if not service_name:
                return {"text": "⚠️ Please specify a service: `/incident payment-api Failure detected`"}
            
            try:
                # Declare incident
                incident_service = IncidentService()
                result = await incident_service.declare_incident(
                    service_name=service_name,
                    message=message,
                    stack_trace=None
                )
                
                # Format response for Slack
                response_text = f"🚨 Incident {result['incident_id']} declared for {service_name}\n\n"
                response_text += f"*Severity:* {result['severity']}\n"
                response_text += f"*Root Cause:* {result['root_cause'][:300]}\n"
                response_text += f"*Suggested Fix:* {result['suggested_fix'][:200]}\n"
                response_text += f"*Rollback Command:* `{result['rollback_command']}`"
                
                return {"text": response_text}
                
            except Exception as e:
                logger.error(f"Error declaring incident: {e}")
                return {"text": f"❌ Failed to declare incident: {str(e)}"}
        
        # Handle other events
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Slack error: {e}")
        return {"error": str(e)}

@router.get("/slack/status")
async def slack_status():
    return {
        "status": "configured",
        "message": "Slack integration is ready",
        "bot_token": "✅ Set" if settings.SLACK_BOT_TOKEN else "❌ Missing"
    }
