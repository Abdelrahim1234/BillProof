"use client";

import type { Analysis, BillLineOut, Facility, LineComparison, SourceCitation } from "@/lib/api";
import { formatMoney } from "@/lib/api";
import { PairedBars } from "@/components/Bars";
import AskAI from "@/components/AskAI";
import {
  BASIS_LABELS,
  CONFIDENCE_LABELS,
  FINDING_LABELS,
  GLOSSARY,
  NO_COMPARISON_POSTURE,
  REVIEW_LABELS,
  STATUS_HEADLINES,
  SUBJECT_LABELS,
} from "@/lib/labels";

function SourceList({ sources }: { sources: SourceCitation[] }) {
  if (sources.length === 0) return null;
  return (
    <details>
      <summary>Where this number comes from ({sources.length})</summary>
      <ul className="tight small">
        {sources.map((s, i) => (
          <li key={`${s.source_url}-${i}`}>
            {s.publisher}
            {s.is_synthetic && <> · <span className="tag">synthetic fixture</span></>}
            <br />
            File dated {s.effective_date ?? "unknown"}, retrieved {s.retrieval_date}.{" "}
            <a href={s.source_url} target="_blank" rel="noreferrer">
              Open hospital source page
            </a>
            {s.source_record_locator && (
              <>
                <br />
                <span className="muted">Record: {s.source_record_locator}</span>
              </>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Anything with a code and a description can title a comparison card. */
export type DisplayLine = { id: string; code: string | null; description: string | null };

export function LineCard({
  line,
  comparison,
  scale,
  ask,
}: {
  line: DisplayLine | undefined;
  comparison: LineComparison;
  /** Shared axis maximum. When given, the two amounts are drawn as bars. */
  scale?: number;
  /** Present only when the case has consented to AI-assisted explanations. */
  ask?: { caseId: string };
}) {
  const title = line?.description || (line?.code ? `Code ${line.code}` : "Bill line");
  const showCodeSuffix = Boolean(line?.code && line?.description);
  const subject = comparison.comparison_subject;
  const benchmark = comparison.benchmark;
  const review = comparison.review_label ? REVIEW_LABELS[comparison.review_label] : null;
  const basis = benchmark ? BASIS_LABELS[benchmark.basis] : null;
  const contextOnly = comparison.comparison_status === "context_only";
  const diffCents = comparison.difference?.amount_cents ?? null;

  return (
    <article className="line-card">
      <div className="line-head">
        <h3 style={{ margin: 0 }}>
          {title}
          {showCodeSuffix && <span className="muted small"> · code {line!.code}</span>}
        </h3>
        {comparison.comparison_status === "insufficient_data" ? (
          <span className="tag">No published price</span>
        ) : review ? (
          <span className={`tag ${review.tone === "strong" ? "loud" : ""}`}>{review.label}</span>
        ) : (
          <span className="tag">Context only</span>
        )}
      </div>

      {comparison.comparison_status === "insufficient_data" ? (
        <p className="small muted">{comparison.warnings[0] ?? NO_COMPARISON_POSTURE}</p>
      ) : (
        <>
          {/* On a shared axis the two amounts read as bars; on a phone, where
              there is no axis to share, they stay as figures with their
              definitions. */}
          {scale && subject && benchmark?.median ? (
            <PairedBars
              charged={subject.money}
              published={benchmark.median}
              scale={scale}
              chargedLabel={SUBJECT_LABELS[subject.type]?.short ?? subject.type}
              publishedLabel={basis?.short ?? "Published"}
            />
          ) : (
            <div className="compare-grid">
              <div className="compare-cell">
                <div className="key">
                  {subject ? SUBJECT_LABELS[subject.type]?.label ?? subject.type : "On the bill"}
                </div>
                <div className="amount">{subject ? formatMoney(subject.money) : "n/a"}</div>
                <div className="gloss">
                  {subject ? SUBJECT_LABELS[subject.type]?.definition : "No comparable amount on this line."}
                </div>
              </div>
              <div className="compare-cell">
                <div className="key">{basis?.label ?? benchmark?.basis ?? "No published price"}</div>
                <div className="amount">
                  {benchmark
                    ? contextOnly && benchmark.low && benchmark.high && benchmark.low.amount_cents !== benchmark.high.amount_cents
                      ? `${formatMoney(benchmark.low)} to ${formatMoney(benchmark.high)}`
                      : formatMoney(benchmark.median)
                    : "n/a"}
                </div>
                <div className="gloss">{basis?.definition ?? ""}</div>
              </div>
            </div>
          )}

          {diffCents === 0 && (
            <p className="delta">
              <span className="headline">This line matches the published price.</span>
            </p>
          )}

          {diffCents !== null && diffCents !== 0 && (
            <p className="delta">
              <span className="headline">
                {formatMoney({ amount_cents: Math.abs(diffCents), currency: "USD" })}
                {diffCents > 0 ? " worth asking about" : " below the published price"}
              </span>
              {comparison.percent_above_benchmark && diffCents > 0 && (
                <span className="muted small"> · {comparison.percent_above_benchmark}% above</span>
              )}
            </p>
          )}

          {contextOnly && (
            <p className="delta small muted">
              These are different kinds of amount, so the gap is not scored. Use the published number as a
              talking point.
            </p>
          )}

          {benchmark && (
            <p className="small muted">
              {CONFIDENCE_LABELS[benchmark.confidence] ?? benchmark.confidence} · {benchmark.sample_size}{" "}
              published record{benchmark.sample_size === 1 ? "" : "s"}
            </p>
          )}
        </>
      )}

      {(comparison.warnings.length > 0 || (benchmark?.limitations.length ?? 0) > 0) &&
        comparison.comparison_status !== "insufficient_data" && (
          <details>
            <summary>Limits on this comparison</summary>
            <ul className="tight small">
              {[...(benchmark?.limitations ?? []), ...comparison.warnings].map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </details>
        )}

      {comparison.suggested_questions.length > 0 && (
        <details>
          <summary>What to ask</summary>
          <ul className="tight small">
            {comparison.suggested_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </details>
      )}

      <SourceList sources={comparison.references} />

      {ask && <AskAI caseId={ask.caseId} lineId={comparison.line_id} />}
    </article>
  );
}

export default function Results({
  analysis,
  lines,
  facility,
  isDemo,
  onBuildPacket,
  onDelete,
  onRestart,
  busy,
  ask,
}: {
  analysis: Analysis;
  lines: BillLineOut[];
  facility: Facility | null;
  isDemo: boolean;
  onBuildPacket: () => void;
  onDelete: () => void;
  onRestart: () => void;
  busy: boolean;
  /** Present only when the case has consented to AI-assisted explanations. */
  ask?: { caseId: string };
}) {
  const byId = new Map(lines.map((l) => [l.id, l]));
  const scored = analysis.line_comparisons.filter((c) => c.review_score !== null).length;
  const total = analysis.line_comparisons.length;

  // The backend emits one finding per line, so the same observation can repeat
  // several times. Collapse each kind into a single card naming the lines.
  const findings = new Map<string, { description: string; basis: string; lineIds: string[] }>();
  for (const f of analysis.non_price_findings) {
    const existing = findings.get(f.finding_type);
    if (existing) existing.lineIds.push(...f.line_ids);
    else findings.set(f.finding_type, { description: f.description, basis: f.basis, lineIds: [...f.line_ids] });
  }
  const codesFor = (ids: string[]) =>
    Array.from(new Set(ids.map((id) => byId.get(id)?.code).filter(Boolean))).join(", ");

  return (
    <>
      <h1>Compared against published prices</h1>

      {isDemo && (
        <p className="note">
          <strong>Example bill.</strong> The patient side is a sample. The prices it is compared against
          are real, from the hospital&apos;s own published file.
        </p>
      )}

      <p className="lede">
        {scored} of {total} line{total === 1 ? "" : "s"} scored
        {facility ? ` against ${facility.name}'s own published prices` : ""}.
      </p>

      {analysis.status === "insufficient_data" && <p className="note">{NO_COMPARISON_POSTURE}</p>}

      {ask && <AskAI caseId={ask.caseId} />}

      {analysis.line_comparisons.map((c) => (
        <LineCard key={c.line_id} line={byId.get(c.line_id)} comparison={c} ask={ask} />
      ))}

      {findings.size > 0 && (
        <>
          <h2>Other things worth asking about</h2>
          {Array.from(findings.entries()).map(([type, f]) => {
            const codes = codesFor(f.lineIds);
            return (
              <div className="card" key={type}>
                <strong>{FINDING_LABELS[type] ?? type}</strong>
                <p className="small" style={{ margin: "0.25rem 0 0" }}>
                  {f.description}
                </p>
                <p className="muted small" style={{ margin: 0 }}>
                  {f.lineIds.length} line{f.lineIds.length === 1 ? "" : "s"}
                  {codes && ` (${codes})`} ·{" "}
                  {f.basis === "user_confirmed_arithmetic"
                    ? "based on the bill details you confirmed"
                    : "based on public data"}
                </p>
              </div>
            );
          })}
        </>
      )}

      <h2>What to do with this</h2>
      <button type="button" className="primary choice" onClick={onBuildPacket} disabled={busy}>
        <span className="title">{busy ? "Preparing…" : "Build my negotiation packet"}</span>
        <span className="sub">Phone script, written request and evidence table, from the numbers above.</span>
      </button>

      {facility && (
        <>
          <h2>{facility.name}</h2>
          <ul className="tight small">
            {facility.financial_assistance_url && (
              <li>
                <a href={facility.financial_assistance_url} target="_blank" rel="noreferrer">
                  Financial assistance policy
                </a>
              </li>
            )}
            {facility.billing_url && (
              <li>
                <a href={facility.billing_url} target="_blank" rel="noreferrer">
                  Billing department
                </a>
              </li>
            )}
            {facility.public_price_url && (
              <li>
                <a href={facility.public_price_url} target="_blank" rel="noreferrer">
                  Published price file
                </a>
              </li>
            )}
          </ul>
          <p className="muted small">Eligibility for assistance must be confirmed by the facility.</p>
        </>
      )}

      <details>
        <summary>What these words mean</summary>
        <dl className="small">
          {GLOSSARY.map(([term, definition]) => (
            <div key={term}>
              <dt>
                <strong>{term}</strong>
              </dt>
              <dd style={{ margin: "0 0 0.5rem" }}>{definition}</dd>
            </div>
          ))}
        </dl>
      </details>

      <div className="actions">
        <button type="button" onClick={onDelete} disabled={busy}>
          Delete my data now
        </button>
        <button type="button" onClick={onRestart} disabled={busy}>
          Start over
        </button>
      </div>
    </>
  );
}
