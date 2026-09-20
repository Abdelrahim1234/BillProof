"""Deterministic packet content. No model call here: every sentence is a
static, goal/language-selected template filled with numbers and citations
that already came out of services/analysis.py (docs/01, docs/04)."""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from billproof.models import BillLine, Case
from billproof.schemas.analysis import LineComparison

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
PROVENANCE_PATH = Path(__file__).resolve().parents[3] / "data" / "seed" / "provenance.json"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    trim_blocks=True,
    lstrip_blocks=True,
)

DISCLAIMER = {
    "en": "Educational information, not legal, medical, or insurance advice.",
    "es": "Informacion educativa, no es asesoria legal, medica ni de seguros.",
}

SYNTHETIC_DEMO_NOTICE = {
    "en": (
        "Demo notice: This patient bill is a synthetic fixture. The cited hospital price "
        "records are verified extracts from public machine-readable files."
    ),
    "es": (
        "Aviso de demostracion: Esta cuenta del paciente es un ejemplo sintetico. Los precios "
        "hospitalarios citados son extractos verificados de archivos publicos legibles por maquina."
    ),
}

SUMMARY_INTRO = {
    "en": "We compared {line_count} from this bill against the hospital's own publicly disclosed prices.",
    "es": "Comparamos {line_count} de esta cuenta con los precios publicos que el hospital ya ha divulgado.",
}

NO_COMPARISON_POSTURE = {
    "en": "We could not make a reliable price comparison, but we can help request an itemized explanation.",
    "es": "No pudimos hacer una comparacion de precios confiable, pero podemos ayudar a solicitar una explicacion detallada.",
}

GOAL_QUESTIONS = {
    "billing_review": {
        "en": [
            "I found a difference I would like reviewed.",
            "Please explain which rate and billing code were applied.",
        ],
        "es": [
            "Encontre una diferencia que me gustaria que revisaran.",
            "Por favor expliquen que tarifa y codigo de facturacion se aplicaron.",
        ],
    },
    "cash_price_match": {
        "en": ["Is a cash-price match available even though I have insurance or am paying out of pocket?"],
        "es": ["¿Hay disponible una igualacion al precio de pago en efectivo aunque tenga seguro o pague de mi bolsillo?"],
    },
    "discount": {
        "en": ["Is a self-pay discount available for this bill?"],
        "es": ["¿Hay un descuento por pago en efectivo disponible para esta cuenta?"],
    },
    "payment_plan": {
        "en": ["Is an interest-free payment plan available for this balance?"],
        "es": ["¿Hay un plan de pagos sin intereses disponible para este saldo?"],
    },
    "financial_assistance": {
        "en": ["Is a self-pay discount or financial-assistance review available?"],
        "es": ["¿Hay disponible una revision de descuento por pago en efectivo o de asistencia financiera?"],
    },
    "insurance_appeal": {
        "en": ["Is a self-pay discount or financial-assistance review available?"],
        "es": ["¿Hay disponible una revision de descuento por pago en efectivo o de asistencia financiera?"],
    },
}

ITEMIZED_CHECKLIST = {
    "en": [
        "Ask for a fully itemized bill, not just a summary statement.",
        "Confirm the billing code and description for every line.",
        "Confirm which department or provider billed each line.",
    ],
    "es": [
        "Solicite una cuenta completamente detallada, no solo un resumen.",
        "Confirme el codigo de facturacion y la descripcion de cada partida.",
        "Confirme que departamento o proveedor facturo cada partida.",
    ],
}

EOB_CHECKLIST = {
    "en": [
        "Compare the allowed amount on the EOB to the amount billed.",
        "Confirm the plan applied the correct deductible, copay, and coinsurance.",
        "Ask for a corrected EOB if the numbers do not match the plan's terms.",
    ],
    "es": [
        "Compare el monto permitido en la EOB con el monto facturado.",
        "Confirme que el plan aplico correctamente el deducible, copago y coseguro.",
        "Solicite una EOB corregida si los numeros no coinciden con los terminos del plan.",
    ],
}

