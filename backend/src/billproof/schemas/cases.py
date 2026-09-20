from datetime import datetime

from pydantic import BaseModel, Field

from billproof.enums import CareSetting, CoverageType, Language


class CaseCreate(BaseModel):
    # extra="forbid": protected traits (race, gender, name, ...) have no field
    # here and are rejected outright rather than silently ignored (docs/03).
    model_config = {"extra": "forbid"}

    hospital_id: str | None = None
    coverage_type: CoverageType = CoverageType.UNKNOWN
    payer_name: str | None = None
    plan_name: str | None = None
    care_setting: CareSetting = CareSetting.UNKNOWN
    service_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    language: Language = Language.EN
    external_processing_consent: bool = False


class CaseCreated(BaseModel):
    case_id: str
    access_token: str
    expires_at: datetime
    is_demo: bool = False


class CaseOut(BaseModel):
    id: str
    hospital_id: str | None
    coverage_type: str
    payer_name: str | None
    plan_name: str | None
    care_setting: str
    service_month: str | None
    language: str
    external_processing_consent: bool
    created_at: datetime
    expires_at: datetime
