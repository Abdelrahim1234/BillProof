"""Admin CLI: delete expired cases and everything scoped to them.

Run: uv run python scripts/purge_expired_cases.py
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof import store
from billproof.models import Case
from billproof.repositories.case_records import purge_case_cascade


async def main() -> None:
    await store.connect()
    db = store.get_private_db()
    docs = await db["cases"].find({"expires_at": {"$lt": datetime.now(UTC)}}).to_list()
    expired = [Case.from_doc(d) for d in docs]
    for case in expired:
        await purge_case_cascade(db, case.id)
    print(f"Purged {len(expired)} expired case(s).")
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
