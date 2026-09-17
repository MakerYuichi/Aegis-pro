import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from src import auth as auth_module


@pytest.mark.asyncio
async def test_wrong_audience_rejected():
    """SDK must reject tokens issued for a different API."""
    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "Bearer wrong-aud-token"}

    with patch.object(auth_module.auth0, "require_auth") as mock_ra:
        mock_dep = AsyncMock(
            side_effect=HTTPException(
                status_code=401,
                detail={"error": "invalid_token",
                        "error_description": "Audience mismatch (single aud)"},
            )
        )
        mock_ra.return_value = mock_dep

        with pytest.raises(HTTPException) as exc:
            await auth_module.require_auth(mock_request)

        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_correct_audience_passes():
    """Token with the correct audience passes through."""
    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "Bearer valid-token"}

    expected_claims = {"sub": "auth0|user123", "aud": "https://aegispro.com"}

    with patch.object(auth_module.auth0, "require_auth") as mock_ra:
        mock_dep = AsyncMock(return_value=expected_claims)
        mock_ra.return_value = mock_dep

        claims = await auth_module.require_auth(mock_request)
        assert claims["aud"] == "https://aegispro.com"


@pytest.mark.asyncio
async def test_missing_token_normalized_to_401():
    """The 400→401 normalization for missing tokens still works."""
    mock_request = MagicMock()
    mock_request.headers = {}

    with patch.object(auth_module.auth0, "require_auth") as mock_ra:
        mock_dep = AsyncMock(
            side_effect=HTTPException(status_code=400, detail="Missing token")
        )
        mock_ra.return_value = mock_dep

        with pytest.raises(HTTPException) as exc:
            await auth_module.require_auth(mock_request)

        assert exc.value.status_code == 401
        assert exc.value.headers.get("WWW-Authenticate") == "Bearer"
