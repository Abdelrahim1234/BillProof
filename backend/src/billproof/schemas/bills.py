from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from billproof.enums import CareSetting, ChargeScope, CodeType


class BillLineInput(BaseModel):
    # extra="forbid": protected traits have no field here and are rejected
    # outright rather than silently ignored (docs/03).
    model_config = {"extra": "forbid"}

    code_raw: str | None = None
    code: str | None = None
    code_type: CodeType = CodeType.UNKNOWN
    modifiers: list[str] = Field(default_factory=list)
    description: str | None = None
    units: Decimal = Decimal(1)
    rate_unit: str | None = None
    billed_amount: Decimal | None = None
    allowed_amount: Decimal | None = None
    insurer_paid: Decimal | None = None
    patient_responsibility: Decimal | None = None
    charge_scope: ChargeScope = ChargeScope.UNKNOWN
    care_setting: CareSetting = CareSetting.UNKNOWN


class ExtractedLineCandidate(BillLineInput):
    extraction_confidence: str = "low"
    needs_manual_review: bool = True
    warnings: list[str] = Field(default_factory=list)


class BillDocument(BaseModel):
    lines: list[ExtractedLineCandidate]
    needs_manual_entry: bool = False
    warnings: list[str] = Field(default_factory=list)


class BulkConfirmRequest(BaseModel):
    lines: list[BillLineInput]


class BillLineOut(BaseModel):
    id: str
    code: str | None
    code_type: str
    modifiers: list[str]
    description: str | None
    units: Decimal
    billed_amount: Decimal | None
    allowed_amount: Decimal | None
    insurer_paid: Decimal | None
    patient_responsibility: Decimal | None
    charge_scope: str
    care_setting: str
    confirmed: bool
    needs_manual_review: bool
    version: int
    created_at: datetime
    updated_at: datetime
