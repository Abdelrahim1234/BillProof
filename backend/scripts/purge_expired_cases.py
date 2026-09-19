"""Admin CLI: delete expired cases and everything scoped to them.

Run: uv run python scripts/purge_expired_cases.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from billproof.db import SessionLocal, init_db
from billproof.models import Case
from billproof.services.case_lifecycle import purge_case


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        expired = list(db.scalars(select(Case).where(Case.expires_at < datetime.utcnow())))
        for case in expired:
            purge_case(db, case)
        db.commit()
        print(f"Purged {len(expired)} expired case(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