PHONE_SCRIPT = {
    "en": (
        "Hello, I'm calling about a bill from {hospital}. I've compared some of the charges to the "
        "hospital's own publicly posted prices and found {review_count} worth asking about. "
        "Could you help me understand which rate and billing code were applied, and whether a "
        "self-pay discount, cash-price match, or financial-assistance review is available?"
    ),
    "es": (
        "Hola, llamo por una cuenta de {hospital}. Compare algunos de los cargos con los precios "
        "publicos que el hospital ya ha divulgado y encontre {review_count} que vale la pena "
        "preguntar. ¿Podrian ayudarme a entender que tarifa y codigo de facturacion se aplicaron, y si "
        "hay disponible un descuento por pago en efectivo, igualacion de precio, o revision de "
        "asistencia financiera?"
    ),
}

WRITTEN_REQUEST = {
    "en": (
        "To Whom It May Concern,\n\n"
        "I am requesting a review of my recent bill from {hospital}. Based on the hospital's own "
        "publicly disclosed prices, I found {review_count} with an amount worth asking "
        "about. Please provide an itemized explanation of the billing code and rate applied to each "
        "line, and let me know whether a self-pay discount, cash-price match, or financial-assistance "
        "review is available.\n\n"
        "Patient name: ______________________\n"
        "Account number: ______________________\n\n"
        "Thank you,\n"
    ),
    "es": (
        "A quien corresponda,\n\n"
        "Solicito una revision de mi cuenta reciente de {hospital}. Segun los precios publicos que el "
        "hospital ya ha divulgado, encontre {review_count} con un monto que vale la pena "
        "preguntar. Por favor proporcionen una explicacion detallada del codigo de facturacion y la "
        "tarifa aplicada a cada partida, e informenme si hay disponible un descuento por pago en "
        "efectivo, igualacion de precio, o revision de asistencia financiera.\n\n"
        "Nombre del paciente: ______________________\n"
        "Numero de cuenta: ______________________\n\n"
        "Gracias,\n"
    ),
}


SUBJECT_LABELS = {
    "en": {
        "allowed_amount": "allowed amount",
        "billed_amount": "billed amount",
        "patient_responsibility": "patient responsibility",
        "context_only": "context only",
    },
    "es": {
        "allowed_amount": "monto permitido",
        "billed_amount": "monto facturado",
        "patient_responsibility": "responsabilidad del paciente",
        "context_only": "solo contexto",
    },
}

BENCHMARK_LABELS = {
    "en": {
        "payer_negotiated_rate": "your plan's disclosed negotiated rate",
        "hospital_discounted_cash": "this hospital's disclosed cash price",
        "peer_discounted_cash": "another local hospital's disclosed cash price",
        "hospital_allowed_median": "this hospital's de-identified allowed-amount median",
        "peer_payer_negotiated_rate": "another local hospital's disclosed negotiated rate",
        "medicare_ffs_hospital_aggregate": "Medicare average payment at this hospital",
        "hospital_discounted_cash_anchor": "hospital disclosed cash price",
        "hospital_deidentified_range_context": "de-identified allowed-amount range",
    },
    "es": {
        "payer_negotiated_rate": "tarifa negociada divulgada de su plan",
        "hospital_discounted_cash": "precio en efectivo divulgado por este hospital",
        "peer_discounted_cash": "precio en efectivo divulgado por otro hospital local",
        "hospital_allowed_median": "mediana desidentificada de montos permitidos de este hospital",
        "peer_payer_negotiated_rate": "tarifa negociada divulgada por otro hospital local",
        "medicare_ffs_hospital_aggregate": "pago promedio de Medicare en este hospital",
        "hospital_discounted_cash_anchor": "precio en efectivo divulgado por el hospital",
        "hospital_deidentified_range_context": "rango desidentificado de montos permitidos",
    },
}

