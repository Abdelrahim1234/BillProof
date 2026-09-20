"""Admin CLI: the active-market demo readiness gate.

CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 7. Checks are against the ACTIVE
MARKET only (config.active_market_facility_list) -- other stored facilities
(e.g. Inova, out of scope for nrv_core_v1) are excluded from every check
here, never deleted, and reported separately. Row/facility counts are
observed and printed, never hardcoded as a pass/fail threshold.

Usage: uv run python -m scripts.readiness
Exit 0: every check passes. Exit 1: at least one fails.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_status import gather_status
from verify_demo import main as verify_demo_main

from billproof import store
from billproof.config import get_settings
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _run_pytest(node_id: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", node_id],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode == 0, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""


async def _run_verify(argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = ["verify_demo.py", *argv]
    try:
        return await verify_demo_main()
    finally:
        sys.argv = old_argv


async def gather_checks() -> list[tuple[str, bool, str]]:
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []

    checks.append(("active market == nrv_core_v1", settings.active_market_id == "nrv_core_v1", settings.active_market_id))

    await store.connect()
    db = store.get_public_db()
    status = await gather_status(db)
    facility_by_name = {f.name: f for f in status["facilities"]}

    p0_registered = [name for name in settings.active_market_facility_list if name in facility_by_name]
    checks.append(
        (
            "both P0 facilities registered",
            len(p0_registered) == len(settings.active_market_facility_list),
            f"{len(p0_registered)}/{len(settings.active_market_facility_list)}: {p0_registered}",
        )
    )

    manifest_ok = []
    for name in settings.active_market_facility_list:
        facility = facility_by_name.get(name)
        if not facility:
            manifest_ok.append(False)
            continue
        sources = await hospitals_repo.sources_by_type(db, {"cms_mrf", "cms_mrf_verified_extract", "cms_mrf_verified"})
        has_active = any(s.hospital_id == facility.id and s.active for s in sources)
        manifest_ok.append(has_active)
    checks.append(
        (
            "at least one active real source manifest per P0 facility",
            all(manifest_ok),
            str(dict(zip(settings.active_market_facility_list, manifest_ok, strict=True))),
        )
    )

    active_records = await prices_repo.search_prices(db, limit=1_000_000)
    all_real = all(not r.is_synthetic for r in active_records)
    checks.append(("active public benchmark rows are is_synthetic=false", all_real and bool(active_records), f"{len(active_records)} active-market rows, all real: {all_real}"))

    hero_ok = []
    for code in ("80053", "71046"):
        rows = [r for r in active_records if r.code == code]
        has_evidence = bool(rows) and all(r.source_url and not r.source_url.count("?") for r in rows)
        hero_ok.append(has_evidence)
    checks.append(("80053 and 71046 demo evidence exists with provenance", all(hero_ok), str(dict(zip(("80053", "71046"), hero_ok, strict=True)))))

    citations_ok = all((r.citation_url or r.source_url) and "?" not in (r.citation_url or r.source_url) for r in active_records)
    checks.append(("all public citation URLs are stable, no secret query params", citations_ok, ""))

    await store.close()

    commercial_exit = await _run_verify(["--coverage", "commercial", "--payer", "Cigna", "--plan", "NPR"])
    checks.append(("commercial/no-EOB fixture passes (context_only)", commercial_exit == 0, f"exit {commercial_exit}"))

    self_pay_exit = await _run_verify([])
    checks.append(("self-pay/gross fixture passes (compared)", self_pay_exit == 0, f"exit {self_pay_exit}"))

    cascade_passed, cascade_summary = _run_pytest("tests/integration/test_case_purge.py")
    checks.append(("delete cascade integration test passes", cascade_passed, cascade_summary))

    return checks


async def main() -> int:
    checks = await gather_checks()
    print("BILLBUSTER ACTIVE-MARKET READINESS")
    for name, passed, detail in checks:
        line = f"  [{'PASS' if passed else 'FAIL'}] {name}"
        if detail:
            line += f"  -- {detail}"
        print(line)
    overall = all(passed for _, passed, _ in checks)
    print(f"\nVERDICT  {'READY' if overall else 'NOT READY'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
