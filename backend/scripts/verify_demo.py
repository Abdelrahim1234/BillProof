"""VERIFY_FIX.md: exercises the full backend flow against a synthetic bill
shaped like the real uploaded one, and prints a report a human can read in
ten seconds to decide whether the demo is ready.

This is not a unit test -- the test suite proves the rules; this proves the
demo. Runs against the same service the REST route calls (not over HTTP), so
it works with the API server stopped. Always deletes the case it creates,
even on failure.

Usage:
    uv run python -m scripts.verify_demo
    uv run python -m scripts.verify_demo --coverage commercial --payer Cigna --plan NPR
    uv run python -m scripts.verify_demo --facility carilion-nrv
    uv run python -m scripts.verify_demo --json
"""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof import store
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.schemas.bills import BillLineInput
from billproof.schemas.cases import CaseCreate
from billproof.services import case_lifecycle
from billproof.services.analysis import run_case_analysis, status_summary

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_status import gather_status  # sibling script, sys.path set above

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "nrv_uploaded_bill_synthetic.json"

FACILITY_SLUGS = {
    "lewisgale": "LewisGale Hospital Montgomery",
    "carilion-nrv": "Carilion New River Valley Medical Center",
    "inova": "Inova Fairfax Hospital",
}

SUBJECT_LABELS = {
    "billed_amount": "billed charge",
    "allowed_amount": "allowed amount",
    "patient_responsibility": "patient responsibility",
}

BENCHMARK_LABELS = {
    "hospital_discounted_cash": "discounted cash price",
    "peer_discounted_cash": "peer hospital cash price",
    "payer_negotiated_rate": "payer negotiated rate",
    "hospital_allowed_median": "hospital allowed-amount median",
    "peer_payer_negotiated_rate": "peer payer negotiated rate",
    "medicare_ffs_hospital_aggregate": "Medicare average payment",
    "hospital_discounted_cash_anchor": "discounted cash price (anchor only)",
    "hospital_deidentified_range_context": "de-identified allowed range (context only)",
}


def money(value) -> str:
    """$1,385.59 -- two decimals, thousands separator, always."""
    return f"${Decimal(str(value)):,.2f}"


def money_cents(cents: int) -> str:
    return money(Decimal(cents) / 100)


def redact_query(url: str | None) -> str | None:
    """Some real MRF source URLs (Azure blob storage) carry a SAS signature
    -- a live, time-limited access credential -- in the query string. This
    report proves a citation is real and traceable, not the credential
    itself; the host and path are enough for a human to verify the source."""
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment)) + " [query redacted]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", default="uninsured")
    parser.add_argument("--payer", default=None)
    parser.add_argument("--plan", default=None)
    parser.add_argument("--facility", default="lewisgale")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def build_line_inputs(fixture: dict) -> list[BillLineInput]:
    default_setting = fixture["care_setting"]
    inputs = []
    for raw in fixture["coded_lines"] + fixture["uncoded_lines"]:
        inputs.append(
            BillLineInput(
                code=raw.get("code"),
                code_type=raw.get("code_type", "UNKNOWN"),
                description=raw["description"],
                billed_amount=raw["billed_amount"],
                care_setting=raw.get("care_setting", default_setting),
            )
        )
    return inputs


def diagnose_zero_compared(comparisons, lines) -> list[str]:
    """VERIFY_FIX.md: "A silent zero is what caused this whole detour" --
    when nothing is compared, name the first coded line and exactly what its
    own analysis pass reported, instead of a bare zero."""
    by_id = {c.line_id: c for c in comparisons}
    for line in lines:
        if not line.code:
            continue
        comparison = by_id.get(line.id)
        if not comparison:
            continue
        out = [f"  first coded line: {line.code} {line.description!r}", f"  comparison_status: {comparison.comparison_status}"]
        if comparison.benchmark:
            out.append(f"  benchmark tried: {comparison.benchmark.basis} (tier {comparison.benchmark.match_tier})")
        if comparison.warnings:
            out.append(f"  reason: {' / '.join(comparison.warnings)}")
        return out
    return ["  no coded lines in the fixture"]


def check_amount_type_honesty(comparisons, lines) -> bool:
    """FIX_BACKEND.md Fix 2, re-checked here: no limitation should claim a
    line carries patient-responsibility when it does not."""
    by_id = {ln.id: ln for ln in lines}
    for c in comparisons:
        line = by_id.get(c.line_id)
        if line is None:
            continue
        mentions_patient_resp = any("patient-responsibility" in w or "patient responsibility" in w for w in c.warnings)
        if mentions_patient_resp and line.patient_responsibility is None:
            return False
    return True


