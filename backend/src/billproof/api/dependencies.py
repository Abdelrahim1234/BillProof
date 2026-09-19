from datetime import datetime

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from billproof.db import get_db
from billproof.errors import forbidden, unauthorized
from billproof.models import Case
from billproof.repositories.cases import get_case_by_token


def get_current_case(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Case:
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized("Missing case access token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise unauthorized("Missing case access token")

    case = get_case_by_token(db, token)
    if case is None:
        raise forbidden("Invalid case access token")
    if case.expires_at < datetime.utcnow():
        raise forbidden("Case access token has expired")
    return case
