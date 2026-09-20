"""The catalogue of synthetic sample bills behind POST /demo/cases.

Every sample is a checked-in fixture, so the demo works with no internet at all
(docs/04). Each one is clearly synthetic: the patient side of the bill is made
up, while the prices it gets compared against are the real published hospital
files loaded by scripts/seed.py.

Samples exist to show different honest outcomes -- a large gap, a reasonable
bill, paperwork findings, and codes with no published price -- so a reviewer can
see the tool decline to score as readily as it scores.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from billproof.errors import AppError, not_found
from billproof.models import BillLine
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.schemas.cases import CaseCreate

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "data" / "fixtures"
SAMPLE_DIR = FIXTURE_DIR / "samples"

# The original fixture keeps its own path so existing callers and tests that
# post no body at all get exactly the bill they always got.
DEFAULT_SAMPLE_ID = "insured_visit"
_DEFAULT_FILE = FIXTURE_DIR / "demo_bill_expected.json"
_DEFAULT_META = {
    "title": "Insured clinic visit",
    "blurb": "An insured bill with an EOB, compared against the plan's own published negotiated rate.",
}

# Display order on the start screen: lead with the flagship insured case.
_ORDER = [
    DEFAULT_SAMPLE_ID,
    "uninsured_emergency",
    "carilion_emergency",
    "uninsured_imaging",
    "full_itemized",
    "insured_no_eob",
    "fair_bill",
    "bill_with_problems",
    "nothing_to_compare",
]


def _load(sample_id: str) -> dict:
    if sample_id == DEFAULT_SAMPLE_ID:
        return json.loads(_DEFAULT_FILE.read_text(encoding="utf-8")) | _DEFAULT_META

    # Defend the path join: a sample id only ever names a file in SAMPLE_DIR.
    if not sample_id.replace("_", "").isalnum():
        raise AppError("UNKNOWN_SAMPLE", f"No sample bill named {sample_id!r}.", status_code=404)
    path = SAMPLE_DIR / f"{sample_id}.json"
    if not path.is_file():
        raise AppError("UNKNOWN_SAMPLE", f"No sample bill named {sample_id!r}.", status_code=404)
    return json.loads(path.read_text(encoding="utf-8"))


def catalogue() -> list[dict]:
    """What the start screen lists. Cheap enough to read from disk per call."""
    entries = []
    for sample_id in _ORDER:
        try:
            body = _load(sample_id)
        except (AppError, OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "id": sample_id,
                "title": body.get("title", sample_id),
                "blurb": body.get("blurb", ""),
                "hospital_name": body.get("hospital_name"),
                "coverage_type": body.get("coverage_type", "unknown"),
                "line_count": len(body.get("lines", [])),
            }
        )
    return entries


def create_case_from_sample(db: Session, sample_id: str):
    """Clones one sample into a fresh case with its lines already confirmed."""
    body = _load(sample_id)

    facility = next(
        (f for f in hospitals_repo.search_facilities(db, name=body["hospital_name"], limit=1)), None
    )
    if not facility:
        raise not_found("Demo hospital (run scripts/seed.py first)")

    case, token = cases_repo.create_case(
        db,
        CaseCreate(
            hospital_id=facility.id,
            coverage_type=body["coverage_type"],
            payer_name=body.get("payer_name"),
            plan_name=body.get("plan_name"),
            care_setting=body.get("care_setting", "outpatient"),
            service_month=body.get("service_month"),
            language="en",
        ),
    )

    for line in body["lines"]:
        db.add(
            BillLine(
                case_id=case.id,
                code_raw=line.get("code"),
                code=line.get("code"),
                code_type=line.get("code_type", "UNKNOWN"),
                description=line.get("description"),
                units=line.get("units", "1"),
                billed_amount=line.get("billed_amount"),
                allowed_amount=line.get("allowed_amount"),
                patient_responsibility=line.get("patient_responsibility"),
                care_setting=line.get("care_setting", "unknown"),
                charge_scope=line.get("charge_scope", "unknown"),
                extraction_confidence="high",
                needs_manual_review=False,
                confirmed=True,
            )
        )
    db.commit()
    return case, token, body