async def main() -> int:
    args = parse_args()
    facility_name = FACILITY_SLUGS.get(args.facility, args.facility)

    await store.connect()
    public_db = store.get_public_db()
    private_db = store.get_private_db()

    fixture = load_fixture()
    report_lines: list[str] = []
    exit_code = 1
    case = None

    try:
        # 1. Check the seed.
        status = await gather_status(public_db)
        if not status["facilities"] or not status["all_records"]:
            print("SEED IS EMPTY. Run `uv run python scripts/seed.py` first, then retry.")
            return 1

        facility = await hospitals_repo.get_facility_by_name(public_db, facility_name)
        if not facility:
            print(f"Facility {facility_name!r} not found in the seed. Known facilities:")
            for f in status["facilities"]:
                print(f"  - {f.name}")
            return 1

        # 2. Create a case.
        case, _token = await cases_repo.create_case(
            private_db,
            CaseCreate(
                hospital_id=facility.id,
                coverage_type=args.coverage,
                payer_name=args.payer,
                plan_name=args.plan,
                care_setting=fixture["care_setting"],
                language="en",
            ),
        )

        # 3. Load the fixture as confirmed bill lines.
        line_inputs = build_line_inputs(fixture)
        lines = await cases_repo.create_bill_lines(private_db, case.id, line_inputs, confirmed=True)

        # 4. Run analysis through the same service the REST route calls.
        comparisons, findings, _overall = await run_case_analysis(public_db, case, lines)
        summary = status_summary(comparisons)
        header_total = len(fixture["coded_lines"]) + len(fixture["uncoded_lines"])

        # ---- 5. Build the report ----
        by_line = {ln.id: ln for ln in lines}
        compared = [c for c in comparisons if c.comparison_status == "compared"]

        # CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 3: the gate must verify the
        # correct outcome FOR THE SCENARIO, not require a compared line for
        # every input. An insured case with no EOB producing zero compared
        # lines is the *correct* outcome, not a failure.
        has_eob = any(ln.allowed_amount is not None for ln in lines)
        if args.coverage == "uninsured":
            scenario = "self_pay_or_gross_audit"
            expected_distribution = "at least one compared line (exact same-facility benchmark exists)"
            scenario_ok = summary["compared"] >= 1
        elif has_eob:
            scenario = "insured_with_final_eob"
            expected_distribution = "compared or context_only (never forced insufficient_data when evidence exists)"
            scenario_ok = (summary["compared"] + summary["context_only"]) >= 1
        else:
            scenario = "insured_without_eob"
            expected_distribution = "zero compared lines; context_only/insufficient_data only"
            # The failure mode this guards against is compared > 0 -- a
            # fabricated comparison with no EOB to support it. Zero is valid.
            scenario_ok = summary["compared"] == 0
        observed_distribution = f"compared={summary['compared']} context_only={summary['context_only']} insufficient_data={summary['insufficient_data']}"

        gate_has_citations = all(
            c.references and all(r.get("source_url") and r.get("retrieval_date") for r in c.references) for c in compared
        )
        # Vacuously true when nothing is compared -- that failure is already
        # reported by the scenario check; this check is specifically about
        # synthetic data hiding inside a real comparison, not about zero.
        gate_all_real = all(not r.get("is_synthetic") for c in compared for r in c.references)
        gate_amount_honesty = check_amount_type_honesty(comparisons, lines)
        gate_counts_derive = (
            summary["compared"] + summary["context_only"] + summary["insufficient_data"] == summary["total"] == len(comparisons)
        )

        checks = [
            (f"scenario ({scenario}) outcome matches its coverage-dependent contract", scenario_ok),
            ("every compared line carries a source URL and dates", gate_has_citations if compared else True),
            ("every compared line is non-synthetic", gate_all_real, True),  # reports, never fails the run
            ("no limitation names an amount type its line lacks", gate_amount_honesty),
            ("counts derive from statuses", gate_counts_derive),
        ]
        blocking_pass = all(passed for _, passed, *rest in checks if not rest)

        any_synthetic_compared = compared and not gate_all_real
        verdict = "DEMO-READY" + (" (synthetic data)" if any_synthetic_compared else "")
        if not blocking_pass:
            verdict = "NOT DEMO-READY"

        real_evidence_count = sum(1 for c in compared for r in c.references if not r.get("is_synthetic"))
        synthetic_evidence_count = sum(1 for c in compared for r in c.references if r.get("is_synthetic"))
        pass_fail_reasons = [f"{name}: {'PASS' if passed else 'FAIL'}" for name, passed, *_ in checks]

        if args.as_json:
            payload = {
                "facility": facility_name,
                "coverage": args.coverage,
                "fixture": FIXTURE_PATH.name,
                "line_count": header_total,
                "seed": {"facilities": len(status["facilities"]), "real": len(status["real"]), "synthetic": len(status["synthetic"])},
                "scenario": {
                    "name": scenario,
                    "expected_status_distribution": expected_distribution,
                    "observed_status_distribution": observed_distribution,
                    "real_evidence_count": real_evidence_count,
                    "synthetic_evidence_count": synthetic_evidence_count,
                    "pass_fail_reasons": pass_fail_reasons,
                },
                "summary": summary,
                "checks": {name: passed for name, passed, *_ in checks},
                "verdict": verdict,
            }
            print(json.dumps(payload, indent=2))
        else:
            report_lines.append("BILLBUSTER DEMO VERIFICATION")
            report_lines.append(f"facility   {facility_name}")
            report_lines.append(f"coverage   {args.coverage}")
            report_lines.append(f"fixture    {FIXTURE_PATH.name} ({header_total} lines)")
            report_lines.append("")
            report_lines.append("SEED")
            report_lines.append(
                f"  facilities {len(status['facilities'])} | price records {len(status['all_records'])} | codes {','.join(status['distinct_codes'])}"
            )
            real_flag = "  <-- flag if real == 0" if len(status["real"]) == 0 else ""
            report_lines.append(f"  real {len(status['real'])} | synthetic {len(status['synthetic'])}{real_flag}")
            report_lines.append("")
            report_lines.append("SCENARIO")
            report_lines.append(f"  scenario                    {scenario}")
            report_lines.append(f"  expected status distribution {expected_distribution}")
            report_lines.append(f"  observed status distribution {observed_distribution}")
            report_lines.append(f"  real evidence count          {real_evidence_count}")
            report_lines.append(f"  synthetic evidence count     {synthetic_evidence_count}")
            for reason in pass_fail_reasons:
                report_lines.append(f"  {reason}")
            report_lines.append("")
            report_lines.append("RESULT COUNTS")
            report_lines.append(f"  compared           {summary['compared']}")
            report_lines.append(f"  context_only       {summary['context_only']}")
            report_lines.append(f"  insufficient_data  {summary['insufficient_data']}")
            report_lines.append(f"  total              {summary['total']}")
            report_lines.append(f"  header count matches status count: {'YES' if header_total == summary['total'] else 'NO'}")
            report_lines.append("")
            if compared:
                report_lines.append("COMPARED LINES")
                for c in compared:
                    line = by_line[c.line_id]
                    subject_label = SUBJECT_LABELS.get(c.comparison_subject.type, c.comparison_subject.type)
                    benchmark_label = BENCHMARK_LABELS.get(c.benchmark.basis, c.benchmark.basis)
                    ref = c.references[0] if c.references else {}
                    is_synth = any(r.get("is_synthetic") for r in c.references)
                    report_lines.append(f"  {line.code}  {line.description}")
                    report_lines.append(f"    subject    {subject_label:<22} {money_cents(c.comparison_subject.money.amount_cents)}")
                    report_lines.append(f"    benchmark  {benchmark_label:<22} {money_cents(c.benchmark.median.amount_cents)}")
                    # direction drives the copy -- never infer wording from the signed
                    # percent string (this is the exact bug Fix 1 exists to catch).
                    abs_percent = c.percent_above_benchmark.lstrip("-") if c.percent_above_benchmark else None
                    abs_diff = money(abs(Decimal(str(c.difference.amount_cents)) / 100))
                    if c.direction == "matches":
                        report_lines.append("    difference matches the benchmark exactly")
                    else:
                        report_lines.append(
                            f"    difference {abs_diff} {c.direction} the {benchmark_label} ({abs_percent}% {c.direction})"
                        )
                    components = ", ".join(c.score_components["available"]) if c.score_components else "?"
                    report_lines.append(f"    score      {c.review_score}  {c.review_label}   [{components}]")
                    report_lines.append(f"    tier       {c.benchmark.match_tier}   confidence {c.benchmark.confidence}")
                    report_lines.append(
                        f"    source     {redact_query(ref.get('source_url'))}  effective {ref.get('effective_date')}  retrieved {ref.get('retrieval_date')}"
                    )
                    report_lines.append(f"    synthetic  {'YES' if is_synth else 'no'}" + ("                                <-- flag" if is_synth else ""))
                    report_lines.append("")
            else:
                report_lines.append("COMPARED LINES: none")
                report_lines.extend(diagnose_zero_compared(comparisons, lines))
                report_lines.append("")

            if findings:
                report_lines.append("FINDINGS (aggregated)")
                for f in findings:
                    report_lines.append(f"  {f.finding_type:<20}  {f.count} lines   {f.action}")
                report_lines.append("")

            report_lines.append("DEMO GATE")
            for entry in checks:
                name, passed = entry[0], entry[1]
                report_lines.append(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            report_lines.append("")
            report_lines.append(f"VERDICT  {verdict}")
            print("\n".join(report_lines))

        exit_code = 0 if blocking_pass else 1
        return exit_code

    finally:
        # 6. Delete the case. Always.
        if case is not None:
            await case_lifecycle.purge_case(private_db, case)
        await store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
