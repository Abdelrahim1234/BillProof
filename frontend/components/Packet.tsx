"use client";

import { useState } from "react";
import type { PacketResponse } from "@/lib/api";
import { DISCLAIMER, GOAL_OPTIONS } from "@/lib/labels";

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 2500);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export default function Packet({
  packet,
  goal,
  language,
  onGoalChange,
  onLanguageChange,
  onRebuild,
  onBack,
  busy,
}: {
  packet: PacketResponse | null;
  goal: string;
  language: string;
  onGoalChange: (goal: string) => void;
  onLanguageChange: (language: string) => void;
  onRebuild: () => void;
  onBack: () => void;
  busy: boolean;
}) {
  const download = () => {
    if (!packet) return;
    const blob = new Blob([packet.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "billproof-packet.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <h1>Your negotiation packet</h1>

      <div className="card">
        <label htmlFor="goal">What do you want to ask for?</label>
        <select id="goal" value={goal} onChange={(e) => onGoalChange(e.target.value)}>
          {GOAL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <label htmlFor="language">Language</label>
        <select id="language" value={language} onChange={(e) => onLanguageChange(e.target.value)}>
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>

        <div className="actions">
          <button type="button" className="primary" onClick={onRebuild} disabled={busy}>
            {busy ? "Preparing…" : packet ? "Update packet" : "Build packet"}
          </button>
        </div>
      </div>

      {packet && (
        <>
          {packet.packet.bill_notice && <p className="note">{packet.packet.bill_notice}</p>}

          <h2>Summary</h2>
          <p>{packet.packet.summary}</p>

          <h2>Phone script</h2>
          <pre className="script">{packet.packet.phone_script}</pre>
          <CopyButton text={packet.packet.phone_script} label="Copy phone script" />

          <h2>Written request</h2>
          <pre className="script">{packet.packet.written_request}</pre>
          <CopyButton text={packet.packet.written_request} label="Copy written request" />
          <p className="muted small">
            Fill in your name and account number yourself when you send it. BillProof never stores them.
          </p>

          <h2>Questions to ask</h2>
          <ul className="tight">
            {packet.packet.review_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>

          <h2>Before you call</h2>
          <ul className="tight">
            {packet.packet.itemized_bill_checklist.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>

          {packet.packet.eob_reconciliation_checklist && (
            <>
              <h2>Checking against your insurer&apos;s EOB</h2>
              <ul className="tight">
                {packet.packet.eob_reconciliation_checklist.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </>
          )}

          <h2>Assumptions</h2>
          <ul className="tight small">
            {packet.packet.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>

          <details>
            <summary>Sources used ({packet.packet.benchmark_sources.length})</summary>
            <ul className="tight small">
              {packet.packet.benchmark_sources.map((s, i) => (
                <li key={i}>
                  {s.publisher}
                  {s.is_synthetic && " (synthetic fixture)"} · file dated {s.effective_date ?? "unknown"},
                  retrieved {s.retrieval_date} ·{" "}
                  <a href={s.source_url} target="_blank" rel="noreferrer">
                    open source
                  </a>
                </li>
              ))}
            </ul>
            {packet.packet.source_limitations.length > 0 && (
              <ul className="tight small">
                {packet.packet.source_limitations.map((l, i) => (
                  <li key={i}>
                    <strong>{l.source_name}:</strong> {l.text}
                  </li>
                ))}
              </ul>
            )}
          </details>

          <div className="actions">
            <button type="button" onClick={download}>
              Download packet (.md)
            </button>
            <button type="button" onClick={onBack}>
              Back to comparison
            </button>
          </div>

          <p className="muted small" style={{ marginTop: "1rem" }}>
            {packet.packet.disclaimer || DISCLAIMER}
          </p>
        </>
      )}

      {!packet && (
        <button type="button" onClick={onBack}>
          Back to comparison
        </button>
      )}
    </>
  );
}
