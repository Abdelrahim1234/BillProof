import re
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit

from billproof.models import Facility, PriceRecord
from billproof.schemas.common import Money, SourceCitation
from billproof.schemas.facilities import FacilityOut
from billproof.schemas.prices import PriceReference

# CLAUDE_FINAL_DEMO_HARDENING Fix 2: a real MRF source URL (Azure Blob
# storage, this project's own experience) can carry a SAS signature -- a
# live, time-limited access credential -- in its query string. These
# parameter names are checked recursively against every response/log value;
# none may ever appear outside an explicitly fake test fixture.
SAS_PARAM_NAMES = frozenset({"sig", "se", "sp", "sv", "spr", "st", "sr", "skoid", "sktid"})


def strip_query(url: str | None) -> str | None:
    """Resolved origin only: scheme + host + path, no query/userinfo/fragment.
    The one place a retrieval URL is sanitized before it can reach storage,
    a response, or a log -- never persist or print the raw signed form."""
    if not url:
        return url
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def contains_sas_params(url: str | None) -> bool:
    if not url or "?" not in url:
        return False
    query = urlsplit(url).query
    param_names = {p.split("=", 1)[0].lower() for p in query.split("&") if p}
    return bool(param_names & SAS_PARAM_NAMES)


def find_sas_leak(value) -> str | None:
    """Recursively scans a JSON-shaped value (the exact recursive
    response/log safety test the hardening prompt requires) and returns a
    dotted path to the first leaked value found, or None. Never returns the
    leaked value itself -- callers must not print what this finds."""
    return _scan(value, "$")


def _scan(value, path: str) -> str | None:
    if isinstance(value, str):
        if contains_sas_params(value):
            return path
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            found = _scan(v, f"{path}.{k}")
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            found = _scan(v, f"{path}[{i}]")
            if found:
                return found
        return None
    return None

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
        code=record.code,
        code_type=record.code_type,
        description=record.description,
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


def public_facility(facility: Facility) -> FacilityOut:
    """Serialize a facility without ever returning credential-bearing URLs."""
    payload = FacilityOut.model_validate(facility).model_dump(mode="python")
    for field in (
        "financial_assistance_url",
        "billing_url",
        "public_price_url",
        "verification_source",
    ):
        payload[field] = strip_query(payload.get(field))
    return FacilityOut.model_validate(payload)


def citation_for_price_record(record: PriceRecord) -> SourceCitation:
    """The public-facing source_url is always the stable citation page when
    one is on file, otherwise the resolved (query-stripped) origin -- never
    the raw retrieval URL, even if one somehow reached storage unsanitized."""
    effective = record.mrf_date if isinstance(record.mrf_date, date) else None
    # Sanitize both candidates. A citation page is normally stable, but it is
    # still untrusted persisted input and must not get a query-string bypass.
    public_url = strip_query(record.citation_url) or strip_query(record.source_url)
    return SourceCitation(
        price_record_id=record.id,
        source_url=public_url,
        publisher="hospital MRF" if not record.is_synthetic else "synthetic fixture",
        effective_date=effective,
        retrieval_date=record.created_at.date()
        if isinstance(record.created_at, datetime)
        else date.today(),
        source_record_locator=record.source_record_locator,
        is_synthetic=record.is_synthetic,
    )
