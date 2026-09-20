import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from billproof.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


Money = Numeric(12, 2)


class Facility(Base):
    """Generalized from the original `hospitals` table — see docs/05-proofmap.md."""

    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    facility_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)  # CMS CCN
    organization_npi: Mapped[str | None] = mapped_column(String(10), nullable=True)
    taxonomy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    facility_type: Mapped[str] = mapped_column(String(30), default="hospital")
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(10))
    hospital_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ownership: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    financial_assistance_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    billing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    public_price_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cms_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sources: Mapped[list["FacilitySource"]] = relationship(back_populates="facility")


class FacilitySource(Base):
    __tablename__ = "hospital_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    source_type: Mapped[str] = mapped_column(String(50))  # cms_mrf | cms_provider | cms_medicare | ...
    source_url: Mapped[str] = mapped_column(String(500))
    schema_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    file_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    sha256: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    facility: Mapped[Facility] = relationship(back_populates="sources")


class PriceRecord(Base):
    __tablename__ = "price_records"
    __table_args__ = (
        Index("ix_price_records_hospital_code", "hospital_id", "code_type", "code"),
        Index(
            "ix_price_records_code_setting_charge",
            "code_type",
            "code",
            "care_setting",
            "charge_type",
        ),
        Index("ix_price_records_payer_plan", "payer_normalized", "plan_normalized"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    code_type: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(20))
    modifier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    care_setting: Mapped[str] = mapped_column(String(20), default="unknown")
    charge_scope: Mapped[str] = mapped_column(String(20), default="unknown")
    charge_type: Mapped[str] = mapped_column(String(30))
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    rate_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rate_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    allowed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrf_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(String(500))
    source_record_locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MedicareBenchmark(Base):
    __tablename__ = "medicare_benchmarks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    code_type: Mapped[str] = mapped_column(String(20))  # P0: MS_DRG or APC only
    code: Mapped[str] = mapped_column(String(20))
    service_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_submitted_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    average_total_payment: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    average_medicare_payment: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    data_year: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(String(500))
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    coverage_type: Mapped[str] = mapped_column(String(30), default="unknown")
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    care_setting: Mapped[str] = mapped_column(String(20), default="unknown")
    service_month: Mapped[str | None] = mapped_column(String(7), nullable=True)  # YYYY-MM
    language: Mapped[str] = mapped_column(String(2), default="en")
    external_processing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class BillLine(Base):
    __tablename__ = "bill_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    code_raw: Mapped[str | None] = mapped_column(String(50), nullable=True)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    code_type: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    modifiers: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    units: Mapped[Decimal] = mapped_column(Money, default=1)
    rate_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    billed_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    allowed_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    insurer_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    patient_responsibility: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    charge_scope: Mapped[str] = mapped_column(String(20), default="unknown")
    care_setting: Mapped[str] = mapped_column(String(20), default="unknown")
    extraction_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic-lock counter for PATCH
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Packet(Base):
    __tablename__ = "packets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    goal: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(2))
    packet_json: Mapped[dict] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ActivityReceipt(Base):
    __tablename__ = "activity_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    transport: Mapped[str] = mapped_column(String(10))  # rest | mcp | internal
    tool_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(500))
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --- ProofMap additions (docs/05-proofmap.md) ---


class ServiceBundle(Base):
    __tablename__ = "service_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    display_name: Mapped[str] = mapped_column(String(255))
    normalized_service_key: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str] = mapped_column(String(20))
    code_type: Mapped[str] = mapped_column(String(20))
    setting: Mapped[str] = mapped_column(String(20), default="unknown")
    charge_scope: Mapped[str] = mapped_column(String(20), default="unknown")
    included_components: Mapped[list] = mapped_column(JSON, default=list)
    excluded_components: Mapped[list] = mapped_column(JSON, default=list)
    caveat: Mapped[str | None] = mapped_column(String(500), nullable=True)


class RegionalBenchmark(Base):
    __tablename__ = "regional_benchmarks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    geography_type: Mapped[str] = mapped_column(String(30))  # zip | county | msa | state
    geography_code: Mapped[str] = mapped_column(String(20))
    service_code: Mapped[str] = mapped_column(String(20))
    code_type: Mapped[str] = mapped_column(String(20))
    amount_type: Mapped[str] = mapped_column(String(30))
    observed_or_published: Mapped[str] = mapped_column(String(20))
    payer_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    p10: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    median: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    p90: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str] = mapped_column(String(500))
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    limitations: Mapped[list] = mapped_column(JSON, default=list)


class PlanBenefitProfile(Base):
    """Case-scoped only. Never store member or group IDs (invariant 9)."""

    __tablename__ = "plan_benefit_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    network_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    deductible_applicability: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deductible_remaining: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    copay: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    coinsurance_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    remaining_oop_max: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    copay_interaction: Mapped[str] = mapped_column(String(20), default="unknown")
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CaseEvidence(Base):
    __tablename__ = "case_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    bill_line_id: Mapped[str | None] = mapped_column(ForeignKey("bill_lines.id"), nullable=True)
    facility_id: Mapped[str | None] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    regional_benchmark_id: Mapped[str | None] = mapped_column(
        ForeignKey("regional_benchmarks.id"), nullable=True
    )
    match_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20))
    snapshot_json: Mapped[dict] = mapped_column(JSON)  # immutable facts + source + limitations
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FacilityAssistance(Base):
    __tablename__ = "facility_assistance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"))
    policy_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    application_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    billing_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[str] = mapped_column(String(500))
    last_verified_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ScreenSubmission(Base):
    """One bill sent to a presentation screen (docs/04 demo surface).

    This is a *display copy*, not a second source of truth: it holds the
    already-computed analysis plus the line labels needed to render it, and
    never a case access token. Publishing replaces whatever the room held, so
    only the bill currently on screen is retained.
    """

    __tablename__ = "screen_submissions"
    __table_args__ = (Index("ix_screen_submissions_room", "room_code", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_code: Mapped[str] = mapped_column(String(32))
    case_id: Mapped[str] = mapped_column(String(36))
    source_label: Mapped[str] = mapped_column(String(50))
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
