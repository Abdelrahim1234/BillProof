"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";

// Code does the math; this only drafts prose (CLAUDE.md invariant 4) -- the
// answer is plain text, never rendered as if it were a new price or source.
// Only rendered when the case has opted into external_processing_consent.
export default function AskAI({
  caseId,
  lineId,
}: {
  caseId: string;
  lineId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ text: string; model: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async () => {
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const result = lineId
        ? await api.explainLine(caseId, lineId, question)
        : await api.askCase(caseId, question);
      setAnswer({ text: result.answer, model: result.model });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not get an explanation right now.");
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button type="button" className="link" onClick={() => setOpen(true)}>
        {lineId ? "Ask about this line" : "Ask a question about your bill"}
      </button>
    );
  }

  return (
    <div className="card">
      <label htmlFor={lineId ? `ask-${lineId}` : "ask-case"}>
        {lineId ? "What do you want explained about this line? (optional)" : "Your question"}
      </label>
      <textarea
        id={lineId ? `ask-${lineId}` : "ask-case"}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        maxLength={500}
        rows={2}
      />
      <div className="actions">
        <button type="button" className="primary" onClick={() => void ask()} disabled={loading || (!lineId && !question.trim())}>
          {loading ? "Asking…" : "Ask"}
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setAnswer(null);
            setError(null);
          }}
        >
          Close
        </button>
      </div>
      {error && <p className="error small">{error}</p>}
      {answer && (
        <div className="note">
          <p className="muted small" style={{ margin: "0 0 0.4rem" }}>
            {answer.model === "deterministic" ? "Built-in" : "AI-generated"} explanation, not medical,
            legal, or insurance advice.
          </p>
          {answer.text}
        </div>
      )}
    </div>
  );
}
