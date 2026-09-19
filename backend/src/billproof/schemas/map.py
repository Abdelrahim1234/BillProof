from decimal import Decimal

from pydantic import BaseModel, Field

from billproof.schemas.common import Money, SourceCitation


class FacilitySearchResult(BaseModel):
    id: str
    name: str
    facility_type: str
    address: str
    city: str
    state: str
    zip_code: str
    latitude: float | None
    longitude: float | None
    distance_miles: float | None
    evidence_availability: str  # exact | partial | regional_context | unavailable


class PriceEvidenceItem(BaseModel):
    amount_type: str
    observed_or_published: str
    money: Money | None = None
    low: Money | None = None
    high: Money | None = None
    facility_id: str
    facility_name: str
    facility_type: str
    distance_miles: float | None = None
    code: str
    code_type: str
    care_setting: str
    charge_scope: str
    payer_name: str | None = None
    plan_name: str | None = None
    geography: str | None = None
    sample_count: int | None = None
    provider_count: int | None = None
    data_year: int | None = None
    match_tier: str
    confidence: str
    limitations: list[str] = Field(default_factory=list)
    source: SourceCitation
    is_synthetic: bool


class AreaBenchmarkOut(BaseModel):
    geography_type: str
    geography_code: str
    service_code: str
    code_type: str
    amount_type: str
    observed_or_published: str
    payer_category: str | None
    plan_name: str | None
    p10: Money | None
    median: Money | None
    p90: Money | None
    sample_count: int | None
    provider_count: int | None
    data_year: int | None
    source_url: str
    suppressed: bool
    limitations: list[str]


class OutOfPocketEstimateRequest(BaseModel):
    allowed_amount: Decimal
    network_status: str = "in_network"  # in_network | out_of_network | unknown
    deductible_applicability: bool = True
    remaining_deductible: Decimal | None = None
    copay: Decimal | None = None
    coinsurance_rate: Decimal | None = None
    copay_interaction: str = "unknown"  # in_addition | instead_of | unknown
    remaining_oop_max: Decimal | None = None


class OutOfPocketEstimateResponse(BaseModel):
    low: Money
    high: Money
    components: dict
    assumptions: list[str]
    unknowns: list[str]
    warnings: list[str]


class CaseEvidenceCreate(BaseModel):
    bill_line_id: str | None = None
    facility_id: str | None = None
    regional_benchmark_id: str | None = None


class CaseEvidenceOut(BaseModel):
    id: str
    case_id: str
    bill_line_id: str | None
    facility_id: str | None
    regional_benchmark_id: str | None
    match_tier: str | None
    confidence: str
    snapshot_json: dict
    created_at: str
