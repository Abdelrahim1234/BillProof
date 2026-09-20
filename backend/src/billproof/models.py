"""Domain/document models, persisted via billproof.store.

Every model's money fields (``MONEY_FIELDS``) round-trip as signed integer
cents in storage (never a float) while staying plain ``Decimal`` dollars
everywhere in Python.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


class StoredModel(BaseModel):
    """Base for every persisted document. ``id`` <-> the store's ``_id``."""

    model_config = ConfigDict(populate_by_name=True)

    # Field names (per-subclass) that are Decimal money and must be stored as
    # integer cents; DECIMAL_FIELDS are non-money Decimals (units, rates)
    # stored as strings so precision is never lost to float.
    MONEY_FIELDS: ClassVar[frozenset[str]] = frozenset()
    DECIMAL_FIELDS: ClassVar[frozenset[str]] = frozenset()
    DATE_FIELDS: ClassVar[frozenset[str]] = frozenset()

    id: str = Field(default_factory=_uuid)

    def to_doc(self) -> dict:
        doc = self.model_dump(mode="python")
        doc["_id"] = doc.pop("id")
        for f in self.MONEY_FIELDS:
            if doc.get(f) is not None:
                doc[f] = _cents(doc[f])
        for f in self.DECIMAL_FIELDS:
            if doc.get(f) is not None:
                doc[f] = str(doc[f])
        for f in self.DATE_FIELDS:
            if doc.get(f) is not None:
                doc[f] = doc[f].isoformat()
        return doc

    def to_set(self) -> dict:
        """Same as to_doc() but without ``_id`` -- for ``$set`` update payloads
        (the store rejects modifying ``_id`` even to its own value)."""
        doc = self.to_doc()
        doc.pop("_id", None)
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> "StoredModel":
        data = dict(doc)
        data["id"] = data.pop("_id")
        for f in cls.MONEY_FIELDS:
            if data.get(f) is not None:
                data[f] = Decimal(data[f]) / 100
        for f in cls.DECIMAL_FIELDS:
            if data.get(f) is not None:
                data[f] = Decimal(data[f])
        for f in cls.DATE_FIELDS:
            if data.get(f) is not None:
                data[f] = date.fromisoformat(data[f])
        return cls(**data)


class Facility(StoredModel):
    """Generalized from the original `hospitals` table -- see docs/05-proofmap.md."""

    facility_id: str | None = None  # CMS CCN
    organization_npi: str | None = None
    taxonomy: str | None = None
    facility_type: str = "hospital"
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    hospital_type: str | None = None
    ownership: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    financial_assistance_url: str | None = None
    billing_url: str | None = None
    public_price_url: str | None = None
    verification_source: str | None = None
    verification_date: date | None = None
    cms_updated_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)

    DATE_FIELDS = frozenset({"verification_date"})


class FacilitySource(StoredModel):
    hospital_id: str
    source_type: str  # cms_mrf | cms_provider | cms_medicare | ...
    source_url: str  # resolved origin only, no query/userinfo/fragment
    citation_url: str | None = None  # stable official hospital page
    schema_version: str | None = None
    file_date: date | None = None
    retrieved_at: datetime = Field(default_factory=_now)
    sha256: str
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    active: bool = True

    DATE_FIELDS = frozenset({"file_date"})


class PriceRecord(StoredModel):
    hospital_id: str
    code_type: str
    code: str
    modifier: str | None = None
    description: str | None = None
    care_setting: str = "unknown"
    charge_scope: str = "unknown"
    charge_type: str
    payer_name: str | None = None
    payer_normalized: str | None = None
    plan_name: str | None = None
    plan_normalized: str | None = None
    amount: Decimal | None = None
    currency: str = "USD"
    rate_unit: str | None = None
    rate_method: str | None = None
    allowed_count: int | None = None
    mrf_date: date | None = None
    source_url: str  # resolved origin only, no query/userinfo/fragment -- never a signed retrieval URL
    citation_url: str | None = None  # stable official hospital page a human can visit; what the API surfaces
    source_record_locator: str | None = None
    # Which ingestion path wrote this row (e.g. "cms_mrf_verified_extract" vs "cms_mrf").
    # Two different ingestion runs can share one FacilitySource (same file, matched by
    # sha256), so reconciliation can't tell them apart via source_url alone -- it must
    # key on this field instead. See scripts/seed.py's CURATED_SOURCE_TYPES.
    source_type: str | None = None
    is_synthetic: bool = False
    created_at: datetime = Field(default_factory=_now)

    MONEY_FIELDS = frozenset({"amount"})
    DATE_FIELDS = frozenset({"mrf_date"})


class MedicareBenchmark(StoredModel):
    hospital_id: str
    code_type: str  # P0: MS_DRG or APC only
    code: str
    service_count: int | None = None
    average_submitted_charge: Decimal | None = None
    average_total_payment: Decimal | None = None
    average_medicare_payment: Decimal | None = None
    data_year: int
    source_url: str
    suppressed: bool = False

    MONEY_FIELDS = frozenset(
        {"average_submitted_charge", "average_total_payment", "average_medicare_payment"}
    )


