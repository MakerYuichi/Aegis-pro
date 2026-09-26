from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from src.services.autofix_service import AutoFixService
from src.services.oncall_service import OnCallService
from src.services.alert_service import AlertService
from src.auth import require_auth 

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


# ── Whoami ──────────────────────────────────────────────────
@router.get("/me")
async def whoami(claims: dict = Depends(require_auth)):
    """
    Return the caller's email and admin status.

    Called once by the frontend after login to decide whether to show
    the admin navbar link. Always 200 for an authenticated user —
    non-admins get is_admin: false, not 403. The /admin/* routes
    themselves still 403 for non-admins.
    """
    from src.auth import _claim_email, _admin_allowlist

    email = _claim_email(claims)
    return {
        "email": email,
        "is_admin": bool(email and email in _admin_allowlist()),
    }


# ── Incident declaration ────────────────────────────────────
@router.post("/incident/declare")
async def declare_incident(
    request: DeclareIncidentRequest,
    req: Request,
    claims: dict = Depends(require_auth),
):
    service = req.app.state.incident_service
    result = await service.declare_incident(
        service_name=request.service_name,
        message=request.message,
        stack_trace=request.stack_trace,
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

# ── Rollback ────────────────────────────────────────────────
@router.post("/incident/rollback")
async def rollback_incident(
    request: RollbackRequest,
    req: Request,
    claims: dict = Depends(require_auth),
):
    service = req.app.state.incident_service
    result = await service.rollback(request.incident_id)
    return result


# ── Approve auto-fix ────────────────────────────────────────
@router.post("/incident/{incident_id}/approve")
async def approve_fix(
    incident_id: str,
    claims: dict = Depends(require_auth),
):
    """Approve an auto-generated fix"""
    autofix = AutoFixService()
    result = await autofix.approve_fix(incident_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Reject auto-fix ─────────────────────────────────────────
@router.post("/incident/{incident_id}/reject")
async def reject_fix(
    incident_id: str,
    request: RejectFixRequest = RejectFixRequest(),
    claims: dict = Depends(require_auth),
):
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

# ── Create service ──────────────────────────────────────────
@router.post("/services")
async def create_service(
    request: CreateServiceRequest,
    req: Request,
    claims: dict = Depends(require_auth),
):
    service = req.app.state.incident_service
    try:
        return await service.add_service(request.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
# ── Delete service ──────────────────────────────────────────
@router.delete("/services/{name}")
async def delete_service(
    name: str,
    req: Request,
    claims: dict = Depends(require_auth),
):
    service = req.app.state.incident_service
    return await service.delete_service(name)


# ── Seed services ───────────────────────────────────────────
@router.post("/services/seed")
async def seed_services(
    req: Request,
    claims: dict = Depends(require_auth),
):
    service = req.app.state.incident_service
    result = await service.seed_services()
    return result

@router.get("/fixes/pending")
async def get_pending_fixes():
    """Get all pending fixes for approval"""
    autofix = AutoFixService()
    pending = await autofix.get_pending_fixes()
    return {"fixes": pending, "count": len(pending)}

# ── Fixes: approve from UI ──────────────────────────────────
@router.post("/fixes/{incident_id}/approve")
async def approve_fix_from_ui(
    incident_id: str,
    claims: dict = Depends(require_auth),
):
    """Approve a fix from the UI"""
    autofix = AutoFixService()
    result = await autofix.approve_fix(incident_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

# ── Fixes: reject from UI ───────────────────────────────────
@router.post("/fixes/{incident_id}/reject")
async def reject_fix_from_ui(
    incident_id: str,
    request: RejectFixRequest = RejectFixRequest(),
    claims: dict = Depends(require_auth),
):
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

# ── On-call member management ───────────────────────────────
@router.post("/oncall/members")
async def add_oncall_member(
    request: TeamMemberRequest,
    claims: dict = Depends(require_auth),
):
    oncall = OnCallService()
    try:
        return await oncall.add_member(request.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/oncall/members/{member_id}")
async def remove_oncall_member(
    member_id: int,
    claims: dict = Depends(require_auth),
):
    oncall = OnCallService()
    return await oncall.remove_member(member_id)


@router.get("/oncall/alert/history")
async def get_alert_history(req: Request, limit: int = 20):
    """Get alert history"""
    alerts = AlertService()
    history = await alerts.get_alert_history(limit)
    return {"alerts": history, "count": len(history)}

# ── On-call alerts ──────────────────────────────────────────
@router.post("/oncall/alert")
async def send_oncall_alert(
    request: AlertRequest,
    claims: dict = Depends(require_auth),
):
    alerts = AlertService()
    message = request.message or (
        f"🚨 AEGIS PRO page: all hands on incident {request.incident_id}"
        if request.incident_id
        else "🚨 AEGIS PRO: please acknowledge — on-call page"
    )
    if request.everyone or (request.target or "").lower() in ("everyone", "all"):
        return await alerts.alert_everyone(message, request.service_name)
    if not request.target:
        raise HTTPException(
            status_code=400,
            detail="Provide target Slack handle or set everyone=true",
        )
    result = await alerts.alert_person(
        slack_handle=request.target,
        message=message,
        incident_id=request.incident_id,
    )
    return result

# ── Phase 10: demo-to-dashboard continuity ──────────────────────────────

from pydantic import BaseModel as _BaseModel  # local to this section

class _LinkDemoSessionRequest(_BaseModel):
    session_id: str


class _OnboardingInterestRequest(_BaseModel):
    session_id: Optional[str] = None
    repo: Optional[str] = None


@router.get("/me/demo-sessions")
async def list_my_demo_sessions(
    limit: int = 10,
    claims: dict = Depends(require_auth),
):
    """
    Return the signed-in user's linked demo sessions, newest first.

    Used by the dashboard card to show "You tried <org>/<repo> in the
    demo." Returns an empty list for users who never demoed, or who
    demoed without ever linking.
    """
    from src.auth import _claim_email
    from src.demo import session_service

    email = _claim_email(claims)
    if not email:
        raise HTTPException(
            status_code=403,
            detail="Token has no email claim — cannot look up demo sessions.",
        )

    limit = max(1, min(limit, 50))  # clamp
    sessions = await session_service.list_for_user(email, limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.post("/me/link-demo-session")
async def link_my_demo_session(
    request: Request,
    claims: dict = Depends(require_auth),
):
    """
    Link the caller's demo session to their email.

    Reads the demo_session_id cookie directly — the cookie is
    httpOnly, so the frontend cannot read it, but the browser sends
    it automatically on the request. No body parameter needed.
    """
    from src.auth import _claim_email
    from src.demo import session_service
    from src.demo.endpoints import SESSION_COOKIE

    email = _claim_email(claims)
    if not email:
        raise HTTPException(status_code=403, detail="Token has no email claim")

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return {"status": "no_cookie", "email": email}

    linked = await session_service.link_to_user(session_id, email)
    return {
        "status": "linked" if linked else "no_match",
        "session_id": session_id,
        "email": email,
    }


@router.post("/me/onboarding-interest")
async def mark_onboarding_interest(
    body: _OnboardingInterestRequest,
    claims: dict = Depends(require_auth),
):
    """
    Record that the user clicked "Connect it now" for their demo session.

    The session_id is optional — if omitted, we mark the user's most
    recent linked session (the one the card was showing).

    Fails silently for the caller: always returns 200, with a flag
    indicating whether a row was updated. The frontend shows the
    thank-you either way.
    """
    from src.auth import _claim_email
    from src.demo import session_service

    email = _claim_email(claims)
    if not email:
        raise HTTPException(403, "Token has no email claim")

    recorded = await session_service.mark_onboarding_interest(
        email, body.session_id
    )
    return {"status": "recorded" if recorded else "no_match", "email": email}
