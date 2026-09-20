// Every user-facing string lives here so the wording rules in
// docs/01-product-truth.md are reviewable in one place.
//
// Never: "overcharge", "illegal", "fraud", "savings", "what patients paid".
// Always: "amount worth asking about", "review opportunity", "public comparison".

export const COVERAGE_OPTIONS = [
  { value: "uninsured", label: "No insurance / paying myself" },
  { value: "commercial", label: "Insurance through work or the marketplace" },
  { value: "medicare_advantage", label: "Medicare Advantage" },
  { value: "medicaid_managed", label: "Medicaid managed care" },
  { value: "medicare_ffs", label: "Original Medicare" },
  { value: "unknown", label: "I'm not sure" },
];

export const SETTING_OPTIONS = [
  { value: "outpatient", label: "Outpatient (visit, no overnight stay)" },
  { value: "emergency", label: "Emergency department" },
  { value: "inpatient", label: "Inpatient (admitted overnight)" },
  { value: "unknown", label: "Not sure" },
];

export const CODE_TYPE_OPTIONS = [
  { value: "CPT", label: "CPT (most 5-digit codes)" },
  { value: "HCPCS", label: "HCPCS (letter + 4 digits)" },
  { value: "CPT_HCPCS", label: "5 digits, system not stated" },
  { value: "REVENUE", label: "Revenue code (4 digits)" },
  { value: "MS_DRG", label: "MS-DRG (inpatient stay)" },
  { value: "APC", label: "APC" },
  { value: "UNKNOWN", label: "I don't know" },
];

export const GOAL_OPTIONS = [
  { value: "billing_review", label: "Ask for a billing review" },
  { value: "cash_price_match", label: "Ask about the cash price" },
  { value: "discount", label: "Ask for a self-pay discount" },
  { value: "payment_plan", label: "Ask for a payment plan" },
  { value: "financial_assistance", label: "Ask about financial assistance" },
  { value: "insurance_appeal", label: "Prepare an insurance appeal" },
];

/** What the bill amount we compared actually is, defined inline. */
export const SUBJECT_LABELS: Record<string, { label: string; short: string; definition: string }> = {
  allowed_amount: {
    label: "Allowed amount",
    short: "Allowed",
    definition: "The total your plan recognized for this service, before your share was worked out.",
  },
  billed_amount: {
    label: "Billed amount",
    short: "Billed",
    definition: "The hospital's sticker price for this line, before any discount or plan adjustment.",
  },
  patient_responsibility: {
    label: "Your responsibility",
    short: "You owe",
    definition: "The part of this line the bill says you owe.",
  },
};

/** What the public number we compared against actually is. */
export const BASIS_LABELS: Record<string, { label: string; short: string; definition: string }> = {
  payer_negotiated_rate: {
    label: "Your plan's disclosed negotiated rate",
    short: "Plan's rate",
    definition: "The price this hospital publicly discloses for your insurance plan for this code.",
  },
  hospital_discounted_cash: {
    label: "This hospital's disclosed cash price",
    short: "Cash price",
    definition: "The self-pay price this hospital publishes for this code.",
  },
  peer_discounted_cash: {
    label: "Another local hospital's disclosed cash price",
    short: "Peer cash price",
    definition: "This hospital publishes no cash price for this code, so a nearby hospital's is shown.",
  },
  hospital_allowed_median: {
    label: "This hospital's de-identified allowed-amount median",
    short: "Allowed median",
    definition: "A published aggregate of allowed amounts at this hospital, not a single claim.",
  },
  peer_payer_negotiated_rate: {
    label: "Another local hospital's disclosed negotiated rate",
    short: "Peer rate",
    definition: "Your hospital publishes no negotiated rate for this code, so a nearby hospital's is shown.",
  },
  hospital_discounted_cash_anchor: {
    label: "This hospital's disclosed cash price (context only)",
    short: "Cash price",
    definition:
      "A cash price is not the same kind of number as an insured allowed amount. It is a talking point, not a like-for-like comparison.",
  },
  hospital_deidentified_range_context: {
    label: "De-identified allowed-amount range (context only)",
    short: "Allowed range",
    definition: "A published low-to-high range. There is no single correct point inside it.",
  },
  medicare_ffs_hospital_aggregate: {
    label: "Medicare average payment at this hospital",
    short: "Medicare average",
    definition: "A CMS average for this hospital and code. Medicare rates are not commercial rates.",
  },
};

export const REVIEW_LABELS: Record<string, { label: string; icon: string; tone: string }> = {
  high_review_opportunity: { label: "High review opportunity", icon: "▲▲", tone: "strong" },
  strong_review_opportunity: { label: "Strong review opportunity", icon: "▲", tone: "strong" },
  review_recommended: { label: "Review recommended", icon: "◆", tone: "medium" },
  limited_discrepancy_signal: { label: "Limited signal", icon: "■", tone: "calm" },
};

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "High confidence in this match",
  medium: "Medium confidence in this match",
  low: "Low confidence in this match",
  insufficient: "Not a defensible match",
};

export const STATUS_HEADLINES: Record<string, string> = {
  completed: "We compared every line against public prices.",
  partial: "We compared some lines. Others need more information.",
  insufficient_data: "We could not make a reliable price comparison.",
};

export const FINDING_LABELS: Record<string, string> = {
  exact_duplicate_line: "Possible duplicate line",
  missing_code: "Missing billing code",
  unknown_care_setting: "Care setting not stated",
  facility_professional_ambiguity: "Facility or provider charge not stated",
};

export const GLOSSARY = [
  ["Gross charge", "The hospital's sticker price, before any discount."],
  ["Cash price", "The discounted price a hospital publishes for people paying themselves."],
  ["Negotiated rate", "The price a hospital and an insurance plan agreed on, which hospitals must publish."],
  ["Allowed amount", "The total your plan recognized for a service after it processed the claim."],
  ["Patient responsibility", "The part of the bill you are asked to pay."],
] as const;

export const NO_COMPARISON_POSTURE =
  "We could not make a reliable price comparison, but we can help you request an itemized explanation.";

export const DISCLAIMER = "Educational information, not legal, medical, or insurance advice.";
