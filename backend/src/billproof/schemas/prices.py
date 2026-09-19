from datetime import date

from pydantic import BaseModel

from billproof.schemas.common import Money, SourceCitation


class PriceReference(BaseModel):
    price_record_id: str
    charge_type: str
    amount: Money | None
    payer_name: str | None = None
    plan_name: str | None = None
    care_setting: str
    mrf_date: date | None = None
    source_record_locator: str | None = None
    is_synthetic: bool
    source: SourceCitation


class BenchmarkSummary(BaseModel):
    basis: str
    low: Money | None
    median: Money | None
    high: Money | None
    sample_size: int
    match_tier: str
    confidence: str
    limitations: list[str] = []
