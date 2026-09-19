import enum


class CodeType(str, enum.Enum):
    CPT = "CPT"
    HCPCS = "HCPCS"
    CPT_HCPCS = "CPT_HCPCS"
    MS_DRG = "MS_DRG"
    APC = "APC"
    REVENUE = "REVENUE"
    NDC = "NDC"
    LOCAL = "LOCAL"
    UNKNOWN = "UNKNOWN"


class CareSetting(str, enum.Enum):
    INPATIENT = "inpatient"
    OUTPATIENT = "outpatient"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


class CoverageType(str, enum.Enum):
    UNINSURED = "uninsured"
    COMMERCIAL = "commercial"
    MEDICARE_ADVANTAGE = "medicare_advantage"
    MEDICAID_MANAGED = "medicaid_managed"
    MEDICARE_FFS = "medicare_ffs"
    OTHER = "other"
    UNKNOWN = "unknown"


class ChargeType(str, enum.Enum):
    GROSS = "gross"
    DISCOUNTED_CASH = "discounted_cash"
    PAYER_NEGOTIATED = "payer_negotiated"
    DEIDENTIFIED_MIN = "deidentified_min"
    DEIDENTIFIED_MAX = "deidentified_max"
    ALLOWED_P10 = "allowed_p10"
    ALLOWED_MEDIAN = "allowed_median"
    ALLOWED_P90 = "allowed_p90"
    MEDICARE_AVG_PAYMENT = "medicare_avg_payment"


class Confidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class AnalysisStatus(str, enum.Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"


class FacilityType(str, enum.Enum):
    HOSPITAL = "hospital"
    HOSPITAL_OUTPATIENT = "hospital_outpatient"
    URGENT_CARE = "urgent_care"
    OTHER = "other"


class MapAmountType(str, enum.Enum):
    GROSS = "gross"
    DISCOUNTED_CASH = "discounted_cash"
    PAYER_NEGOTIATED = "payer_negotiated"
    DEIDENTIFIED_MIN = "deidentified_min"
    DEIDENTIFIED_MAX = "deidentified_max"
    ALLOWED_P10 = "allowed_p10"
    ALLOWED_MEDIAN = "allowed_median"
    ALLOWED_P90 = "allowed_p90"
    MEDICARE_FFS_OBSERVED = "medicare_ffs_observed"
    APCD_ALLOWED_AGGREGATE = "apcd_allowed_aggregate"


class EvidenceAvailability(str, enum.Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    REGIONAL_CONTEXT = "regional_context"
    UNAVAILABLE = "unavailable"


class ObservedOrPublished(str, enum.Enum):
    PUBLISHED = "published"
    OBSERVED_AGGREGATE = "observed_aggregate"
    USER_ENTERED = "user_entered"


class ChargeScope(str, enum.Enum):
    FACILITY = "facility"
    PROFESSIONAL = "professional"
    UNKNOWN = "unknown"


class Transport(str, enum.Enum):
    REST = "rest"
    MCP = "mcp"
    INTERNAL = "internal"


class CopayInteraction(str, enum.Enum):
    IN_ADDITION = "in_addition"
    INSTEAD_OF = "instead_of"
    UNKNOWN = "unknown"


class Language(str, enum.Enum):
    EN = "en"
    ES = "es"


class PacketGoal(str, enum.Enum):
    BILLING_REVIEW = "billing_review"
    CASH_PRICE_MATCH = "cash_price_match"
    DISCOUNT = "discount"
    PAYMENT_PLAN = "payment_plan"
    FINANCIAL_ASSISTANCE = "financial_assistance"
    INSURANCE_APPEAL = "insurance_appeal"
