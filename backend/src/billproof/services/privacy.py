import re
from datetime import date, datetime

from billproof.models import PriceRecord
from billproof.schemas.common import Money, SourceCitation
from billproof.schemas.prices import PriceReference

# Invariant 9: no patient name, DOB, street address, account number, MRN,
# member ID, email, or phone may reach extraction, storage, or logs.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_DOB_LABELED = re.compile(
    r"(?i)\b(DOB|date of birth|birth date)\b\s*[:\-]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_LABELED_ID = re.compile(
    r"(?i)\b(account\s*(no\.?|number|#)|MRN|member\s*id|subscriber\s*id|patient\s*id)\b\s*[:\-]?\s*[A-Za-z0-9-]+"
)
_STREET_ADDRESS = re.compile(
    r"(?i)\b\d{1,6}\s+([A-Za-z0-9.'-]+\s){1,5}"
    r"(street|st|avenue|ave|road|rd|drive|dr|lane|ln|way|blvd|boulevard|court|ct)\b\.?"
)
_BARCODE = re.compile(r"(?i)\*[A-Za-z0-9]{6,}\*")


def mask_identity_fields(text: str) -> str:
    """Redact PII before any parsing or external call touches the text."""
    text = _EMAIL.sub("[REDACTED]", text)
    text = _PHONE.sub("[REDACTED]", text)
    text = _DOB_LABELED.sub("[REDACTED]", text)
    text = _SSN.sub("[REDACTED]", text)
    text = _LABELED_ID.sub("[REDACTED]", text)
    text = _STREET_ADDRESS.sub("[REDACTED]", text)
    text = _BARCODE.sub("[REDACTED]", text)
    return text


def price_reference(record: PriceRecord) -> PriceReference:
    return PriceReference(
        price_record_id=record.id,
        charge_type=record.charge_type,
        amount=Money.from_decimal(record.amount),
        payer_name=record.payer_name,
        plan_name=record.plan_name,
        care_setting=record.care_setting,
        mrf_date=record.mrf_date,
        source_record_locator=record.source_record_locator,
        is_synthetic=record.is_synthetic,
        source=citation_for_price_record(record),
    )


def citation_for_price_record(record: PriceRecord) -> SourceCitation:
    effective = record.mrf_date if isinstance(record.mrf_date, date) else None
    return SourceCitation(
        price_record_id=record.id,
        source_url=record.source_url,
        publisher="hospital MRF" if not record.is_synthetic else "synthetic fixture",
        effective_date=effective,
        retrieval_date=record.created_at.date()
        if isinstance(record.created_at, datetime)
        else date.today(),
        source_record_locator=record.source_record_locator,
        is_synthetic=record.is_synthetic,
    )
