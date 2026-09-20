from datetime import UTC, datetime

from fastapi import Depends, Header

from billproof import store
from billproof.errors import AppError, unauthorized
from billproof.models import Case
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories.cases import get_case_by_token


def get_private_db():
    return store.get_private_db()


def get_public_db():
    return store.get_public_db()


async def get_authenticated_case(authorization: str | None = Header(default=None)) -> Case:
    """Authenticate a live case token without applying current-market policy.

    This narrower dependency is intentionally available to lifecycle operations
    such as DELETE so an owner can remove a legacy case after its hospital has
    left the active market.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized("Missing case access token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise unauthorized("Missing case access token")

    case = await get_case_by_token(store.get_private_db(), token)
    if case is None:
        raise AppError("INVALID_CASE_TOKEN", "Invalid case access token", status_code=403)
    if case.expires_at < datetime.now(UTC):
        raise AppError("CASE_TOKEN_EXPIRED", "Case access token has expired", status_code=403)
    return case


async def get_current_case(current: Case = Depends(get_authenticated_case)) -> Case:
    """Authorize a case for active-market reads and processing."""

    case = current
    if case.hospital_id and not await hospitals_repo.get_active_facility(
        store.get_public_db(), case.hospital_id
    ):
        raise AppError(
            "CASE_OUTSIDE_ACTIVE_MARKET",
            "This case is outside the active market",
            status_code=403,
        )
    return case
