"""Generate a redacted, metadata-only storage inventory.

Run from ``backend/``:

    uv run python -m scripts.mongo_inventory --redact
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from billproof import store
from billproof.admin.mongo_inventory import build_inventory, write_inventory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent if BACKEND_ROOT.name == "backend" else BACKEND_ROOT
DEFAULT_OUTPUT = WORKSPACE_ROOT / "artifacts" / "mongo_inventory.json"


async def _run(output: Path) -> None:
    await store.connect()
    try:
        inventory = await build_inventory()
        write_inventory(inventory, output)
        collection_count = sum(len(database["collections"]) for database in inventory["databases"])
        print(
            f"Wrote redacted inventory for {collection_count} collection(s) "
            f"to {output}; target_id={inventory['target']['target_id']}."
        )
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redact",
        action="store_true",
        help="Accepted for clarity; inventory output is always redacted.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.output))
    except Exception as exc:  # noqa: BLE001 -- sanitize all driver/config failure details
        raise SystemExit(
            f"Inventory failed safely ({type(exc).__name__}); no connection details were printed."
        ) from None


if __name__ == "__main__":
    main()
