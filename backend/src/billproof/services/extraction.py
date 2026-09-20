import io
import re
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader

from billproof.errors import AppError
from billproof.schemas.bills import BillDocument, ExtractedLineCandidate
from billproof.services.code_normalizer import normalize_code
from billproof.services.privacy import mask_identity_fields

MAX_TEXT_BYTES_FOR_SNIFF = 4096


def sniff_media_type(data: bytes) -> str:
    """Inspect magic bytes, not extension or MIME (docs/02)."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    try:
        data[:MAX_TEXT_BYTES_FOR_SNIFF].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


_LINE_SPLIT = re.compile(r"(?im)^\s*line\s+\d+\s*$")
_FIELD_PATTERNS = {
    "code": re.compile(r"(?im)^code:\s*(?P<val>[A-Za-z0-9]+)\s*(?:\((?P<type>[A-Za-z_]+)\))?\s*$"),
    "description": re.compile(r"(?im)^description:\s*(?P<val>.+?)\s*$"),
    "setting": re.compile(r"(?im)^setting:\s*(?P<val>\w+)\s*$"),
    "units": re.compile(r"(?im)^units:\s*(?P<val>[\d.]+)\s*$"),
    "billed_amount": re.compile(r"(?im)^billed amount:\s*\$?(?P<val>[\d,]+\.?\d*)\s*$"),
    "allowed_amount": re.compile(r"(?im)^allowed amount:\s*\$?(?P<val>[\d,]+\.?\d*)\s*$"),
    "patient_responsibility": re.compile(
        r"(?im)^patient responsibility:\s*\$?(?P<val>[\d,]+\.?\d*)\s*$"
    ),
}
_KNOWN_SETTINGS = {"inpatient", "outpatient", "emergency"}


def _to_decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def parse_labeled_bill_text(text: str) -> BillDocument:
    """Parses the simple labeled block format used by the demo/manual-style
    text bill (docs/02 point 8: "parse labeled codes, descriptions, units,
    amount categories"). Not a general-purpose bill OCR parser -- unmatched
    blocks fall through to needs_manual_review candidates instead of being
    silently dropped."""
    blocks = _LINE_SPLIT.split(text)[1:]
    candidates: list[ExtractedLineCandidate] = []
    warnings: list[str] = []

    for block in blocks:
        fields: dict[str, str] = {}
        for name, pattern in _FIELD_PATTERNS.items():
            m = pattern.search(block)
            if m:
                fields[name] = m.group("val")
        code_match = _FIELD_PATTERNS["code"].search(block)
        code_type = (code_match.group("type") or "").upper() if code_match else ""

        setting = (fields.get("setting") or "").lower()
        if setting not in _KNOWN_SETTINGS:
            setting = "unknown"

        line_warnings = []
        has_code = bool(fields.get("code"))
        has_amount = bool(fields.get("billed_amount"))
        if not has_code:
            line_warnings.append("No billing code found on this line; manual entry needed.")
        if not has_amount:
            line_warnings.append("No billed amount found on this line; manual entry needed.")

        candidates.append(
            ExtractedLineCandidate(
                code_raw=fields.get("code"),
                code=fields.get("code"),
                code_type=code_type or "UNKNOWN",
                description=fields.get("description"),
                units=_to_decimal(fields.get("units")) or Decimal(1),
                billed_amount=_to_decimal(fields.get("billed_amount")),
                allowed_amount=_to_decimal(fields.get("allowed_amount")),
                patient_responsibility=_to_decimal(fields.get("patient_responsibility")),
                care_setting=setting,
                extraction_confidence="high" if (has_code and has_amount) else "low",
                needs_manual_review=not (has_code and has_amount),
                warnings=line_warnings,
            )
        )

    if not candidates:
        warnings.append("No labeled lines were recognized in this document.")

    return BillDocument(lines=candidates, needs_manual_entry=not candidates, warnings=warnings)


# Real hospital itemized statements ("Itemization of Hospital Services"),
# not the synthetic labeled-block demo fixture above. Common HCA-family
# layout: revenue-code section headers, then rows of
#   DATE  [CODE]  UNITS  DESCRIPTION  $ AMOUNT
# where CODE is absent for pure facility/revenue-code charges (room, OR,
# anesthesia), "00000" for supply lines with no procedure code, or a
# zero-padded 5-digit HCPCS/CPT number (e.g. "080053" -> 80053). The digit
# lengths of CODE (5-6) and UNITS (1-4) never overlap, so a single regex
# disambiguates them without guessing.
_ITEMIZATION_ROW = re.compile(
    r"^\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?:(?P<code>\d{5,6})\s+)?"
    r"(?P<units>\d{1,4})\s+"
    r"(?P<description>.+?)\s+"
    r"\$\s*(?P<amount>[\d,]+\.\d{2})\s*$"
)


def parse_itemization_table(text: str) -> BillDocument:
    """Parses a real hospital itemized-statement table (docs/02 point 8:
    "parse labeled codes, descriptions, units, amount categories" -- this is
    the free-form-table sibling of parse_labeled_bill_text's fixed-label
    format). Section headers ("0112 - ROOM AND CARE") and "Subtotal:" lines
    never match the row pattern (no leading date) and are skipped, not
    misread as items."""
    candidates: list[ExtractedLineCandidate] = []

    for raw_line in text.splitlines():
        m = _ITEMIZATION_ROW.match(raw_line)
        if not m:
            continue

        code_raw = m.group("code")
        # "00000" is this format's explicit "no procedure code applies"
        # placeholder (facility supply/OR/anesthesia lines), not a real code.
        has_real_code = bool(code_raw) and code_raw != "00000"
        # This statement format zero-pads a 5-digit code to 6 digits
        # ("080053" -> 80053); that's this layout's own convention, not a
        # normalize_code() concern, so unwrap it before handing off.
        code_for_lookup = code_raw[1:] if has_real_code and len(code_raw) == 6 and code_raw[0] == "0" else code_raw
        normalized = normalize_code(code_for_lookup) if has_real_code else None

        warnings = []
        if not has_real_code:
            warnings.append("No billing code on this line; comparison may be limited.")

        candidates.append(
            ExtractedLineCandidate(
                code_raw=code_raw,
                code=normalized.code if normalized else None,
                code_type=normalized.code_type if normalized else "UNKNOWN",
                description=m.group("description").strip(),
                units=_to_decimal(m.group("units")) or Decimal(1),
                billed_amount=_to_decimal(m.group("amount")),
                extraction_confidence="high" if has_real_code else "medium",
                needs_manual_review=not has_real_code,
                warnings=warnings,
            )
        )

    return BillDocument(
        lines=candidates,
        needs_manual_entry=not candidates,
        warnings=[] if candidates else ["No itemized rows were recognized in this document."],
    )


def extract_bill(data: bytes, *, max_pdf_pages: int) -> BillDocument:
    media_type = sniff_media_type(data)

    if media_type in ("image/png", "image/jpeg"):
        # No local or external OCR provider is enabled in P0 (docs/02 point 6).
        return BillDocument(
            lines=[],
            needs_manual_entry=True,
            warnings=["This looks like a scanned image. Please enter the bill details manually."],
        )

    if media_type == "application/pdf":
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > max_pdf_pages:
            raise AppError(
                "PDF_TOO_LONG",
                f"PDF exceeds the {max_pdf_pages}-page limit.",
                status_code=413,
            )
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            return BillDocument(
                lines=[],
                needs_manual_entry=True,
                warnings=["Could not read text from this PDF. Please enter the bill details manually."],
            )
    elif media_type == "text/plain":
        text = data.decode("utf-8")
    else:
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "Unsupported file type.", status_code=415)

    text = mask_identity_fields(text)
    tabular = parse_itemization_table(text)
    if tabular.lines:
        return tabular
    return parse_labeled_bill_text(text)
