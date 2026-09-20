"""AI-assisted plain-language explanations and Q&A (Gemini).

CLAUDE.md invariant 4: code does the math, this module only drafts prose.
Its output is never treated as a price, difference, score, citation, or
eligibility determination -- every number it can reference is already
computed and already cited (the DATA block below); it explains what exists,
it never invents or recomputes a number.

Gated on Case.external_processing_consent (docs/02's own field for exactly
this -- previously declared but never enforced anywhere). The question and
answer are never persisted: only a receipt-safe activity summary is logged,
matching invariant 9's "never log ... extracted text" for this new external
call.
"""

from dataclasses import dataclass

from google import genai
from google.genai import types

from billproof.config import get_settings
from billproof.errors import AppError
from billproof.models import BillLine, Case
from billproof.schemas.analysis import LineComparison

MAX_QUESTION_CHARS = 500
_MAX_OUTPUT_TOKENS = 1024

_SYSTEM_INSTRUCTION = """\
You explain a hospital bill price comparison to a patient, in plain sixth-to-eighth-grade language.

Rules you must never break:
- Never invent a price, benchmark, percentage, or score. Only use numbers given to you in the DATA section.
- Never say "fraud", "illegal", "you broke the law", "guaranteed savings", or "the legally correct amount is X".
- Never give a legal, medical, or financial conclusion or advice. If asked, say you can't help with that \
and suggest a lawyer, doctor, or licensed advisor instead.
- Never guess or assert what the patient's insurance contract requires them to pay.
- Use phrases like "amount worth asking about" or "review opportunity", never "overcharge" or "illegally charged".
- If the DATA section does not have enough information to answer, say so plainly instead of guessing.
- Keep answers to a few short sentences, not an essay.
"""


@dataclass
class ExplainResult:
    answer: str
    model: str


def _require_consent(case: Case) -> None:
    if not case.external_processing_consent:
        raise AppError(
            "EXTERNAL_PROCESSING_NOT_CONSENTED",
            "AI-assisted explanations are not enabled for this case. Re-create the case with "
            "external processing consent to use this feature.",
            status_code=403,
        )


def _require_configured() -> str:
    settings = get_settings()
    provider = settings.explanation_provider.strip().lower()
    if provider == "deterministic":
        return "deterministic"
    if provider != "gemini":
        raise AppError(
            "AI_PROVIDER_UNSUPPORTED",
            "The configured explanation provider is not supported.",
            status_code=503,
        )
    if not settings.gemini_api_key:
        raise AppError(
            "AI_NOT_CONFIGURED", "AI-assisted explanations are not configured on this server.", status_code=503
        )
    return settings.gemini_model


def _require_question(question: str | None) -> str:
    q = (question or "").strip()
    if len(q) > MAX_QUESTION_CHARS:
        raise AppError("QUESTION_TOO_LONG", f"Questions are limited to {MAX_QUESTION_CHARS} characters.", status_code=400)
    return q


def _line_data_block(line: BillLine, comparison: LineComparison | None) -> str:
    parts = [
        f"Line item: {line.description or '(no description)'} (code {line.code or 'none'})",
        f"Billed amount: ${line.billed_amount}" if line.billed_amount is not None else "Billed amount: not given",
    ]
    if not comparison:
        parts.append("No comparison has been run for this line yet.")
        return "\n".join(parts)

    parts.append(f"Comparison status: {comparison.comparison_status}")
    if comparison.comparison_subject:
        subject = comparison.comparison_subject
        parts.append(f"Compared as: {subject.type} = ${subject.money.amount_cents / 100:.2f}")
    if comparison.benchmark:
        b = comparison.benchmark
        parts.append(f"Benchmark ({b.basis}): median ${b.median.amount_cents / 100:.2f}, confidence {b.confidence}")
    if comparison.difference and comparison.direction:
        parts.append(f"Difference: ${abs(comparison.difference.amount_cents) / 100:.2f} {comparison.direction} the benchmark")
    if comparison.warnings:
        parts.append("Limitations already on file: " + "; ".join(comparison.warnings))
    if comparison.references:
        ref = comparison.references[0]
        parts.append(f"Source: {ref.get('publisher')}, retrieved {ref.get('retrieval_date')}")
    return "\n".join(parts)


