from fastapi_plugin import Auth0FastAPI
from fastapi import HTTPException, Request
from loguru import logger

from src.config import settings
from fastapi import Depends

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


def _admin_allowlist() -> set[str]:
    """Parse ADMIN_EMAILS into a lowercase set. Recomputed per call."""
    return {
        e.strip().lower()
        for e in settings.ADMIN_EMAILS.split(",")
        if e.strip()
    }


def _claim_email(claims: dict) -> str:
    """
    Extract the email from a decoded Auth0 JWT.

    Auth0 places the email claim in different places depending on how
    the Action/rule that adds it is configured. Check the common shapes
    in order of likelihood, return "" if none are present.
    """
    for key in (
        "email",                                          # standard OIDC
        "https://aegis-pro/email",                        # namespaced (custom API)
        f"https://{settings.AUTH0_DOMAIN}/email",         # tenant-namespaced
    ):
        val = claims.get(key)
        if isinstance(val, str) and val:
            return val.lower()
    return ""


async def require_admin(claims: dict = Depends(require_auth)) -> dict:
    """
    Require an authenticated user whose email is in ADMIN_EMAILS.

    Fails closed: an empty ADMIN_EMAILS list returns 403 for everyone.
    """
    allowlist = _admin_allowlist()
    if not allowlist:
        logger.warning("🚫 Admin access attempted but ADMIN_EMAILS is empty")
        raise HTTPException(
            status_code=403,
            detail="Admin access is not configured on this instance.",
        )

    email = _claim_email(claims)
    if not email:
        logger.warning(
            f"🚫 Admin access attempted but no email claim found. "
            f"Claim keys: {sorted(claims.keys())}"
        )
        raise HTTPException(
            status_code=403,
            detail="Admin access requires an email claim in the token.",
        )

    if email not in allowlist:
        logger.warning(f"🚫 Admin access denied for {email}")
        raise HTTPException(status_code=403, detail="Admin access required")

    return claims