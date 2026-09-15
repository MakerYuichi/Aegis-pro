from fastapi_plugin import Auth0FastAPI
from fastapi import HTTPException, Request
from loguru import logger

from src.config import settings

auth0 = Auth0FastAPI(
    domain=settings.AUTH0_DOMAIN,
    audience=settings.AUTH0_AUDIENCE,
)

async def require_auth(request: Request) -> dict:
    """Wrap Auth0's require_auth to normalize 400 → 401 for missing tokens."""
    try:
        return await auth0.require_auth()(request)
    except HTTPException as e:
        if e.status_code == 400:
            raise HTTPException(
                status_code=401,
                detail=e.detail,
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise

logger.info("🔐 Auth0 initialized")