"""Tests for require_admin — the admin access gate."""
import pytest
from fastapi import HTTPException

from src.auth import require_admin, _admin_allowlist, _claim_email


def test_allowlist_empty_by_default(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "")
    assert _admin_allowlist() == set()


def test_allowlist_parses_comma_separated(monkeypatch):
    monkeypatch.setattr(
        "src.auth.settings.ADMIN_EMAILS",
        "a@x.com, b@y.com ,, c@z.com",
    )
    assert _admin_allowlist() == {"a@x.com", "b@y.com", "c@z.com"}


def test_allowlist_lowercases(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "Admin@Example.COM")
    assert _admin_allowlist() == {"admin@example.com"}


@pytest.mark.parametrize("claims,expected", [
    ({"email": "a@x.com"}, "a@x.com"),
    ({"https://aegis-pro/email": "b@y.com"}, "b@y.com"),
    ({"email": "C@Z.com"}, "c@z.com"),
    ({}, ""),
    ({"email": None}, ""),
    ({"email": 123}, ""),
])
def test_claim_email_extraction(claims, expected):
    assert _claim_email(claims) == expected


@pytest.mark.asyncio
async def test_require_admin_empty_allowlist_fails_closed(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "")
    with pytest.raises(HTTPException) as exc:
        await require_admin(claims={"email": "anyone@example.com"})
    assert exc.value.status_code == 403
    assert "not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_require_admin_no_email_claim_fails(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "admin@x.com")
    with pytest.raises(HTTPException) as exc:
        await require_admin(claims={})
    assert exc.value.status_code == 403
    assert "email claim" in exc.value.detail


@pytest.mark.asyncio
async def test_require_admin_non_admin_rejected(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "admin@x.com")
    with pytest.raises(HTTPException) as exc:
        await require_admin(claims={"email": "nobody@y.com"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_admin_accepted(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "admin@x.com")
    claims = {"email": "admin@x.com"}
    assert await require_admin(claims=claims) is claims


@pytest.mark.asyncio
async def test_require_admin_case_insensitive(monkeypatch):
    monkeypatch.setattr("src.auth.settings.ADMIN_EMAILS", "Admin@X.com")
    claims = {"email": "admin@x.com"}
    assert await require_admin(claims=claims) is claims
