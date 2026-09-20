# Extraction schema (current state)

This describes what `services/extraction.py` actually does today, not the
full CODEX_IMPLEMENTATION_SPEC.md #7-#8 document-AI pipeline (embedded-PDF
word/span coordinates, local OCR fallback, page classification, six document
types, field-level evidence envelopes with confidence/validation). None of
that is implemented in this pass -- see "Not implemented" below.

## What exists: `extract_bill()`

`POST /api/v1/cases/{case_id}/bill/extract` accepts a PDF, PNG, JPEG, or
plain-text upload and returns a `BillDocument` (`schemas/bills.py`):

```json
{
  "lines": [
    {
      "code_raw": "71046", "code": "71046", "code_type": "CPT",
      "description": "CHEST XRAY 2 VIEW", "units": "1",
      "billed_amount": "450.00", "allowed_amount": null,
      "care_setting": "outpatient", "charge_scope": "unknown",
      "extraction_confidence": "high", "needs_manual_review": false,
      "warnings": []
    }
  ],
  "needs_manual_entry": false,
  "warnings": []
}
```

Pipeline (`sniff_media_type` -> `extract_bill` -> `parse_labeled_bill_text`):

1. **Magic-byte sniffing**, not filename/Content-Type
   (`%PDF-`, PNG/JPEG signatures, else attempt UTF-8 decode as `text/plain`).
2. **PDF**: `pypdf.PdfReader` extracts embedded text per page; rejects with
   `PDF_TOO_LONG` (413) past `max_pdf_pages`. No OCR fallback -- an
   image-only PDF returns `needs_manual_entry: true` with an explanatory
   warning.
3. **PNG/JPEG**: always returns `needs_manual_entry: true` -- no local or
   external OCR provider is wired up.
4. **`mask_identity_fields`** (`services/privacy.py`) redacts email, phone,
   DOB, SSN, labeled IDs, street addresses, and barcodes from the extracted
   text before any parsing happens.
5. **`parse_labeled_bill_text`** parses the demo's simple `Line N` /
   `Code:` / `Description:` / `Units:` / `Billed amount:` block format
   (see `data/fixtures/demo_bill.txt`). This is a fixture-format parser, not
   a general bill layout parser -- unmatched blocks are never silently
   dropped; every line missing a code or amount is flagged
   `needs_manual_review: true` with a specific warning, and the line is
   still returned so a human can fill it in.
6. A non-itemized document (no lines matched) sets
   `needs_manual_entry: true` rather than inventing line items.

## Persistence

Confirmed lines (`POST .../bill/manual`, `POST .../lines/bulk`, or PATCH)
become `BillLine` documents in the `bill_lines` collection (`models.py`).
Every field-level evidence envelope, page/polygon citation, and
confidence/validation object described in
CODEX_IMPLEMENTATION_SPEC.md #6/#8 does **not** exist -- a `BillLine` is a
single flat, redacted, user-confirmable record, not a per-field evidence
graph.

## Not implemented

- `documents`, `extraction_runs`, `extracted_fields`, `claim_headers` collections.
- OCR (local Tesseract or Azure Document Intelligence) of any kind.
- Page/document classification across the six required document types
  (`hospital_bill`, `insurance_card`, `eob`, `sbc`, `accumulator_screenshot`,
  `receipt`) -- this pass only extracts hospital-bill line items.
- SHA-256/owner-scoped upload idempotency, encrypted/corrupt-file detection,
  malware scanning.
- Coordinate-tracked evidence spans or region-based highlight-to-explain. The
  current explanation routes operate only on confirmed normalized bill lines
  and deterministic comparison results; see `CHATBOT_GROUNDING.md`.
