from datetime import UTC, datetime, timedelta

from billproof.config import get_settings
from billproof.models import BillLine, Case
from billproof.schemas.cases import CaseCreate
from billproof.services.case_auth import generate_token, hash_token


async def create_case(db, data: CaseCreate) -> tuple[Case, str]:
    token = generate_token()
    ttl = get_settings().case_ttl_hours
    case = Case(
        access_token_hash=hash_token(token),
        hospital_id=data.hospital_id,
        coverage_type=data.coverage_type.value,
        payer_name=data.payer_name,
        plan_name=data.plan_name,
        care_setting=data.care_setting.value,
        service_month=data.service_month,
        language=data.language.value,
        external_processing_consent=data.external_processing_consent,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl),
    )
    await db["cases"].insert_one(case.to_doc())
    return case, token


async def get_case(db, case_id: str) -> Case | None:
    doc = await db["cases"].find_one({"_id": case_id})
    return Case.from_doc(doc) if doc else None


async def get_case_by_token(db, token: str) -> Case | None:
    doc = await db["cases"].find_one({"access_token_hash": hash_token(token)})
    return Case.from_doc(doc) if doc else None


async def delete_case(db, case_id: str) -> None:
    await db["cases"].delete_one({"_id": case_id})


async def create_bill_lines(db, case_id: str, inputs, *, confirmed: bool) -> list[BillLine]:
    lines = []
    for item in inputs:
        line = BillLine(
            case_id=case_id,
            code_raw=item.code_raw,
            code=item.code,
            code_type=item.code_type.value,
            modifiers=item.modifiers,
            description=item.description,
            units=item.units,
            rate_unit=item.rate_unit,
            billed_amount=item.billed_amount,
            allowed_amount=item.allowed_amount,
            insurer_paid=item.insurer_paid,
            patient_responsibility=item.patient_responsibility,
            charge_scope=item.charge_scope.value,
            care_setting=item.care_setting.value,
            confirmed=confirmed,
        )
        await db["bill_lines"].insert_one(line.to_doc())
        lines.append(line)
    return lines


async def get_bill_lines(db, case_id: str) -> list[BillLine]:
    docs = await db["bill_lines"].find({"case_id": case_id}).to_list()
    return [BillLine.from_doc(d) for d in docs]


async def get_bill_line(db, line_id: str) -> BillLine | None:
    doc = await db["bill_lines"].find_one({"_id": line_id})
    return BillLine.from_doc(doc) if doc else None


async def save_bill_line(db, line: BillLine) -> None:
    await db["bill_lines"].update_one({"_id": line.id}, {"$set": line.to_set()})
