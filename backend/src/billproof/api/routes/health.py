from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from billproof.db import get_db
from billproof.errors import ok
from billproof.repositories.hospitals import count_hospitals

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    seeded = count_hospitals(db) > 0
    return ok({"status": "ok", "db": "ok", "seeded": seeded})
