# 06 — UI contract

Read with `docs/01-product-truth.md`. That file owns language and labels; this
file owns structure, components, and states.

## Frontend invariants

1. **The frontend never does money math.** Every dollar figure, difference,
   percentage, score, and range comes from the API already computed. The client
   formats `amount_cents` for display and nothing else. No `/100` then `*100`,
   no summing line items in JS, no recomputing a percentage.
2. **Never render a number without its amount type.** Every displayed figure
   carries a plain-language amount-type label from `docs/01`. A bare dollar
   amount on screen is a bug.
3. **Never render a comparison without its source.** Source link, publisher,
   effective date, and retrieval date are reachable from every comparison — in
   the card or one tap away. `is_synthetic=true` rows display a visible
   "Sample data" marker, always, including on stage.
4. **List view is equal to map view, not a fallback.** Same facilities, same
   values, same actions. Build the list first.
5. **Status is never color alone.** Confidence, match tier, and data-gap states
   use shape, icon, or text in addition to color.
6. **Changing language changes no number.** The locale toggle re-renders copy
   only. Assert this in a test.
7. **Types come from the backend's OpenAPI schema, never hand-written.**
   Regenerate rather than patch when the contract changes.

## Stack

- Next.js App Router + TypeScript, `frontend/` at repo root beside `backend/`.
- Tailwind for speed. No component library that fights the design tokens.
- `openapi-typescript` generating `frontend/src/lib/api/schema.d.ts` from the
  backend's `/openapi.json`, wrapped in a thin typed fetch client.
- MapLibre GL via `react-map-gl/maplibre`. A licensed hosted basemap or a
  locally cached demo style — **never the public OSM tile server**.
- i18n: a plain `en`/`es` dictionary module. No heavy i18n framework for a
  two-locale build.
- No global state library. Case state is a React context holding `case_id`,
  `access_token`, and `language`.

## Case token handling

The token is returned once at case creation. Hold it in memory in the case
context, mirrored to `sessionStorage` so a refresh does not destroy the demo.
**Never `localStorage`.** Never put it in a URL, a query string, or a log.
Clear it on "Delete my case".

## Routes

```text
/                          Landing, sample-bill choice, manual-entry entry point
/case/new                  Three-step intake (hospital → coverage → bill)
/case/[caseId]/review      Extracted or entered line items, user confirmation
/case/[caseId]/results     Summary + line-item evidence
/case/[caseId]/map         ProofMap
/case/[caseId]/packet      Negotiation builder + print view
/methodology               How comparisons work, data sources, limitations
/privacy                   What is stored, for how long, what is never asked
```

`/methodology` and `/privacy` are P0, not filler. They are where a skeptical
judge goes, and they mirror the MCP `methodology://pricing-comparison` resource.

## Design tokens

```text
--navy     deep navy/blue   — primary, trust, headers, primary actions
--teal     verified         — exact match, high confidence, confirmed source
--amber    uncertainty      — partial match, low confidence, missing fields
--red      error only       — failed request, invalid input, arithmetic conflict
--slate    neutral text/surface ramp
```

Red is **never** used for "this bill is wrong". A price difference is navy or
amber, never red. No confetti, no countdowns, no alarm styling, no fake trust
seals, no "guaranteed savings" badge.

Typography targets a sixth- to eighth-grade reading level. Results lead with the
conclusion in one neutral sentence, then progressively disclose methodology.

## Core components

| Component | Responsibility |
|---|---|
| `MoneyDisplay` | Formats `{amount_cents, currency}`. The only place cents become a string. |
| `AmountTypeLabel` | Plain-language amount type + a tooltip/definition from docs/01 |
| `ConfidenceBadge` | `high\|medium\|low\|insufficient` with icon + text, never color alone |
| `SourceChip` | Publisher, effective date, retrieval date, outbound link, synthetic marker |
| `MatchExplainer` | "Why this is comparable" / "What this does not prove" |
| `ComparisonRange` | Horizontal range/bullet visual **plus** an equivalent `<table>` |
| `LineItemCard` | One bill line: subject, benchmark, difference, match, caveats |
| `CaveatList` | Limitations and missing factors, always visible, never collapsed by default |
| `ActivityReceiptDrawer` | Safe receipts; labels a row "MCP" only when `transport=mcp` |
| `InsufficientDataCard` | The no-comparison state and its itemization-request CTA |
| `LanguageToggle` | `en`/`es`; asserts no numeric change |
| `DisclaimerFooter` | Educational-information line on every results and packet view |

## ProofMap components

`LocalPriceMap` · `AccessibleFacilityList` · `LayerControl` · `SourceLegend` ·
`FacilityPin` · `FacilityBottomSheet` · `CompareDrawer` · `YourAmountMarker` ·
`PlanCostEstimator` · `EvidenceMatchPanel` · `AssistanceCard` · `DataGapCard` ·
`ProofPathProgress`

Facility card contents and layer labels are specified in `docs/05-proofmap.md` —
follow that table exactly, including the non-negotiable label per layer.

`ProofPathProgress` shows Decode → Compare → Choose proof → Take action. Calm
and functional: each step unlocks when its evidence exists. Completion reads
"Your evidence packet is ready." No points, streaks, or leaderboards.

## Required states for every data view

Build all five before moving on. A view with only a happy path is unfinished.

1. **Loading** — synchronous extraction and analysis can take seconds.
2. **Empty** — no lines entered yet.
3. **Insufficient** — a comparison could not be made. Shows the docs/01 sentence
   and offers the itemization request. This is a **first-class result**, not an
   error state, and must not be styled red.
4. **Error** — backend unreachable or a retryable failure, with a retry action.
5. **Synthetic** — sample data marker, visible on stage.

## Accessibility acceptance criteria

- Every map result available in list/table view.
- Keyboard users traverse all results without entering the map canvas.
- Map markers have equivalent named controls.
- Focus never trapped in a popover or bottom sheet.
- Visible focus ring on every interactive element.
- Status never by color alone.
- Every range or chart has a text/table equivalent.
- Works at 200% zoom and 375px width.
- `prefers-reduced-motion` respected, including the map fly-to.
- Labels on every input; errors associated programmatically.
- English and Spanish primary flow. Untranslated source documents stay in their
  original language with a notice.

## What the frontend must not do

- No account, login, or signup anywhere.
- Never ask for SSN, full account or member ID, card data, medical history,
  street address, or date of birth.
- Never require a billing code to proceed — manual entry works without one.
- Never block the flow on document upload.
- Never persist bill contents to browser storage.
- Never send analytics containing bill fields, codes, or amounts.
- Never auto-send a letter, email, fax, or portal submission. The packet is
  copy, print, and download only.
