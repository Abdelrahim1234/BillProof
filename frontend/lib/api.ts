// Thin client for the BillProof REST API. Same-origin: next.config.ts rewrites
// /api/v1/* to the backend, so a phone only needs to reach this Next server.

export type Money = { amount_cents: number; currency: string };

export type Facility = {
  id: string;
  facility_id: string | null;
  facility_type: string;
  name: string;
  address: string;
  city: string;
  state: string;
  zip_code: string;
  financial_assistance_url: string | null;
  billing_url: string | null;
  public_price_url: string | null;
  verification_source: string | null;
  verification_date: string | null;
};

/** Decimal fields arrive as JSON strings; money in results arrives as cents. */
export type LineInput = {
  code: string | null;
  code_type: string;
  description: string | null;
  units: string;
  billed_amount: string | null;
  allowed_amount: string | null;
  insurer_paid: string | null;
  patient_responsibility: string | null;
  care_setting: string;
  charge_scope: string;
};

export type Candidate = LineInput & {
  code_raw: string | null;
  modifiers: string[];
  rate_unit: string | null;
  extraction_confidence: string;
  needs_manual_review: boolean;
  warnings: string[];
};

export type BillDocument = {
  lines: Candidate[];
  needs_manual_entry: boolean;
  warnings: string[];
};

export type BillLineOut = {
  id: string;
  code: string | null;
  code_type: string;
  description: string | null;
  units: string;
  billed_amount: string | null;
  allowed_amount: string | null;
  insurer_paid: string | null;
  patient_responsibility: string | null;
  charge_scope: string;
  care_setting: string;
  confirmed: boolean;
  needs_manual_review: boolean;
  version: number;
};

export type SourceCitation = {
  price_record_id: string | null;
  source_url: string;
  publisher: string;
  effective_date: string | null;
  retrieval_date: string;
  source_record_locator: string | null;
  is_synthetic: boolean;
};

export type BenchmarkSummary = {
  basis: string;
  low: Money | null;
  median: Money | null;
  high: Money | null;
  sample_size: number;
  match_tier: string;
  confidence: string;
  limitations: string[];
};

export type LineComparison = {
  line_id: string;
  comparison_status: "compared" | "insufficient_data";
  comparison_subject: { type: string; money: Money } | null;
  benchmark: BenchmarkSummary | null;
  difference: Money | null;
  percent_above_benchmark: string | null;
  review_score: number | null;
  review_label: string | null;
  match: {
    hospital_exact: boolean;
    code_exact: boolean;
    setting_exact: boolean;
    modifier_exact: boolean | null;
    payer_exact: boolean | null;
    plan_exact: boolean | null;
    factors_used: string[];
    missing_factors: string[];
  } | null;
  references: SourceCitation[];
  suggested_questions: string[];
  warnings: string[];
};

export type NonPriceFinding = {
  finding_type: string;
  description: string;
  basis: string;
  line_ids: string[];
};

export type Analysis = {
  analysis_id: string;
  case_id: string;
  created_at: string;
  status: "completed" | "partial" | "insufficient_data";
  line_comparisons: LineComparison[];
  non_price_findings: NonPriceFinding[];
};

export type PacketResponse = {
  packet_id: string;
  case_id: string;
  goal: string;
  language: string;
  packet: {
    summary: string;
    bill_is_synthetic: boolean;
    bill_notice: string | null;
    assumptions: string[];
    missing_fields: string[];
    review_questions: string[];
    itemized_bill_checklist: string[];
    eob_reconciliation_checklist: string[] | null;
    phone_script: string;
    written_request: string;
    benchmark_sources: SourceCitation[];
    source_limitations: { source_name: string; text: string }[];
    disclaimer: string;
  };
  markdown: string;
};

export type PriceReference = {
  price_record_id: string;
  code: string;
  code_type: string;
  description: string | null;
  charge_type: string;
  amount: Money | null;
  care_setting: string;
  is_synthetic: boolean;
  source: SourceCitation;
};

/** What a presentation screen polls for: a display copy, never a token. */
export type ScreenSubmission = {
  submission_id: string;
  source_label: "example_bill" | "own_bill";
  created_at: string;
  hospital_name: string | null;
  coverage_type: string;
  is_demo_bill: boolean;
  analysis: Analysis;
  lines: { id: string; code: string | null; description: string | null }[];
};