REVIEW_LABELS = {
    "en": {
        "high_review_opportunity": "High review opportunity",
        "strong_review_opportunity": "Strong review opportunity",
        "review_recommended": "Review recommended",
        "limited_discrepancy_signal": "Limited signal",
    },
    "es": {
        "high_review_opportunity": "Alta oportunidad de revision",
        "strong_review_opportunity": "Oportunidad clara de revision",
        "review_recommended": "Revision recomendada",
        "limited_discrepancy_signal": "Senal limitada",
    },
}

COMPARISON_STATUS_LABELS = {
    "en": {
        "compared": "Compared",
        "context_only": "Context only",
        "insufficient_data": "Not enough information",
    },
    "es": {
        "compared": "Comparado",
        "context_only": "Solo contexto",
        "insufficient_data": "Informacion insuficiente",
    },
}

DIRECTION_LABELS = {
    "en": {"above": "above", "below": "below", "matches": "matches"},
    "es": {"above": "por encima", "below": "por debajo", "matches": "coincide"},
}


def _money_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    amount = value.quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _line_count(n: int, language: str) -> str:
    if language == "es":
        return f"{n} partida" if n == 1 else f"{n} partidas"
    return f"{n} line item" if n == 1 else f"{n} line items"


def _review_count(n: int, language: str) -> str:
    if language == "es":
        return f"{n} partida" if n == 1 else f"{n} partidas"
    return f"{n} item" if n == 1 else f"{n} items"


@lru_cache
def _source_metadata_by_url() -> dict[str, dict]:
    """Load checked-in source caveats without fetching either full MRF.

    Keyed by both citation_url and the resolved source_url: citation_for_price_record()
    now exposes citation_url as the public SourceCitation.source_url (CLAUDE_FINAL_DEMO_HARDENING
    Fix 2 -- never the raw signed retrieval URL), so a reference's public
    source_url is the citation page, not the file origin. Indexing both keeps
    this lookup correct regardless of which one a reference actually carries.
    """
    try:
        entries = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    metadata: dict[str, dict] = {}
    for entry in entries:
        details = {
            "source_name": entry.get("hospital_name", "hospital MRF"),
            "limitations": entry.get("limitations", []),
        }
        for key in (entry.get("citation_url"), entry.get("source_url")):
            if key:
                metadata[key] = details
    return metadata


def _source_limitations(sources: list[dict]) -> list[dict[str, str]]:
    metadata = _source_metadata_by_url()
    limitations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        details = metadata.get(source.get("source_url"), {})
        source_name = details.get("source_name", "hospital MRF")
        for text in details.get("limitations", []):
            key = (source_name, text)
            if key not in seen:
                seen.add(key)
                limitations.append({"source_name": source_name, "text": text})
    return limitations


def _line_item_view(line: BillLine, comparison: LineComparison, language: str) -> dict:
    subject = comparison.comparison_subject
    subject_type = subject.type if subject else "context_only"
    subject_amount = subject.money.to_decimal() if subject else None
    benchmark_amount = (
        comparison.benchmark.median.to_decimal()
        if comparison.benchmark and comparison.benchmark.median
        else None
    )
    return {
        "code": line.code,
        "description": line.description,
        "billed_amount": str(line.billed_amount) if line.billed_amount is not None else None,
        "comparison_amount_text": _money_text(subject_amount),
        "comparison_amount_label": SUBJECT_LABELS[language].get(subject_type, subject_type),
        "comparison_status": comparison.comparison_status,
        "benchmark_basis": comparison.benchmark.basis if comparison.benchmark else None,
        "benchmark_label": BENCHMARK_LABELS[language].get(
            comparison.benchmark.basis if comparison.benchmark else "",
            comparison.benchmark.basis if comparison.benchmark else None,
        ),
        "benchmark_amount_text": _money_text(benchmark_amount),
        "benchmark_median_cents": comparison.benchmark.median.amount_cents
        if comparison.benchmark and comparison.benchmark.median
        else None,
        "difference_cents": comparison.difference.amount_cents if comparison.difference else None,
        "difference_text": _money_text(comparison.difference.to_decimal())
        if comparison.difference
        else None,
        "difference_direction": DIRECTION_LABELS[language].get(comparison.direction or ""),
        "review_label": comparison.review_label,
        "review_label_text": REVIEW_LABELS[language].get(
            comparison.review_label or "", comparison.review_label
        ),
        "comparison_status_text": COMPARISON_STATUS_LABELS[language].get(
            comparison.comparison_status, comparison.comparison_status
        ),
        "confidence": comparison.benchmark.confidence if comparison.benchmark else None,
        "limitations": (comparison.benchmark.limitations if comparison.benchmark else [])
        + comparison.warnings,
        "warnings": comparison.warnings,
    }


