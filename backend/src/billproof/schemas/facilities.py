from datetime import date, datetime

from pydantic import BaseModel


class FacilityOut(BaseModel):
    id: str
    facility_id: str | None
    facility_type: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    latitude: float | None
    longitude: float | None
    financial_assistance_url: str | None
    billing_url: str | None
    public_price_url: str | None
    verification_source: str | None
    verification_date: date | None

    model_config = {"from_attributes": True}


class FacilitySourceOut(BaseModel):
    id: str
    source_type: str
    source_url: str
    schema_version: str | None
    file_date: date | None
    retrieved_at: datetime
    sha256: str
    active: bool

    model_config = {"from_attributes": True}


class FacilityDetail(FacilityOut):
    sources: list[FacilitySourceOut] = []
