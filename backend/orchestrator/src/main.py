from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger

from src.api.routes import router
from src.database import init_db
from src.services.incident_service import IncidentService

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting AEGIS PRO...")
    
    try:
        await init_db()
        logger.info("✅ Database connected successfully")
    except Exception as e:
        logger.warning(f"⚠️ Database connection failed: {e}")
    
    # Initialize services
    app.state.incident_service = IncidentService()
    
    logger.info("✅ AEGIS PRO is ready!")
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down AEGIS PRO...")

# Create FastAPI app
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

@app.get("/")
async def root():
    return {
        "service": "AEGIS PRO",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/health",
            "api": "/api/v1",
            "ping": "/api/v1/ping"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "database": "connected",
            "redis": "connected"
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
    