import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from billproof.api.dependencies import (
    get_authenticated_case,
    get_current_case,
    get_private_db,
    get_public_db,
)
from billproof.errors import forbidden, not_found, ok
from billproof.models import BillLine, Case
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.schemas.cases import CaseCreate, CaseCreated, CaseOut
from billproof.services import activity
from billproof.services.case_lifecycle import purge_case

router = APIRouter(prefix="/api/v1", tags=["cases"])

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures"
HERO_SAMPLE_ID = "nrv_cash_review"


class DemoCaseRequest(BaseModel):
    sample: str | None = None


@router.get("/demo/samples")
async def demo_samples(public_db=Depends(get_public_db)):
    facility = (
        await hospitals_repo.search_active_facilities(
            public_db, name="LewisGale Hospital Montgomery", limit=1
        )
    )
    return ok(
        [
            {
                "id": HERO_SAMPLE_ID,
                "title": "Two hospital charges, two different conclusions",
                "blurb": (
                    "A synthetic, identifier-free bill with one line above and one line below "
                    "LewisGale Montgomery's published cash prices."
                ),
                "hospital_name": facility[0].name if facility else None,
                "coverage_type": "uninsured",
                "line_count": 2,
            }
        ]
    )


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


@router.post("/cases", status_code=201)
async def create_case(payload: CaseCreate, private_db=Depends(get_private_db), public_db=Depends(get_public_db)):
    if payload.hospital_id and not await hospitals_repo.get_active_facility(public_db, payload.hospital_id):
        raise not_found("Hospital")
    case, token = await cases_repo.create_case(private_db, payload)
    return ok(
        CaseCreated(case_id=case.id, access_token=token, expires_at=case.expires_at).model_dump(mode="json")
    )


@router.post("/demo/cases", status_code=201)
async def create_demo_case(
    payload: DemoCaseRequest | None = None,
    private_db=Depends(get_private_db),
    public_db=Depends(get_public_db),
):
    """Clones the stable synthetic demo fixture into a fresh case. Must work
    fully offline (docs/04) -- everything here reads local fixtures only."""
    sample = payload.sample if payload else None
    if sample not in (None, HERO_SAMPLE_ID):
        raise not_found("Demo sample")

    expected = json.loads((FIXTURE_DIR / "demo_bill_expected.json").read_text())
    if sample == HERO_SAMPLE_ID:
        expected = {
            "hospital_name": "LewisGale Hospital Montgomery",
            "coverage_type": "uninsured",
            "payer_name": None,
            "plan_name": None,
            "service_month": "2026-09",
            "lines": [
                {
                    "code": "80053",
                    "code_type": "CPT",
                    "description": "Comprehensive metabolic panel",
                    "care_setting": "outpatient",
                    "charge_scope": "unknown",
                    "units": "1",
                    "billed_amount": "1385.59",
                },
                {
                    "code": "71046",
                    "code_type": "CPT",
                    "description": "Chest X-ray, 2 views",
                    "care_setting": "outpatient",
                    "charge_scope": "unknown",
                    "units": "1",
                    "billed_amount": "1100.00",
                },
            ],
        }
    matches = await hospitals_repo.search_active_facilities(
        public_db, name=expected["hospital_name"], limit=1
    )
    facility = matches[0] if matches else None
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
        # The demo bill is a synthetic fixture (no real patient data), so the
        # AI explain/ask feature can be enabled by default here without the
        # privacy tradeoff a real user's case would have.
        external_processing_consent=True,
    )
    case, token = await cases_repo.create_case(private_db, payload)

    for line in expected["lines"]:
        await private_db["bill_lines"].insert_one(
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
            ).to_doc()
        )

    await activity.record(
        private_db,
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
            "sample": sample or "insured_eob",
            "title": "Two hospital charges, two different conclusions"
            if sample == HERO_SAMPLE_ID
            else "Synthetic insured-bill example",
        }
    )


@router.get("/cases/{case_id}")
async def get_case(case_id: str, current: Case = Depends(get_current_case)):
    _require_matching_case(case_id, current)
    return ok(CaseOut.model_validate(current, from_attributes=True).model_dump(mode="json"))


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: str,
    current: Case = Depends(get_authenticated_case),
    db=Depends(get_private_db),
):
    _require_matching_case(case_id, current)
    await purge_case(db, current)
