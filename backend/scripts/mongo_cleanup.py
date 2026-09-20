"""Plan or apply reversible BillBuster storage cleanup.

Dry-run is the default and performs no writes:

    uv run python -m scripts.mongo_cleanup --dry-run

Apply and rollback require the exact target fingerprint printed by dry-run.
Permanent deletion is intentionally not supported.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from billproof import store
from billproof.admin.mongo_cleanup import (
    CleanupSafetyError,
    apply_manifest,
    build_cleanup_manifest,
    load_manifest,
    rollback_cleanup,
    validate_apply_confirmation,
    write_cleanup_artifacts,
)
from billproof.admin.mongo_inventory import build_inventory
from billproof.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent if BACKEND_ROOT.name == "backend" else BACKEND_ROOT
ARTIFACT_DIR = WORKSPACE_ROOT / "artifacts"
DEFAULT_INVENTORY = ARTIFACT_DIR / "mongo_inventory.json"
DEFAULT_PLAN = ARTIFACT_DIR / "mongo_cleanup_plan.md"
DEFAULT_MANIFEST = ARTIFACT_DIR / "mongo_cleanup_manifest.private.json"


def _write_confirmation(args, *, manifest: dict | None = None) -> None:
    validate_apply_confirmation(
        manifest
        or {
            "plan_id": args.rollback,
            "target": {"target_id": store.target_id()},
        },
        reviewed_plan_id=args.plan_id or args.rollback,
        confirmed_target_id=args.confirm_target or "",
        acknowledged_review=args.acknowledge_reviewed_plan,
        backup_confirmed=args.backup_confirmed,
        allow_remote_write=args.allow_remote_write,
        remote_writes_enabled=get_settings().mongodb_cleanup_writes_enabled,
    )


async def _run(args) -> None:
    await store.connect()
    try:
        if args.apply:
            manifest = load_manifest(args.manifest)
            _write_confirmation(args, manifest=manifest)
            result = await apply_manifest(manifest)
            total = sum(action["quarantined_count"] for action in result["actions"])
            print(f"Quarantined {total} document(s); cleanup_run_id={result['cleanup_run_id']}.")
            return
        if args.rollback:
            _write_confirmation(args)
            result = await rollback_cleanup(args.rollback)
            print(
                f"Restored {result['restored_count']} document(s); "
                f"cleanup_run_id={result['cleanup_run_id']}."
            )
            return

        inventory = await build_inventory()
        manifest = await build_cleanup_manifest(inventory)
        write_cleanup_artifacts(
            inventory,
            manifest,
            inventory_path=args.inventory,
            plan_path=args.plan,
            manifest_path=args.manifest,
        )
        count = sum(action["expected_count"] for action in manifest["actions"])
        print(
            f"Dry-run only: {count} reversible quarantine candidate(s); "
            f"plan_id={manifest['plan_id']}; target_id={store.target_id()}."
        )
        print(f"Public plan: {args.plan}")
        print(f"Private manifest (gitignored): {args.manifest}")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (default); never writes storage.")
    mode.add_argument("--apply", action="store_true", help="Apply a reviewed quarantine-only plan.")
    mode.add_argument("--rollback", metavar="CLEANUP_RUN_ID", help="Roll back one quarantine run.")
    parser.add_argument("--plan-id", help="Exact reviewed plan ID (required for apply).")
    parser.add_argument("--confirm-target", help="Exact target_id printed by dry-run.")
    parser.add_argument("--acknowledge-reviewed-plan", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--allow-remote-write", action="store_true")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    if args.apply and not args.plan_id:
        parser.error("--apply requires --plan-id")
    try:
        asyncio.run(_run(args))
    except CleanupSafetyError as exc:
        raise SystemExit(f"Cleanup refused: {exc}") from None
    except Exception as exc:  # noqa: BLE001 -- sanitize all driver/config failure details
        raise SystemExit(
            f"Cleanup failed safely ({type(exc).__name__}); no connection details were printed."
        ) from None


if __name__ == "__main__":
    main()
