from fastapi import APIRouter, Request, HTTPException, Response, BackgroundTasks
from src.config import settings
from src.services.incident_service import IncidentService
from loguru import logger
import json

router = APIRouter()

@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack events"""
    try:
        # Get raw body
        body = await request.body()
        body_str = body.decode('utf-8')
        
        # Log the FULL raw body for debugging
        logger.info(f"RAW SLACK REQUEST: {body_str}")
        
        # For Slack slash commands, the body might be form-encoded, not JSON!
        # Let's check content-type
        content_type = request.headers.get('content-type', '')
        logger.info(f"Content-Type: {content_type}")
        
        # If it's form-encoded, parse it differently
        if 'application/x-www-form-urlencoded' in content_type:
            # Parse form data
            from urllib.parse import parse_qs
            form_data = parse_qs(body_str)
            logger.info(f"Form data: {form_data}")
            
            # Convert to dict with string values
            data = {k: v[0] for k, v in form_data.items()}
            logger.info(f"Parsed form data: {data}")
            
            # Handle slash command
            if data.get('command') == '/incident':
                logger.info(f"Slash command: {data.get('text', '')}")
                background_tasks.add_task(process_slack_command, data=data)
                return Response(content='', media_type="application/json")
        
        # Try JSON parsing
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {body_str[:200]}")
            return Response(content='{"error":"invalid json"}', media_type="application/json")
        
        # Handle URL verification
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            logger.info(f"URL verification challenge: {challenge}")
            return {"challenge": challenge}
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Slack error: {e}")
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json")

async def process_slack_command(data: dict):
    """Process Slack slash command in background"""
    try:
        service_name = data.get('text', '').split(' ')[0] if data.get('text') else None
        message = data.get('text', '')[len(service_name)+1:] if service_name else "Incident reported"
        
        if not service_name:
            logger.warning("No service name provided")
            return
        
        logger.info(f"Processing: service={service_name}, message={message}")
        
        incident_service = IncidentService()
        result = await incident_service.declare_incident(
            service_name=service_name,
            message=message,
            stack_trace=None
        )
        
        response_url = data.get('response_url')
        if response_url:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={
                        "text": f"🚨 Incident {result['incident_id']} declared for {service_name}\n\n"
                                f"*Severity:* {result['severity']}\n"
                                f"*Root Cause:* {result['root_cause'][:300]}\n"
                                f"*Suggested Fix:* {result['suggested_fix'][:200]}\n"
                                f"*Rollback Command:* `{result['rollback_command']}`"
                    }
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
