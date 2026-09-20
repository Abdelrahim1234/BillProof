# Explanation assistant grounding

BillBuster exposes two optional, consent-gated explanation routes:

```text
POST /api/v1/cases/{case_id}/lines/{line_id}/explain
POST /api/v1/cases/{case_id}/ask
```

These routes explain data that deterministic backend services already computed.
They never calculate a price, difference, score, citation, eligibility result, or
amount owed.

## Providers

`EXPLANATION_PROVIDER=deterministic` is the safe default. It produces a short
server-local summary from comparison statuses and amounts, needs no API key, and
keeps the judge demo functional without internet access.

`EXPLANATION_PROVIDER=gemini` is optional. It requires `GEMINI_API_KEY` and uses
only after a case explicitly sets `external_processing_consent=true`. Missing
configuration returns a bounded `AI_NOT_CONFIGURED` response; it never silently
falls back to fabricated data.

## Grounding and privacy rules

1. Code performs every calculation before the explanation service runs.
2. The external prompt contains only the selected normalized line/comparison or
   the normalized case lines and their already-computed comparisons.
3. The system prompt forbids invented values, legal/medical conclusions, promised
   savings, and guesses about an insurance contract.
4. If the comparison lacks evidence, the assistant must say so rather than infer
   a price.
5. Questions and answers are not persisted. Activity receipts contain only the
   operation name and provider/model.
6. No name, date of birth, account number, uploaded file, raw OCR text, token, or
   signed source URL is sent to the provider.

The document-region/highlight contract described in earlier planning is not part
of this hackathon build. The current feature explains confirmed normalized bill
lines and comparison results only.
