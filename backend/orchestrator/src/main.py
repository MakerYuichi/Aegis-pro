from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import redis.asyncio as redis
import os

from src.api.routes import router
from src.api.slack import router as slack_router
from src.database import init_db
from src.services.incident_service import IncidentService
from src.api.webhook import router as webhook_router
from src.demo.endpoints import router as demo_router
from src.api.admin import router as admin_router
from src.config import settings
from src.websocket import manager
from src.auth import auth0

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting AEGIS PRO...")
    
    db_connected = False
    try:
        await init_db()
        db_connected = True
        logger.info("✅ Database connected successfully")
    except Exception as e:
        logger.warning(f"⚠️ Database connection failed: {e}")
    
    redis_connected = False
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        redis_connected = True
        logger.info("✅ Redis connected successfully")
        await redis_client.close()
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {e}")
    
    app.state.db_connected = db_connected
    app.state.redis_connected = redis_connected
    app.state.incident_service = IncidentService()
    if settings.DEMO_MODE:
        try:
            from src.demo.seed_backfill import backfill_demo_embeddings
            from src.services.rag_service import RAGService

            rag = RAGService()
            await backfill_demo_embeddings(rag)
        except Exception as e:
            logger.warning(f"⚠️ Demo embedding backfill failed: {e}")
    logger.info(f"🔒 AUTO_FIX_MODE={settings.AUTO_FIX_MODE}")
    
    logger.info("✅ AEGIS PRO is ready!")
    yield
    
    logger.info("🛑 Shutting down AEGIS PRO...")

app = FastAPI(
    title="AEGIS PRO",
    description="Open-source AI incident commander that turns an alert into a reviewed fix PR.",
    version="1.0.0",
    lifespan=lifespan
)

_cors_env = os.getenv("CORS_ORIGINS", "*")
allow_origins = (
    ["*"] if _cors_env.strip() == "*"
    else [o.strip() for o in _cors_env.split(",") if o.strip()]
)

# CORS
# allow_credentials=True with allow_origins=["*"] is invalid per the
# CORS spec — browsers reject credentialed requests against a wildcard.
# Disable credentials when the origin list is a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials="*" not in allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info(f"🔓 CORS allow_origins={allow_origins} credentials={'*' not in allow_origins}")

# Include routes
app.include_router(admin_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1")
app.include_router(slack_router)
app.include_router(webhook_router)
app.include_router(demo_router)

@app.websocket("/ws/incidents")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time incident updates"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/")
async def root():
    return {
        "service": "AEGIS PRO",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/health",
            "api": "/api/v1",
            "ping": "/api/v1/ping",
            "slack": "/slack/events",
            "slack_status": "/slack/status",
            "websocket": "ws://localhost:8000/ws/incidents"
        }
    }

@app.get("/health")
async def health_check():
    db_status = getattr(app.state, 'db_connected', False)
    redis_status = getattr(app.state, 'redis_connected', False)
    
    return {
        "status": "healthy" if db_status and redis_status else "degraded",
        "version": "1.0.0",
        "auto_fix_mode": settings.AUTO_FIX_MODE,
        "demo_mode": settings.DEMO_MODE,
        "services": {
            "database": "connected" if db_status else "disconnected",
            "redis": "connected" if redis_status else "disconnected"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )