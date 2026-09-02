from fastapi import APIRouter, Request, HTTPException
from src.services.incident_service import IncidentService
from src.websocket import manager
from loguru import logger
import json

router = APIRouter()

@router.post("/webhook/incident")
async def webhook_incident(request: Request):
    """
    Webhook endpoint for external monitoring tools
    Accepts alerts from Prometheus, DataDog, etc.
    """
    try:
        # Get raw body
        body = await request.body()
        body_str = body.decode('utf-8')
        logger.info(f"📨 Webhook received: {body_str[:500]}")
        
        # Parse JSON
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {body_str[:200]}")
            return {"error": "invalid json"}
        
        # Extract incident data
        service_name = data.get('service_name')
        message = data.get('message')
        stack_trace = data.get('stack_trace')
        
        if not service_name or not message:
            return {"error": "missing required fields: service_name, message"}
        
        # Create incident
        incident_service = IncidentService()
        result = await incident_service.declare_incident(
            service_name=service_name,
            message=message,
            stack_trace=stack_trace
        )
        
        logger.info(f"✅ Webhook created incident: {result['incident_id']}")
        
        # Broadcast via WebSocket
        await manager.broadcast({
            "type": "new_incident",
            "data": result
        })
        
        return {
            "status": "created",
            "incident_id": result['incident_id']
        }
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/webhook/status")
async def webhook_status():
    """Check webhook endpoint status"""
    return {
        "status": "active",
        "endpoint": "/webhook/incident",
        "method": "POST",
        "format": "JSON",
        "fields": ["service_name", "message", "stack_trace(optional)"]
    }
