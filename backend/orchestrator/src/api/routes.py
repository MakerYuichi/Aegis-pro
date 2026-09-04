from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from src.services.autofix_service import AutoFixService
from src.services.oncall_service import OnCallService
from src.services.alert_service import AlertService

router = APIRouter()

class DeclareIncidentRequest(BaseModel):
    service_name: str
    message: str
    stack_trace: Optional[str] = None

class RollbackRequest(BaseModel):
    incident_id: str

class RejectFixRequest(BaseModel):
    reason: Optional[str] = None

class AlertRequest(BaseModel):
    target: Optional[str] = None
    everyone: bool = False
    message: Optional[str] = None
    incident_id: Optional[str] = None
    service_name: Optional[str] = None

class TeamMemberRequest(BaseModel):
    name: str
    email: Optional[str] = None
    slack_handle: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = "secondary"
    service_name: str

class CreateServiceRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    repo_name: Optional[str] = None
    dependencies: Optional[List[str]] = []
    is_critical: Optional[bool] = False
    on_call: Optional[List[str]] = []

@router.get("/ping")
async def ping():
    return {"message": "pong", "status": "alive"}

@router.post("/incident/declare")
async def declare_incident(request: DeclareIncidentRequest, req: Request):
    service = req.app.state.incident_service
    result = await service.declare_incident(
        service_name=request.service_name,
        message=request.message,
        stack_trace=request.stack_trace
    )
    return result

@router.get("/incident/{incident_id}")
async def get_incident(incident_id: str, req: Request):
    service = req.app.state.incident_service
    result = await service.get_incident(incident_id)
    if not result:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result

@router.get("/incidents")
async def list_incidents(req: Request, limit: int = 50):
    service = req.app.state.incident_service
    result = await service.get_all_incidents(limit)
    return {"incidents": result, "count": len(result)}

@router.post("/incident/rollback")
async def rollback_incident(request: RollbackRequest, req: Request):
    service = req.app.state.incident_service
    result = await service.rollback(request.incident_id)
    return result

@router.post("/incident/{incident_id}/approve")
async def approve_fix(incident_id: str):
    """Approve an auto-generated fix"""
    autofix = AutoFixService()
    result = await autofix.approve_fix(incident_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/incident/{incident_id}/reject")
async def reject_fix(incident_id: str, request: RejectFixRequest = RejectFixRequest()):
    autofix = AutoFixService()
    result = await autofix.reject_fix(incident_id, request.reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/services")
async def list_services(req: Request):
    service = req.app.state.incident_service
    result = await service.list_services()
    return {"services": result}

@router.post("/services")
async def create_service(request: CreateServiceRequest, req: Request):
    service = req.app.state.incident_service
    try:
        return await service.add_service(request.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/services/{name}")
async def delete_service(name: str, req: Request):
    service = req.app.state.incident_service
    return await service.delete_service(name)

@router.post("/services/seed")
async def seed_services(req: Request):
    service = req.app.state.incident_service
    result = await service.seed_services()
    return result

@router.get("/fixes/pending")
async def get_pending_fixes():
    """Get all pending fixes for approval"""
    autofix = AutoFixService()
    pending = await autofix.get_pending_fixes()
    return {"fixes": pending, "count": len(pending)}

@router.post("/fixes/{incident_id}/approve")
async def approve_fix_from_ui(incident_id: str):
    """Approve a fix from the UI"""
    autofix = AutoFixService()
    result = await autofix.approve_fix(incident_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/fixes/{incident_id}/reject")
async def reject_fix_from_ui(incident_id: str, request: RejectFixRequest = RejectFixRequest()):
    autofix = AutoFixService()
    result = await autofix.reject_fix(incident_id, request.reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/oncall")
async def list_oncall(service_name: Optional[str] = None):
    oncall = OnCallService()
    roster = await oncall.list_roster(service_name)
    return {"roster": roster, "count": len(roster)}

@router.post("/oncall/members")
async def add_oncall_member(request: TeamMemberRequest):
    oncall = OnCallService()
    try:
        return await oncall.add_member(request.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/oncall/members/{member_id}")
async def remove_oncall_member(member_id: int):
    oncall = OnCallService()
    return await oncall.remove_member(member_id)

@router.get("/oncall/alert/history")
async def get_alert_history(req: Request, limit: int = 20):
    """Get alert history"""
    alerts = AlertService()
    history = await alerts.get_alert_history(limit)
    return {"alerts": history, "count": len(history)}

@router.post("/oncall/alert")
async def send_oncall_alert(request: AlertRequest):
    alerts = AlertService()
    message = request.message or (
        f"🚨 AEGIS PRO page: all hands on incident {request.incident_id}"
        if request.incident_id
        else "🚨 AEGIS PRO: please acknowledge — on-call page"
    )
    if request.everyone or (request.target or "").lower() in ("everyone", "all"):
        return await alerts.alert_everyone(message, request.service_name)
    if not request.target:
        raise HTTPException(status_code=400, detail="Provide target Slack handle or set everyone=true")
    result = await alerts.alert_person(
        slack_handle=request.target,
        message=message,
        incident_id=request.incident_id,
    )
    return result