class Case(StoredModel):
    access_token_hash: str
    hospital_id: str | None = None
    coverage_type: str = "unknown"
    payer_name: str | None = None
    plan_name: str | None = None
    care_setting: str = "unknown"
    service_month: str | None = None  # YYYY-MM
    language: str = "en"
    external_processing_consent: bool = False
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime


class BillLine(StoredModel):
    case_id: str
    code_raw: str | None = None
    code: str | None = None
    code_type: str = "UNKNOWN"
    modifiers: list[str] = Field(default_factory=list)
    description: str | None = None
    units: Decimal = Decimal(1)
    rate_unit: str | None = None
    billed_amount: Decimal | None = None
    allowed_amount: Decimal | None = None
    insurer_paid: Decimal | None = None
    patient_responsibility: Decimal | None = None
    charge_scope: str = "unknown"
    care_setting: str = "unknown"
    extraction_confidence: str | None = None
    needs_manual_review: bool = False
    confirmed: bool = False
    version: int = 1  # optimistic-lock counter for PATCH
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    MONEY_FIELDS = frozenset({"billed_amount", "allowed_amount", "insurer_paid", "patient_responsibility"})
    DECIMAL_FIELDS = frozenset({"units"})


class Analysis(StoredModel):
    case_id: str
    input_hash: str
    status: str
    result_json: dict
    created_at: datetime = Field(default_factory=_now)


class Packet(StoredModel):
    case_id: str
    goal: str
    language: str
    packet_json: dict
    markdown: str
    created_at: datetime = Field(default_factory=_now)


class ActivityReceipt(StoredModel):
    case_id: str
    transport: str  # rest | mcp | internal
    tool_name: str
    display_name: str
    status: str
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


class ScreenSubmission(StoredModel):
    """Privacy-reduced display copy for the opt-in presentation wall."""

    case_id: str
    room_code: str
    source_label: str
    hospital_name: str | None = None
    coverage_type: str
    is_demo_bill: bool = False
    analysis_json: dict
    lines_json: list[dict]
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime


# --- ProofMap additions (docs/05-proofmap.md) ---


class ServiceBundle(StoredModel):
    display_name: str
    normalized_service_key: str
    code: str
    code_type: str
    setting: str = "unknown"
    charge_scope: str = "unknown"
    included_components: list[str] = Field(default_factory=list)
    excluded_components: list[str] = Field(default_factory=list)
    caveat: str | None = None


class RegionalBenchmark(StoredModel):
    geography_type: str  # zip | county | msa | state
    geography_code: str
    service_code: str
    code_type: str
    amount_type: str
    observed_or_published: str
    payer_category: str | None = None
    plan_name: str | None = None
    p10: Decimal | None = None
    median: Decimal | None = None
    p90: Decimal | None = None
    sample_count: int | None = None
    provider_count: int | None = None
    data_year: int | None = None
    source_url: str
    suppressed: bool = False
    limitations: list[str] = Field(default_factory=list)

    MONEY_FIELDS = frozenset({"p10", "median", "p90"})


class PlanBenefitProfile(StoredModel):
    """Case-scoped only. Never store member or group IDs (invariant 9)."""

    case_id: str
    network_status: str | None = None
    deductible_applicability: bool | None = None
    deductible_remaining: Decimal | None = None
    copay: Decimal | None = None
    coinsurance_rate: Decimal | None = None
    remaining_oop_max: Decimal | None = None
    copay_interaction: str = "unknown"
    assumptions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    MONEY_FIELDS = frozenset({"deductible_remaining", "copay", "remaining_oop_max"})
    DECIMAL_FIELDS = frozenset({"coinsurance_rate"})


class CaseEvidence(StoredModel):
    case_id: str
    bill_line_id: str | None = None
    facility_id: str | None = None
    regional_benchmark_id: str | None = None
    match_tier: str | None = None
    confidence: str
    snapshot_json: dict  # immutable facts + source + limitations
    created_at: datetime = Field(default_factory=_now)


class FacilityAssistance(StoredModel):
    facility_id: str
    policy_url: str | None = None
    application_url: str | None = None
    billing_phone: str | None = None
    languages: list[str] = Field(default_factory=list)
    summary: str | None = None
    source_url: str
    last_verified_date: date | None = None

    DATE_FIELDS = frozenset({"last_verified_date"})


# --- Explain-my-bill (CODEX_IMPLEMENTATION_SPEC.md #12) ---


class BillingGlossaryEntry(StoredModel):
    term: str
    slug: str
    explanation: str
    source_url: str
    publisher: str
    retrieval_date: date
    content_hash: str

    DATE_FIELDS = frozenset({"retrieval_date"})
