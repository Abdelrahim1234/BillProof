import re
from dataclasses import dataclass

from billproof.enums import CodeType

_MODIFIER_SPLIT = re.compile(r"[\s\-]+")
_FIVE_DIGIT = re.compile(r"^\d{5}$")
_HCPCS_LEVEL_II = re.compile(r"^[A-Z]\d{4}$")
_REVENUE_4DIGIT = re.compile(r"^\d{4}$")
_MS_DRG_APC = re.compile(r"^\d{1,3}$")


@dataclass(frozen=True)
class NormalizedCode:
    code: str
    code_type: str
    modifier: str | None


def normalize_code(code_raw: str, declared_type: str | CodeType | None = None) -> NormalizedCode:
    """Trim/uppercase/split-modifier without ever guessing across code systems.

    docs/03: a five-digit code with no declared system is CPT_HCPCS, never
    auto-CPT. Description similarity is never used here.
    """
    raw = (code_raw or "").strip().upper()
    declared = declared_type.value if isinstance(declared_type, CodeType) else declared_type

    parts = [p for p in _MODIFIER_SPLIT.split(raw) if p]
    base = parts[0] if parts else raw
    modifier = parts[1] if len(parts) > 1 else None

    if declared and declared != CodeType.UNKNOWN.value:
        code_type = declared
    elif _FIVE_DIGIT.match(base):
        code_type = CodeType.CPT_HCPCS.value
    elif _HCPCS_LEVEL_II.match(base):
        code_type = CodeType.HCPCS.value
    elif _REVENUE_4DIGIT.match(base):
        code_type = CodeType.REVENUE.value
    else:
        code_type = CodeType.UNKNOWN.value

    if code_type == CodeType.REVENUE.value and base.isdigit():
        base = base.zfill(4)  # preserve/restore the leading zero either way

    return NormalizedCode(code=base, code_type=code_type, modifier=modifier)


def normalize_payer(payer_name: str | None) -> str | None:
    if not payer_name:
        return None
    text = payer_name.strip().lower()
    text = re.sub(r"[.,]", "", text)
    text = re.sub(r"\b(inc|llc|corp|co)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_plan(plan_name: str | None) -> str | None:
    return normalize_payer(plan_name)
