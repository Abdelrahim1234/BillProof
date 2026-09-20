"""Admin CLI: print the real, current data picture -- no secrets, no spin.

FIX_BACKEND.md Fix 6: `/ready` reports `seeded: true` on any non-empty
database regardless of how thin the data actually is, and nothing else in
the API says how much is really there. This introspects the live public DB
directly and prints exactly what it finds. Source URLs are never printed
(some carry SAS tokens/access signatures) -- only counts, codes, and
charge types.

``gather_status`` is the reusable half (also used by scripts/verify_demo.py's
seed-sanity check); ``main`` is just its CLI printer.

Usage: uv run python scripts/data_status.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof import store
from billproof.models import Facility
from billproof.repositories import prices as prices_repo


async def gather_status(db) -> dict:
    facility_docs = await db["facilities"].find({}).to_list()
    facilities = [Facility.from_doc(d) for d in facility_docs]
    facility_name_by_id = {f.id: f.name for f in facilities}

    synthetic = await prices_repo.all_synthetic(db)
    real = await prices_repo.all_non_synthetic(db)
    all_records = synthetic + real

    distinct_codes = sorted({r.code for r in all_records if r.code})
    charge_types_present = sorted({r.charge_type for r in all_records})
    payer_negotiated = [r for r in all_records if r.charge_type == "payer_negotiated"]

    # Distinct codes per facility, not raw row count (one code has many rows:
    # gross, cash, several payers...).
    distinct_codes_per_facility: dict[str, set[str]] = {}
    for r in all_records:
        name = facility_name_by_id.get(r.hospital_id, r.hospital_id)
        distinct_codes_per_facility.setdefault(name, set()).add(r.code)

    gross_and_cash_by_facility: dict[str, dict[str, set[str]]] = {}
    for r in all_records:
        if r.charge_type not in ("gross", "discounted_cash"):
            continue
        name = facility_name_by_id.get(r.hospital_id, r.hospital_id)
        gross_and_cash_by_facility.setdefault(name, {"gross": set(), "discounted_cash": set()})
        gross_and_cash_by_facility[name][r.charge_type].add(r.code)

    has_gross_and_cash_pair = any(
        sides["gross"] & sides["discounted_cash"] for sides in gross_and_cash_by_facility.values()
    )
    gate_pass = bool(real) and has_gross_and_cash_pair
    if not real:
        gate_reason = "zero non-synthetic (real) price records"
    elif not has_gross_and_cash_pair:
        gate_reason = "no facility has both a gross and a discounted_cash row for the same code"
    else:
        gate_reason = ""

    return {
        "facilities": facilities,
        "real": real,
        "synthetic": synthetic,
        "all_records": all_records,
        "distinct_codes": distinct_codes,
        "charge_types_present": charge_types_present,
        "payer_negotiated": payer_negotiated,
        "distinct_codes_per_facility": distinct_codes_per_facility,
        "gate_pass": gate_pass,
        "gate_reason": gate_reason,
    }


def _print_report(status: dict) -> None:
    facilities = status["facilities"]
    real = status["real"]
    synthetic = status["synthetic"]
    all_records = status["all_records"]
    distinct_codes = status["distinct_codes"]
    charge_types_present = status["charge_types_present"]
    payer_negotiated = status["payer_negotiated"]
    distinct_codes_per_facility = status["distinct_codes_per_facility"]

    print(f"facilities:            {len(facilities)}")
    print(f"price records:         {len(all_records)}   (real: {len(real)}, synthetic: {len(synthetic)})")
    print(f"distinct codes:        {len(distinct_codes)}    {distinct_codes}")
    print(f"charge types present:  {', '.join(charge_types_present) if charge_types_present else '(none)'}")
    if len(payer_negotiated) <= 3:
        examples = ", ".join(f"{r.payer_name}/{r.plan_name} code {r.code}" for r in payer_negotiated)
        print(f"payer-negotiated rows: {len(payer_negotiated)}    ({examples})" if examples else f"payer-negotiated rows: {len(payer_negotiated)}")
    else:
        distinct_payers = len({(r.payer_normalized, r.plan_normalized) for r in payer_negotiated})
        print(f"payer-negotiated rows: {len(payer_negotiated)}    ({distinct_payers} distinct payer/plan pairs)")
    codes_line = ", ".join(f"{name} {len(codes)}" for name, codes in sorted(distinct_codes_per_facility.items()))
    print(f"codes per facility:    {codes_line if codes_line else '(none)'}")
    gate_word = "PASS" if status["gate_pass"] else "FAIL"
    gate_suffix = f"  {status['gate_reason']}" if status["gate_reason"] else ""
    print(f"demo gate:             {gate_word}{gate_suffix}")


async def main() -> None:
    await store.connect()
    db = store.get_public_db()
    status = await gather_status(db)
    _print_report(status)
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