export type CaseCreated = {
  case_id: string;
  access_token: string;
  expires_at: string;
  is_demo?: boolean;
  sample?: string;
  title?: string;
};

export type DemoSample = {
  id: string;
  title: string;
  blurb: string;
  hospital_name: string | null;
  coverage_type: string;
  line_count: number;
};

export type CaseOut = {
  id: string;
  hospital_id: string | null;
  coverage_type: string;
  payer_name: string | null;
  plan_name: string | null;
  care_setting: string;
  language: string;
  expires_at: string;
};

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

type Envelope<T> = { data: T; request_id: string };
type ErrorEnvelope = { error: { code: string; message: string; field: string | null } };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(
      "Could not reach the BillProof server. Check that the backend is running.",
      "NETWORK",
      0,
    );
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = (body as ErrorEnvelope | null)?.error;
    throw new ApiError(err?.message ?? `Request failed (${res.status}).`, err?.code ?? "HTTP", res.status);
  }
  return (body as Envelope<T> | null)?.data as T;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });
const json = { "Content-Type": "application/json" };

export const api = {
  ready: () => request<{ status: string; db: string; seeded: boolean }>("/ready"),

  hospitals: () => request<Facility[]>("/hospitals"),

  hospital: (id: string) => request<Facility>(`/hospitals/${id}`),

  cashPrices: (hospitalId: string) =>
    request<PriceReference[]>(
      `/prices/search?hospital_id=${encodeURIComponent(hospitalId)}&charge_type=discounted_cash`,
    ),

  createCase: (payload: Record<string, unknown>) =>
    request<CaseCreated>("/cases", { method: "POST", headers: json, body: JSON.stringify(payload) }),

  demoSamples: () => request<DemoSample[]>("/demo/samples"),

  demoCase: (sample?: string) =>
    request<CaseCreated>("/demo/cases", {
      method: "POST",
      headers: json,
      body: JSON.stringify(sample ? { sample } : {}),
    }),

  getCase: (caseId: string, token: string) =>
    request<CaseOut>(`/cases/${caseId}`, { headers: auth(token) }),

  extract: (caseId: string, token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BillDocument>(`/cases/${caseId}/bill/extract`, {
      method: "POST",
      headers: auth(token),
      body: form,
    });
  },

  saveLines: (caseId: string, token: string, lines: LineInput[]) =>
    request<BillLineOut[]>(`/cases/${caseId}/lines/bulk`, {
      method: "POST",
      headers: { ...auth(token), ...json },
      body: JSON.stringify({ lines }),
    }),

  getBill: (caseId: string, token: string) =>
    request<BillLineOut[]>(`/cases/${caseId}/bill`, { headers: auth(token) }),

  analyze: (caseId: string, token: string) =>
    request<Analysis>(`/cases/${caseId}/analysis`, { method: "POST", headers: auth(token) }),

  latestAnalysis: (caseId: string, token: string) =>
    request<Analysis>(`/cases/${caseId}/analysis/latest`, { headers: auth(token) }),

  packet: (caseId: string, token: string, goal: string, language: string) =>
    request<PacketResponse>(`/cases/${caseId}/packet`, {
      method: "POST",
      headers: { ...auth(token), ...json },
      body: JSON.stringify({ goal, language }),
    }),

  publishToScreen: (caseId: string, token: string, roomCode: string) =>
    request<{ submission_id: string; room_code: string }>(`/cases/${caseId}/publish`, {
      method: "POST",
      headers: { ...auth(token), ...json },
      body: JSON.stringify({ room_code: roomCode }),
    }),

  screenLatest: (roomCode: string) =>
    request<ScreenSubmission | null>(`/screens/${encodeURIComponent(roomCode)}/latest`),

  clearScreen: (roomCode: string) =>
    request<null>(`/screens/${encodeURIComponent(roomCode)}`, { method: "DELETE" }),

  deleteCase: (caseId: string, token: string) =>
    request<null>(`/cases/${caseId}`, { method: "DELETE", headers: auth(token) }),
};

export function formatMoney(money: Money | null | undefined): string {
  if (!money) return "n/a";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: money.currency || "USD" }).format(
    money.amount_cents / 100,
  );
}

export function formatDecimal(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "n/a";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}