def build_packet(
    *,
    case: Case,
    lines: list[BillLine],
    comparisons: list[LineComparison],
    goal: str,
    language: str,
    hospital_name: str,
    additional_context: str | None = None,
    bill_is_synthetic: bool = False,
) -> tuple[dict, str]:
    lang = language if language in ("en", "es") else "en"
    by_line_id = {c.line_id: c for c in comparisons}

    line_items = [
        _line_item_view(ln, by_line_id[ln.id], lang) for ln in lines if ln.id in by_line_id
    ]
    review_items = [li for li in line_items if li["review_label"] in ("strong_review_opportunity", "high_review_opportunity", "review_recommended")]
    missing_fields = []
    if case.coverage_type == "unknown":
        missing_fields.append("coverage_type")
    if not case.payer_name and case.coverage_type not in ("uninsured", "unknown"):
        missing_fields.append("payer_name")

    any_scored = any(li["comparison_status"] == "compared" and li["review_label"] for li in line_items)
    summary = (
        SUMMARY_INTRO[lang].format(line_count=_line_count(len(line_items), lang))
        if any_scored or line_items
        else NO_COMPARISON_POSTURE[lang]
    )

    sources = []
    seen = set()
    for c in comparisons:
        for ref in c.references:
            key = ref.get("price_record_id") or (
                ref.get("source_url"),
                ref.get("source_record_locator"),
            )
            if key and key not in seen:
                seen.add(key)
                sources.append(ref)

    packet = {
        "summary": summary,
        "bill_is_synthetic": bill_is_synthetic,
        "bill_notice": SYNTHETIC_DEMO_NOTICE[lang] if bill_is_synthetic else None,
        "assumptions": [
            "Comparisons use the hospital's own publicly disclosed prices, not a national average.",
            "A cash price or negotiated rate is a comparison point, not proof of an error.",
        ],
        "missing_fields": missing_fields,
        "line_items": line_items,
        "benchmark_sources": sources,
        "source_limitations": _source_limitations(sources),
        "review_questions": GOAL_QUESTIONS.get(goal, GOAL_QUESTIONS["billing_review"])[lang],
        "itemized_bill_checklist": ITEMIZED_CHECKLIST[lang],
        "eob_reconciliation_checklist": EOB_CHECKLIST[lang] if case.coverage_type not in ("uninsured", "unknown") else None,
        "phone_script": PHONE_SCRIPT[lang].format(
            hospital=hospital_name,
            review_count=_review_count(len(review_items), lang),
        ),
        "written_request": WRITTEN_REQUEST[lang].format(
            hospital=hospital_name,
            review_count=_line_count(len(review_items), lang),
        ),
        "placeholders": {
            "patient_name": "[Your name]" if lang == "en" else "[Su nombre]",
            "account_number": "[Account number]" if lang == "en" else "[Numero de cuenta]",
        },
        "additional_context": additional_context,
        "disclaimer": DISCLAIMER[lang],
    }

    template = _env.get_template(f"negotiation_packet_{lang}.md.j2")
    markdown = template.render(packet=packet, case=case, hospital_name=hospital_name)
    return packet, markdown
