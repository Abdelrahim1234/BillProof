from pydantic import BaseModel

from billproof.schemas.common import Money
from billproof.schemas.prices import BenchmarkSummary


class MatchDetails(BaseModel):
    hospital_exact: bool
    code_exact: bool
    setting_exact: bool
    modifier_exact: bool | None = None
    payer_exact: bool | None = None
    plan_exact: bool | None = None
    factors_used: list[str] = []
    missing_factors: list[str] = []


class ComparisonSubject(BaseModel):
    type: str  # billed_amount | patient_responsibility | allowed_amount
    money: Money


class LineComparison(BaseModel):
    line_id: str
    comparison_status: str  # compared | context_only | insufficient_data
    comparison_subject: ComparisonSubject | None = None
    benchmark: BenchmarkSummary | None = None
    difference: Money | None = None  # signed: negative means the subject is below the benchmark
    percent_above_benchmark: str | None = None  # signed, same sign convention as difference
    direction: str | None = None  # above | below | matches
    finding_type: str | None = None  # above_benchmark | below_benchmark | matches_benchmark
    reason_code: str | None = None  # e.g. exact_code_not_found, when comparison_status is insufficient_data
    review_score: int | None = None
    review_label: str | None = None
    score_components: dict[str, list[str]] | None = None  # {"available": [...], "omitted": [...]}
    match: MatchDetails | None = None
    references: list[dict] = []
    suggested_questions: list[str] = []
    warnings: list[str] = []


class NonPriceFinding(BaseModel):
    finding_type: str
    description: str
    basis: str  # user_confirmed_arithmetic | public_data
    line_ids: list[str] = []
    count: int
    action: str  # one specific, actionable next step for this finding


class AnalysisSummary(BaseModel):
    compared: int
    context_only: int
    insufficient_data: int
    total: int


class AnalysisResponse(BaseModel):
    analysis_id: str
    case_id: str
    status: str  # completed | partial | insufficient_data
    line_comparisons: list[LineComparison]
    non_price_findings: list[NonPriceFinding] = []
    summary: AnalysisSummary
    created_at: str
