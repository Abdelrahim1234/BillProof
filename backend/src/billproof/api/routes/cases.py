import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import forbidden, not_found, ok
from billproof.models import BillLine, Case
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.schemas.cases import CaseCreate, CaseCreated, CaseOut
from billproof.services import activity
from billproof.services.case_lifecycle import purge_case

router = APIRouter(prefix="/api/v1", tags=["cases"])

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures"


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


@router.post("/cases", status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    if payload.hospital_id and not hospitals_repo.get_facility(db, payload.hospital_id):
        raise not_found("Hospital")
    case, token = cases_repo.create_case(db, payload)
    return ok(
        CaseCreated(case_id=case.id, access_token=token, expires_at=case.expires_at).model_dump(mode="json")
    )


@router.post("/demo/cases", status_code=201)
def create_demo_case(db: Session = Depends(get_db)):
    """Clones the stable synthetic demo fixture into a fresh case. Must work
    fully offline (docs/04) -- everything here reads local fixtures only."""
    expected = json.loads((FIXTURE_DIR / "demo_bill_expected.json").read_text())
    facility = next(
        (f for f in hospitals_repo.search_facilities(db, name=expected["hospital_name"], limit=1)), None
    )
    if not facility:
        raise not_found("Demo hospital (run scripts/seed.py first)")

    payload = CaseCreate(
        hospital_id=facility.id,
        coverage_type=expected["coverage_type"],
        payer_name=expected["payer_name"],
        plan_name=expected["plan_name"],
        care_setting="outpatient",
        service_month=expected.get("service_month"),
        language="en",
    )
    case, token = cases_repo.create_case(db, payload)

    for line in expected["lines"]:
        db.add(
            BillLine(
                case_id=case.id,
                code_raw=line["code"],
                code=line["code"],
                code_type=line["code_type"],
                description=line["description"],
                units=line["units"],
                billed_amount=line.get("billed_amount"),
                allowed_amount=line.get("allowed_amount"),
                patient_responsibility=line.get("patient_responsibility"),
                care_setting=line["care_setting"],
                charge_scope=line.get("charge_scope", "unknown"),
                extraction_confidence="high",
                needs_manual_review=False,
                confirmed=True,
            )
        )
    db.commit()

    activity.record(
        db,
        case_id=case.id,
        transport="internal",
        tool_name="create_demo_case",
        display_name="Demo case created",
        status="success",
        summary=f"Loaded {len(expected['lines'])} synthetic demo bill line items.",
    )

    return ok(
        {
            "case_id": case.id,
            "access_token": token,
            "expires_at": case.expires_at.isoformat(),
            "is_demo": True,
        }
    )


@router.get("/cases/{case_id}")
def get_case(case_id: str, current: Case = Depends(get_current_case)):
    _require_matching_case(case_id, current)
    return ok(CaseOut.model_validate(current, from_attributes=True).model_dump(mode="json"))


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    _require_matching_case(case_id, current)
    purge_case(db, current)
    db.commit()

