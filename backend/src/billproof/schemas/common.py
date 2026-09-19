from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class Money(BaseModel):
    amount_cents: int
    currency: str = "USD"

    @classmethod
    def from_decimal(cls, value: Decimal | None, currency: str = "USD") -> "Money | None":
        if value is None:
            return None
        return cls(amount_cents=int((value * 100).to_integral_value()), currency=currency)

    def to_decimal(self) -> Decimal:
        return Decimal(self.amount_cents) / 100


class SourceCitation(BaseModel):
    price_record_id: str | None = None
    source_url: str
    publisher: str
    effective_date: date | None = None
    retrieval_date: date
    source_record_locator: str | None = None
    is_synthetic: bool = False


class ActivityReceiptOut(BaseModel):
    id: str
    transport: str
    tool_name: str
    display_name: str
    status: str
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    retryable: bool = False
    details: dict = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
    request_id: str


def percent_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))
