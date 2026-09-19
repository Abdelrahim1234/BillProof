# 05 — ProofMap (local price landscape) — required P0

This section is newer than the original blueprint and **takes precedence** if an
earlier scope statement treats maps as optional.

A source-labeled local price landscape for hospitals and urgent-care locations.
Never collapse different amount types into one "fair price".

## Data rules

- Hospital CMS MRFs are the primary source for gross, discounted cash,
  payer/plan negotiated, de-identified min/max, and applicable 2026 allowed
  p10/median/p90/count values.
- Transparency in Coverage MRFs may supply a small **preprocessed** insurer-rate
  slice. P0 must never download or scan national payer files at runtime.
- CMS Medicare provider/service aggregates appear only as `medicare_ffs_observed`
  context.
- Virginia APCD holds real allowed amounts but raw access is requested and paid,
  and is not a hackathon API. Ingest only an already-public aggregate with
  compatible terms; otherwise keep an adapter with **zero fake APCD records**.
- Independent urgent-care centers are not necessarily subject to hospital MRF
  rules. Discover candidates from NPPES, verify demo locations manually. If no
  compatible price exists, return `unavailable` with "No public price found" —
  never substitute a hospital price.
- Never label negotiated rates, allowed amounts, or Medicare payments as patient
  out-of-pocket spending.

## Storage additions

Generalize `hospitals` → `facilities` (or add a compatible table) with
`facility_type` (`hospital | hospital_outpatient | urgent_care | other`), CCN,
organizational NPI, taxonomy, verified address + coordinates, verification
source/date, billing URL, assistance URL, public-price URL.

Add:

- `service_bundles` — display name, normalized service key, code + code type,
  setting, charge scope, included/excluded components, caveat.
- `regional_benchmarks` — geography, service/code, amount type,
  `published | observed_aggregate`, payer category/plan, p10/median/p90,
  sample + provider counts, year/date, source, suppression flag, limitations.
- `plan_benefit_profiles` — case-scoped network status, deductible
  applicability/remaining, copay, coinsurance, remaining OOP max, copay
  interaction (`in_addition | instead_of | unknown`), assumptions.
  **Never store member or group IDs.**
- `case_evidence` — case/line, facility/benchmark IDs, immutable snapshot of
  facts + source + limitations, match tier, confidence, timestamp.
- `facility_assistance` — policy/application URLs, billing phone, languages,
  summary, source, last verified date.

PostGIS when available; a tested Haversine query is acceptable for SQLite and
offline fixtures.

## Endpoints

```http
GET  /api/v1/map/search?lat=&lng=&radius_miles=&service_code=&code_type=&facility_types=&payer_name=&plan_name=&layers=
GET  /api/v1/map/legend
GET  /api/v1/facilities/{facility_id}/price-evidence?service_code=&code_type=&payer_name=&plan_name=
GET  /api/v1/areas/{geography_type}/{geography_code}/benchmarks?service_code=&code_type=
POST /api/v1/estimates/out-of-pocket
POST /api/v1/cases/{case_id}/evidence
DELETE /api/v1/cases/{case_id}/evidence/{evidence_id}
```

Return facilities **even when price evidence is unavailable**. Every evidence
item returns: `amount_type`, `observed_or_published`, money or range, facility +
type + distance, code/setting/scope, payer/plan, geography, sample and provider
counts, data year, match tier, confidence, limitations, source URL + publisher +
effective and retrieval dates, and the synthetic flag.

Adding evidence to a case validates compatibility with the case line, snapshots
provenance, records a safe activity receipt, and invalidates/rebuilds the packet.
Regional context must never silently become an exact comparison.

## Evidence layers

| Layer | Non-negotiable label |
|---|---|
| Published cash | Published price, not insured responsibility |
| Your plan | Negotiated rate, not final copay |
| Observed public payments | Observed/aggregate population and year |
| Assistance | Eligibility must be confirmed by the facility |
| Data gaps | No public price found |

Never compute one "fair price" by mixing layers. Default sort is **best evidence
match**, then distance — never "cheapest".

## Out-of-pocket estimate

Accept: allowed amount, network status, deductible applicability + remaining,
copay, copay interaction, coinsurance rate, remaining in-network OOP maximum.

For a covered in-network scenario:

```text
deductible_applied  = min(allowed, remaining_deductible) when applicable, else 0
post_deductible     = max(0, allowed - deductible_applied)
coinsurance_amount  = post_deductible * coinsurance_rate
candidate           = deductible_applied + applicable_copay + coinsurance_amount
estimate            = min(allowed, candidate, remaining_oop_max)
```

Return low/high, components, assumptions, unknowns, warnings. When copay
interaction is unknown, compute bounded scenarios. **Do not cap a possible
out-of-network balance bill at the allowed amount.** An adjudicated EOB
patient-responsibility value overrides this estimate in post-visit analysis. Do
not request or store a member ID.

## Geographic privacy

Accept ZIP or approximate location; never require a street address. Do not
persist browser geolocation without explicit consent. Round/cache to ZIP centroid
or coarse coordinates. Suppress aggregates with small cohorts — default `n < 10`,
stricter if the source requires. Never display individual patient dots or exact
visit locations.

## Seed and tests

- Blacksburg/Christiansburg, 25–40 mile radius.
- Two verified hospitals, 5–10 manually verified urgent-care/clinic locations.
- Three to five clean services chosen **after** source verification.
- Real cached public rows, a clearly synthetic bill, at least one honest
  `unavailable` result, verified assistance links.
- Test: radius boundaries · distance ordering · unavailable facilities ·
  amount-layer separation · payer/plan confidence · aggregate labels ·
  small-cohort suppression · all cost-share branches · provenance snapshots ·
  packet invalidation · REST/MCP parity · protected-trait and locale invariance.
