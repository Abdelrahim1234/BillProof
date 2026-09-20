# 01 — Product truth and safe language

Read this before writing any user-facing string, label, template, or disclaimer.

## The promise

> BillBuster identifies price differences and billing issues worth asking about,
> then gives the patient sourced evidence and language for that conversation.

It is **not** an overcharge detector. The emotional arc is
**confusion → evidence → agency**.

## The seven amount types

| Amount | Meaning | Only compare against |
|---|---|---|
| Gross / billed charge | Sticker price before discounts | Gross charge for same code, setting, units, date |
| Discounted cash price | Published self-pay price | Self-pay balance, or a request to consider the cash price |
| Payer-negotiated rate | Contracted provider↔plan price | Exact payer/plan match; allowed amount with caveats |
| Total allowed amount | Recognized amount after adjudication | Exact payer/plan negotiated rate, or allowed distribution |
| Insurer payment | Portion the plan paid | EOB arithmetic only — never a public price |
| Patient responsibility | Deductible + copay + coinsurance + non-covered | Plan/EOB terms; cash price is an anchor, not proof of error |
| De-identified allowed percentile | Aggregate claim amounts (2026 template p10/median/p90 + count) | Same-hospital allowed distributions, labeled as aggregate |

**Medicare average payment** is a further, clearly-labeled public context
benchmark for Medicare FFS only.

## What public data can and cannot show

Can show: hospital gross charges, discounted cash prices, payer/plan negotiated
charges when disclosed, de-identified min/max, 2026 allowed p10/median/p90 and
counts when applicable, CMS aggregate Medicare payment benchmarks.

Cannot show: the exact out-of-pocket amount a comparable individual paid, a
definitive "fair price", whether a charge is unlawful, or what this user's
insurance contract requires them to pay.

## Approved vocabulary

Use: **hospital disclosed cash price**, **your plan's disclosed negotiated
rate**, **de-identified allowed-amount range**, **public comparison**, **amount
worth asking about**, **potential billing discrepancy**, **review
opportunity**, **local comparison**, **observed allowed amount**, **estimate**.

Never use: "proven overcharge", "illegal charge", "guaranteed savings", "you
committed fraud", "you broke the law", "you must reduce this bill", "the legally
correct amount is X", or "what patients paid" (unless a real, consented,
de-identified cohort exists — it does not in this build).

## Packet wording

Neutral asks only:

- "I found a difference I would like reviewed."
- "Please explain which rate and billing code were applied."
- "Is a self-pay discount or financial-assistance review available?"

Every packet ends with: *Educational information, not legal, medical, or
insurance advice.*

## When confidence is insufficient

Return exactly this posture, in the user's language:

> We could not make a reliable price comparison, but we can help request an
> itemized explanation.

Then generate only a request for itemization/explanation — no number, no score.

## Accessibility and inclusion requirements (these are product requirements, not polish)

- Target a sixth- to eighth-grade reading level.
- Define "gross charge", "allowed amount", "negotiated rate", and "patient
  responsibility" inline where they first appear.
- No account required. Manual entry is a first-class path, never a fallback.
- Uninsured/self-pay flow is equal in quality to the insured flow.
- English and Spanish are both primary. Untranslated source documents may stay
  in their original language with a notice.
- Status is never communicated by color alone — shape plus text or icon.
- WCAG 2.2 AA core flow: keyboard operation, visible focus, labels, contrast,
  semantic structure, accessible table equivalent for every chart or map,
  reduced motion, 200% zoom, 375px width.
- Never shame users for debt, income, or missing information.
- No confetti, points, streaks, leaderboards, countdowns, fake seals, or alarm
  styling. Progress is calm and functional.

## Non-goals for this build

No national price database. No automated calls, emails, faxes, or portal
submissions. No diagnosis or medical-coding engine. No legal determination. No
HIPAA-compliance claim. No crowdsourced real patient bills. No fabricated peer
observations presented as real data.
