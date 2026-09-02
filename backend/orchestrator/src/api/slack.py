from fastapi import APIRouter, Request, Response, BackgroundTasks
from src.config import settings
from src.services.incident_service import IncidentService
from src.websocket import manager
from loguru import logger
import json
import httpx
from urllib.parse import parse_qs
from datetime import datetime

router = APIRouter()

async def send_slack_response(response_url: str, payload: dict):
    """Send response to Slack via webhook"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(response_url, json=payload)
    except Exception as e:
        logger.error(f"Error sending Slack response: {e}")

@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        logger.info(f"Slack request: {body_str[:300]}")
        
        # Handle URL verification
        if 'challenge' in body_str and 'url_verification' in body_str:
            data = json.loads(body_str)
            return {"challenge": data.get("challenge")}
        
        # Handle interactive actions (button clicks)
        if 'payload' in body_str:
            data = json.loads(parse_qs(body_str)['payload'][0])
            logger.info(f"Interactive action: {data}")
            
            if data.get('type') == 'block_actions':
                action = data['actions'][0]
                action_id = action.get('action_id')
                incident_id = action.get('value')
                user_name = data.get('user', {}).get('username', 'Unknown')
                
                # Broadcast activity to WebSocket
                activity = {
                    "type": "activity",
                    "action": action_id,
                    "incident_id": incident_id,
                    "user": user_name,
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": f"@{user_name} {action_id.replace('_', ' ')} incident {incident_id}"
                }
                
                if action_id == 'rollback':
                    background_tasks.add_task(handle_rollback, data=data, incident_id=incident_id, user=user_name)
                elif action_id == 'view_details':
                    background_tasks.add_task(handle_view_details, data=data, incident_id=incident_id, user=user_name)
                elif action_id == 'acknowledge':
                    background_tasks.add_task(handle_acknowledge, data=data, incident_id=incident_id, user=user_name)
                
                return Response(content='', media_type="application/json")
        
        # Handle slash command
        if 'command' in body_str:
            form_data = parse_qs(body_str)
            data = {k: v[0] for k, v in form_data.items()}
            
            if data.get('command') == '/incident':
                logger.info(f"Slash command: {data.get('text')}")
                background_tasks.add_task(process_incident_command, data=data)
                return Response(content='', media_type="application/json")
        
        return Response(content='{"status":"ok"}', media_type="application/json")
        
    except Exception as e:
        logger.error(f"Slack error: {e}")
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json")

async def process_incident_command(data: dict):
    try:
        text = data.get('text', '')
        parts = text.split(' ', 1)
        service_name = parts[0] if parts else None
        message = parts[1] if len(parts) > 1 else "Incident reported"
        user_name = data.get('user_name', 'Unknown')  # Get Slack user
        
        if not service_name:
            await send_slack_response(data.get('response_url'), {
                "text": "⚠️ Please specify a service: `/incident payment-api Failure detected`"
            })
            return
        
        incident_service = IncidentService()
        result = await incident_service.declare_incident(
            service_name=service_name,
            message=message,
            stack_trace=None,
            reported_by=user_name  # Pass user name
        )
        
        # Broadcast incident creation
        await manager.broadcast({
            "type": "new_incident",
            "data": result
        })
        
        blocks = build_incident_blocks(result)
        await send_slack_response(data.get('response_url'), {
            "blocks": blocks,
            "text": f"🚨 Incident {result['incident_id']}"
        })
        
    except Exception as e:
        logger.error(f"Error processing command: {e}")

async def handle_rollback(data: dict, incident_id: str, user: str):
    try:
        incident_service = IncidentService()
        result = await incident_service.rollback(incident_id)
        
        await manager.broadcast({
            "type": "activity",
            "action": "rollback",
            "incident_id": incident_id,
            "user": user,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"@{user} rolled back incident {incident_id}"
        })
        
        response_url = data.get('response_url')
        if response_url:
            await send_slack_response(response_url, {
                "text": f"✅ Rollback initiated for {incident_id} by @{user}"
            })
    except Exception as e:
        logger.error(f"Rollback error: {e}")

async def handle_view_details(data: dict, incident_id: str, user: str):
    try:
        incident_service = IncidentService()
        incident = await incident_service.get_incident(incident_id)
        
        await manager.broadcast({
            "type": "activity",
            "action": "view_details",
            "incident_id": incident_id,
            "user": user,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"@{user} viewed incident {incident_id}"
        })
        
        response_url = data.get('response_url')
        if response_url and incident:
            blocks = build_detail_blocks(incident)
            await send_slack_response(response_url, {"blocks": blocks})
    except Exception as e:
        logger.error(f"View details error: {e}")

async def handle_acknowledge(data: dict, incident_id: str, user: str):
    try:
        await manager.broadcast({
            "type": "activity",
            "action": "acknowledge",
            "incident_id": incident_id,
            "user": user,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"@{user} acknowledged incident {incident_id}"
        })
        
        response_url = data.get('response_url')
        if response_url:
            await send_slack_response(response_url, {
                "text": f"👋 @{user} acknowledged incident {incident_id}"
            })
    except Exception as e:
        logger.error(f"Acknowledge error: {e}")

def build_incident_blocks(result: dict) -> list:
    severity_color = {"P0": "#FF4444", "P1": "#FF8800", "P2": "#FFCC00"}.get(result['severity'], "#808080")
    
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 Incident {result['incident_id']}", "emoji": True}
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service:*\n{result['service']}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{result['severity']}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{(result['confidence'] * 100):.0f}%"},
                {"type": "mrkdwn", "text": f"*On Call:*\n{', '.join(result['on_call'])}"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🧠 Root Cause:*\n{result['root_cause'][:500]}"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔧 Suggested Fix:*\n{result['suggested_fix'][:500]}"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📋 Rollback:*\n`{result['rollback_command']}`"}
        }
    ]
    
    if result.get('blast_radius'):
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"💥 Blast Radius: {result['blast_radius']['count']} services affected\n{', '.join(result['blast_radius']['affected'])}"}]
        })
    
    if result.get('rag_context_used'):
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "🧠 AI used similar past incidents for analysis"}]
        })
    
    # --- NEW: Git Blame and PR Info ---
    extra_metadata = result.get('extra_metadata', {})
    if extra_metadata and isinstance(extra_metadata, dict):
        github = extra_metadata.get('github')
        if github and github.get('blame'):
            blame = github['blame']
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*👤 Git Blame:*\nLine {blame.get('line', '?')} in `{blame.get('file', 'unknown')}`\nLast changed by *{blame.get('author', 'Unknown')}*"
                }
            })
            if blame.get('pr_number'):
                blocks.append({
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"🔗 PR #{blame['pr_number']}: {blame.get('pr_title', '')} (by {blame.get('pr_author', 'Unknown')})"
                    }]
                })
    
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔧 Rollback Now", "emoji": True},
                "style": "danger",
                "action_id": "rollback",
                "value": result['incident_id']
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📋 View Details", "emoji": True},
                "action_id": "view_details",
                "value": result['incident_id']
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "👋 Acknowledge", "emoji": True},
                "style": "primary",
                "action_id": "acknowledge",
                "value": result['incident_id']
            }
        ]
    })
    
    return blocks

def build_detail_blocks(incident: dict) -> list:
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📋 Incident {incident['incident_id']} Details", "emoji": True}
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service:*\n{incident['service_name']}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{incident['severity']}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{incident['status']}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{(incident['confidence_score'] * 100):.0f}%"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Title:*\n{incident['title']}"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🧠 Root Cause:*\n{incident['root_cause'][:1000]}"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔧 Suggested Fix:*\n{incident['suggested_fix'][:1000]}"}
        }
    ]
    
    if incident.get('stack_trace'):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Stack Trace:*\n```{incident['stack_trace'][:500]}```"}
        })
    
    if incident.get('affected_services'):
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"💥 Affected: {', '.join(incident['affected_services'])}"}]
        })
    
    # --- NEW: Git Blame and PR Info in Details ---
    extra_metadata = incident.get('extra_metadata', {})
    if extra_metadata and isinstance(extra_metadata, dict):
        github = extra_metadata.get('github')
        if github and github.get('blame'):
            blame = github['blame']
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*👤 Git Blame:*\nLine {blame.get('line', '?')} in `{blame.get('file', 'unknown')}`\nLast changed by *{blame.get('author', 'Unknown')}*\nCommit: `{blame.get('commit_hash', '')}`"
                }
            })
            if blame.get('pr_number'):
                blocks.append({
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"🔗 PR #{blame['pr_number']}: {blame.get('pr_title', '')} (by {blame.get('pr_author', 'Unknown')})"
                    }]
                })
    
    return blocks

@router.get("/slack/status")
async def slack_status():
    return {
        "status": "configured",
        "bot_token": "✅ Set" if settings.SLACK_BOT_TOKEN else "❌ Missing"
    }
