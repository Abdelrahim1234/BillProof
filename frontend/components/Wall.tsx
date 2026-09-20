"use client";

import { useEffect, useState } from "react";
import { api, formatMoney, type ScreenSubmission } from "@/lib/api";
import { LineCard } from "@/components/Results";
import { BarsLegend, PairedBars, scaleFor } from "@/components/Bars";

const POLL_MS = 3000;

function Qr({ svg }: { svg: string }) {
  return <div className="qr" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** Sum of the compatible differences, so the room gets one headline number. */
function reviewTotal(submission: ScreenSubmission): number {
  return submission.analysis.line_comparisons.reduce(
    (sum, c) => sum + Math.max(0, c.difference?.amount_cents ?? 0),
    0,
  );
}

/** Totals across the lines that actually have a published price to compare. */
function comparedTotals(submission: ScreenSubmission) {
  let charged = 0;
  let published = 0;
  for (const c of submission.analysis.line_comparisons) {
    const subject = c.comparison_subject?.money.amount_cents;
    const benchmark = c.benchmark?.median?.amount_cents;
    if (c.review_score === null || subject === undefined || benchmark === undefined) continue;
    charged += subject;
    published += benchmark;
  }
  return { charged, published };
}

export default function Wall({ svg, roomCode }: { svg: string; roomCode: string }) {
  const [submission, setSubmission] = useState<ScreenSubmission | null>(null);
  // After a clear, the poll would immediately re-fetch the bill we just cleared
  // if the delete had not landed yet. Remember what we dismissed and ignore it.
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        const next = await api.screenLatest(roomCode);
        if (!active) return;
        if (next && next.submission_id === dismissed) return;
        setSubmission((current) =>
          current && next && current.submission_id === next.submission_id ? current : next,
        );
      } catch {
        /* keep the last bill on screen rather than blanking the room */
      }
    };
    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [roomCode, dismissed]);

  // Presenter control: wipe the wall and wait for the next scan.
  const clearScreen = async () => {
    setDismissed(submission?.submission_id ?? null);
    setSubmission(null);
    try {
      await api.clearScreen(roomCode);
    } catch {
      /* the wall is already clear on screen; the next poll settles the rest */
    }
  };

  if (!submission) {
    return (
      <div className="stage">
        <div className="stage-copy">
          <h1>What does this hospital actually charge?</h1>
          <p className="lede">
            Scan with your phone. Send a bill, ours or yours, and the comparison appears here with
            the source for every number.
          </p>
          <p className="qr-caption">No app, no account, no name asked for.</p>
        </div>
        <div className="stage-scan">
          <Qr svg={svg} />
        </div>
      </div>
    );
  }

  const { analysis, lines } = submission;
  const byId = new Map(lines.map((l) => [l.id, l]));
  const scored = analysis.line_comparisons.filter((c) => c.review_score !== null).length;
  const total = reviewTotal(submission);
  const totals = comparedTotals(submission);
  // One axis for every bar on screen, so lengths compare line to line.
  const scale = scaleFor(analysis.line_comparisons);

  return (
    <div className="wall wall-enter" key={submission.submission_id}>
      <header className="wall-head">
        <div>
          <h1>
            {submission.hospital_name ?? "Hospital bill"}
            {submission.is_demo_bill && <span className="tag" style={{ marginLeft: "0.75rem" }}>Example bill</span>}
          </h1>
          <p className="lede">
            {scored} of {analysis.line_comparisons.length} line
            {analysis.line_comparisons.length === 1 ? "" : "s"} compared against this hospital&apos;s
            published prices.
          </p>
        </div>
        <div className="wall-scan">
          <Qr svg={svg} />
          <p className="qr-caption">Scan to send a bill</p>
          <button type="button" className="wall-reset" onClick={() => void clearScreen()}>
            Clear screen
          </button>
        </div>
      </header>

      {total > 0 && (
        <>
          <div className="wall-total">
            <span className="figure">{formatMoney({ amount_cents: total, currency: "USD" })}</span>
            <span className="caption">
              worth asking about. A difference to raise, not proof of an error.
            </span>
          </div>

          <div className="wall-summary">
            <PairedBars
              charged={{ amount_cents: totals.charged, currency: "USD" }}
              published={{ amount_cents: totals.published, currency: "USD" }}
              scale={Math.max(totals.charged, totals.published)}
              chargedLabel="This bill"
              publishedLabel="Published"
            />
          </div>
        </>
      )}

      <BarsLegend />

      <div className="wall-lines" key={submission.submission_id}>
        {analysis.line_comparisons.map((c) => (
          <LineCard key={c.line_id} line={byId.get(c.line_id)} comparison={c} scale={scale} />
        ))}
      </div>
    </div>
  );
}
