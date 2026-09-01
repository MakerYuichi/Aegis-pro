from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import redis.asyncio as redis

from src.api.routes import router
from src.api.slack import router as slack_router
from src.database import init_db
from src.services.incident_service import IncidentService
from src.config import settings

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
    
    logger.info("✅ AEGIS PRO is ready!")
    yield
    
    logger.info("🛑 Shutting down AEGIS PRO...")

app = FastAPI(
    title="AEGIS PRO",
    description="AI Incident Commander - 10 second incident response",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router, prefix="/api/v1")
app.include_router(slack_router)

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
            "slack_status": "/slack/status"
        }
    }

@app.get("/health")
async def health_check():
    db_status = getattr(app.state, 'db_connected', False)
    redis_status = getattr(app.state, 'redis_connected', False)
    
    return {
        "status": "healthy" if db_status and redis_status else "degraded",
        "version": "1.0.0",
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
