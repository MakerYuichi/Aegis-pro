from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class DeclareIncidentRequest(BaseModel):
    service_name: str
    message: str
    stack_trace: Optional[str] = None

class RollbackRequest(BaseModel):
    incident_id: str

@router.get("/ping")
async def ping():
    return {"message": "pong", "status": "alive"}

@router.post("/incident/declare")
async def declare_incident(request: DeclareIncidentRequest, req: Request):
    """Declare a new incident"""
    service = req.app.state.incident_service
    result = await service.declare_incident(
        service_name=request.service_name,
        message=request.message,
        stack_trace=request.stack_trace
    )
    return result

@router.get("/incident/{incident_id}")
async def get_incident(incident_id: str, req: Request):
    """Get incident details"""
    service = req.app.state.incident_service
    result = await service.get_incident(incident_id)
    if not result:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result

@router.get("/incidents")
async def list_incidents(req: Request, limit: int = 50):
    """List all incidents"""
    service = req.app.state.incident_service
    result = await service.get_all_incidents(limit)
    return {"incidents": result, "count": len(result)}

@router.post("/incident/rollback")
async def rollback_incident(request: RollbackRequest, req: Request):
    """Rollback an incident"""
    service = req.app.state.incident_service
    result = await service.rollback(request.incident_id)
    return result

@router.get("/services")
async def list_services(req: Request):
    """List all services"""
    service = req.app.state.incident_service
    result = await service.list_services()
    return {"services": result}

@router.post("/services/seed")
async def seed_services(req: Request):
    """Seed demo services"""
    service = req.app.state.incident_service
    result = await service.seed_services()
    return result
