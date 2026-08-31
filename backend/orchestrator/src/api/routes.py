from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class DeclareIncidentRequest(BaseModel):
    service_name: str
    message: str
    stack_trace: Optional[str] = None

@router.get("/ping")
async def ping():
    return {"message": "pong"}

@router.post("/incident/declare")
async def declare_incident(request: DeclareIncidentRequest, req: Request):
    """Declare a new incident"""
    return {
        "status": "received",
        "service": request.service_name,
        "message": request.message,
        "incident_id": "INC-20260101-001"
    }

@router.get("/services/seed")
async def seed_services(req: Request):
    """Seed demo services - placeholder"""
    return {
        "status": "seeded",
        "count": 8,
        "services": [
            "payment-api", "auth", "ledger", "refund",
            "fraud", "notification", "user", "database"
        ]
    }