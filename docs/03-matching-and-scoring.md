# 03 — Matching, benchmark selection, confidence, scoring, findings

## Match dimensions

Use only pricing-relevant dimensions: hospital and exact location; code type and
code; service date and source effective date; care setting; units/quantity;
modifiers; payer and plan when available; facility vs professional fee;
geography only for fallback regional benchmarks.

Never vary a target price by race, ethnicity, gender, disability, immigration
status, name, language, or credit score.

## Matching tiers

1. Same hospital/location + exact code type, code, modifier, setting, payer, plan.
2. Same hospital/location + exact code type, code, modifier, setting.
3. Same hospital/location + exact code type and code, unknown modifier/setting.
4. Peer hospital + exact code type, code, setting.
5. Description-only candidate — manual confirmation only, **no automatic number**.

Never match facility and professional charges as equivalent.

## Choosing a comparable amount

Pick the **comparison subject** first, then a compatible benchmark.

### Uninsured / self-pay
Subject: patient responsibility when it is the full self-pay balance; otherwise
billed amount with a caveat.
Benchmark order: (1) same-hospital discounted cash price, (2) peer-hospital cash
median, (3) negotiated min/max as context only — never a midpoint.

### Commercial / managed insurance
Preferred subject: EOB or statement allowed amount.
Benchmark order: (1) exact payer + plan negotiated dollar amount, (2) exact payer
with unmatched plan, lower confidence + warning, (3) same-hospital allowed median
where applicable, (4) cash price as an alternative negotiation anchor only,
(5) peer rate of the same charge type.
If the allowed amount is missing: do **not** compare patient responsibility with
a total negotiated rate. Show contextual rates and questions only.

### Medicare FFS
Subject: allowed/total claim amount when present.
Benchmark order: (1) exact hospital + MS-DRG/APC CMS aggregate payment,
(2) compatible same-hospital public price, (3) peer Medicare aggregate.

### Universal rules
- Gross charge is context, never the preferred benchmark.
- Never invent a midpoint from a de-identified min/max.
- Respect rate units — multiply only when the source explicitly says the rate is
  per unit.
- Exclude non-positive values.
- Return `insufficient_data` rather than inventing a benchmark.
- For peer comparisons, compute one representative value per hospital *before*
  the cross-hospital median, so hospitals with many payer-plan rows do not
  dominate.

## Confidence

| Match | Base |
|---|---:|
| Same hospital/code/modifier/setting/payer/plan | 1.00 |
| Same hospital/code/setting cash price | 0.90 |
| Same hospital/code, unknown modifier/setting | 0.80 |
| Peer hospital, exact code/setting | 0.70 |
| Description only | no automatic result |

Freshness multiplier:

| Source age / alignment | Multiplier |
|---|---:|
| ≤ 400 days, reasonably aligned | 1.00 |
| 401–730 days | 0.80 |
| Older or poorly aligned | 0.60 |

Map the product to `high | medium | low | insufficient` and always return the
reasons and the factors used/missing.

Narrative minimums: **High** = exact hospital/location, code, setting,
units/modifiers, and exact payer/plan when the comparison requires it.
**Medium** = exact hospital and code/setting but payer/plan or modifier missing,
or an allowed-amount range used. **Low** = description-based or regional fallback
with missing code/context. **Insufficient** = no defensible like-for-like
comparison.

## Review score

Compute only when subject and benchmark are compatible.

```text
gap_component =
  60 * clamp((subject / benchmark_median - 1) / 1.0, 0, 1)

peer_component =
  25 * clamp((peer_percentile - 0.50) / 0.50, 0, 1)
  # zero when no valid peer percentile is available

documentation_signal =
  15 when subject exceeds a directly applicable public price by > 5%
  0 otherwise

review_score = round(
  (gap_component + peer_component + documentation_signal)
  * match_confidence
  * freshness_confidence
)
```

Labels: `0–24` `limited_discrepancy_signal` · `25–49` `review_recommended` ·
`50–74` `strong_review_opportunity` · `75–100` `high_review_opportunity`.

The compatible monetary difference is `potential_review_amount`. Null when the
amount types are incompatible. Never "savings".

## Non-price findings (deterministic)

- Exact duplicate line (code + service month + modifiers + units + amount).
- Line totals that do not reconcile with the declared total, beyond one cent.
- Missing itemization or missing code.
- Unknown care setting.
- Facility/professional ambiguity.
- Stale or incomplete source.

Each finding must state whether it derives from user-confirmed arithmetic or
from public data.

## Unit test list for this doc

- Five-digit ambiguity stays `CPT_HCPCS`.
- HCPCS and revenue-code normalization preserve meaning and leading zero.
- Modifiers are separated from the base code.
- Exact matching never crosses code types.
- Description similarity never produces an automatic result.
- Cash price is selected for a valid self-pay comparison.
- Exact payer/plan is selected for a compatible insured allowed amount.
- Gross charge is never selected as the preferred benchmark.
- No midpoint is invented from min/max.
- Patient responsibility is never compared with a total negotiated rate.
- Facility and professional lines never mix.
- Units are multiplied only when the source explicitly permits.
- Peer median uses one representative value per hospital.
- Fixed score examples return the expected values.
- Staleness lowers confidence.
- Duplicate and reconciliation checks fire correctly.
- Numeric analysis is identical when only locale changes.
- Numeric analysis is identical when irrelevant display metadata changes.
- Comparison schemas reject protected-trait fields outright.
