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
    comparison_status: str  # compared | insufficient_data
    comparison_subject: ComparisonSubject | None = None
    benchmark: BenchmarkSummary | None = None
    difference: Money | None = None
    percent_above_benchmark: str | None = None
    review_score: int | None = None
    review_label: str | None = None
    match: MatchDetails | None = None
    references: list[dict] = []
    suggested_questions: list[str] = []
    warnings: list[str] = []


class NonPriceFinding(BaseModel):
    finding_type: str
    description: str
    basis: str  # user_confirmed_arithmetic | public_data
    line_ids: list[str] = []


class AnalysisResponse(BaseModel):
    analysis_id: str
    case_id: str
    status: str  # completed | partial | insufficient_data
    line_comparisons: list[LineComparison]
    non_price_findings: list[NonPriceFinding] = []
    created_at: str