async def _generate(prompt: str, model: str) -> str:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    resp = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0.3,
            # A grounded explanation of already-computed data doesn't need
            # extended reasoning; disabling it makes the token budget above
            # reliably go to the actual answer instead of internal "thinking".
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    answer = (resp.text or "").strip()
    if not answer:
        raise AppError("AI_NO_RESPONSE", "No explanation could be generated. Please try again.", status_code=502)
    return answer


def _money(cents: int) -> str:
    return f"${abs(cents) / 100:,.2f}"


def _deterministic_line_answer(line: BillLine, comparison: LineComparison | None) -> str:
    label = f"code {line.code}" if line.code else "this line"
    if comparison is None:
        return (
            f"BillBuster has not run a comparison for {label} yet. "
            "Review or confirm the line, then run the comparison before drawing a conclusion."
        )
    if comparison.comparison_status == "insufficient_data" or comparison.benchmark is None:
        return (
            f"BillBuster did not find enough like-for-like public data to compare {label}. "
            "That is a missing-evidence result, not a finding that the charge is right or wrong."
        )
    if comparison.comparison_status == "context_only" or comparison.comparison_subject is None:
        return (
            f"BillBuster found public price context for {label}, but it is not comparable enough to "
            "calculate a difference. Check the listed limitations and ask the hospital which rate applied."
        )

    subject = comparison.comparison_subject.money.amount_cents
    benchmark = comparison.benchmark.median.amount_cents if comparison.benchmark.median else None
    if benchmark is None or comparison.difference is None or comparison.direction is None:
        return (
            f"BillBuster found some comparison evidence for {label}, but not enough to summarize a reliable "
            "difference. Use the cited source and limitations when asking the billing office."
        )

    difference = comparison.difference.amount_cents
    if comparison.direction == "matches":
        relationship = "matches the published comparison price"
    else:
        relationship = f"is {_money(difference)} {comparison.direction} the published comparison price"
    return (
        f"For {label}, the compared amount is {_money(subject)} and {relationship} of {_money(benchmark)}. "
        "This is a review cue, not a statement of what you ultimately owe."
    )


def _deterministic_case_answer(lines: list[BillLine], comparisons: list[LineComparison]) -> str:
    compared = [item for item in comparisons if item.comparison_status == "compared"]
    above = sum(1 for item in compared if item.direction == "above")
    below = sum(1 for item in compared if item.direction == "below")
    matches = sum(1 for item in compared if item.direction == "matches")
    limited = max(len(lines) - len(compared), 0)
    return (
        f"BillBuster compared {len(compared)} of {len(lines)} line(s): {above} above, {below} below, "
        f"and {matches} matching a published comparison price. {limited} line(s) have context only or "
        "insufficient data. Open each line to review its source and limitations before contacting billing."
    )


async def explain_line(case: Case, line: BillLine, comparison: LineComparison | None, question: str | None) -> ExplainResult:
    _require_consent(case)
    q = _require_question(question)
    model = _require_configured()

    if model == "deterministic":
        return ExplainResult(answer=_deterministic_line_answer(line, comparison), model=model)

    data_block = _line_data_block(line, comparison)
    ask = f"Patient question: {q}" if q else "Explain this line item and its comparison result in plain language."
    prompt = f"DATA:\n{data_block}\n\n{ask}"

    answer = await _generate(prompt, model)
    return ExplainResult(answer=answer, model=model)


async def ask_case_question(
    case: Case, lines: list[BillLine], comparisons: list[LineComparison], question: str
) -> ExplainResult:
    _require_consent(case)
    q = _require_question(question)
    if not q:
        raise AppError("QUESTION_REQUIRED", "Please provide a question.", status_code=400)
    model = _require_configured()

    if model == "deterministic":
        return ExplainResult(answer=_deterministic_case_answer(lines, comparisons), model=model)

    by_id = {c.line_id: c for c in comparisons}
    blocks = [_line_data_block(line, by_id.get(line.id)) for line in lines]
    data_block = "\n\n".join(f"Line {i + 1}:\n{b}" for i, b in enumerate(blocks))
    prompt = f"DATA (this patient's full bill comparison):\n{data_block}\n\nPatient question: {q}"

    answer = await _generate(prompt, model)
    return ExplainResult(answer=answer, model=model)
