"use client";

import { CODE_TYPE_OPTIONS, SETTING_OPTIONS } from "@/lib/labels";
import type { PriceReference } from "@/lib/api";

export type EditableLine = {
  key: string;
  code: string;
  code_type: string;
  description: string;
  units: string;
  billed_amount: string;
  allowed_amount: string;
  patient_responsibility: string;
  care_setting: string;
  warnings: string[];
};

export function blankLine(careSetting = "unknown"): EditableLine {
  return {
    key: Math.random().toString(36).slice(2),
    code: "",
    code_type: "CPT",
    description: "",
    units: "1",
    billed_amount: "",
    allowed_amount: "",
    patient_responsibility: "",
    care_setting: careSetting,
    warnings: [],
  };
}

export default function LineEditor({
  lines,
  onChange,
  priceHints,
  insured,
  collectDescription = true,
}: {
  lines: EditableLine[];
  onChange: (lines: EditableLine[]) => void;
  priceHints: PriceReference[];
  insured: boolean;
  /** False on a shared screen: nothing typed here would be shown, so asking for
      it only invites someone to type a name that should not be on a projector. */
  collectDescription?: boolean;
}) {
  const update = (key: string, patch: Partial<EditableLine>) =>
    onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const remove = (key: string) => onChange(lines.filter((l) => l.key !== key));

  // One chip per code this hospital actually publishes a cash price for, so a
  // hand-entered line has something real to compare against.
  const hints = Array.from(new Map(priceHints.map((p) => [p.code, p])).values()).slice(0, 8);

  return (
    <>
      {hints.length > 0 && (
        <div className="card">
          <h3 id="hint-label">Services with a published price at this hospital</h3>
          <p className="muted small">
            Tap one to fill in the code, or type your own from your itemized bill.
          </p>
          <div className="chips" role="group" aria-labelledby="hint-label">
            {hints.map((h) => (
              <button
                key={h.code}
                type="button"
                onClick={() => {
                  const target = lines[lines.length - 1];
                  if (!target) return;
                  update(target.key, {
                    code: h.code,
                    code_type: h.code_type,
                    description: h.description ?? "",
                  });
                }}
              >
                {h.description ?? h.code} · {h.code}
              </button>
            ))}
          </div>
        </div>
      )}

      {lines.map((line, i) => (
        <fieldset key={line.key}>
          <legend>Line {i + 1}</legend>

          {line.warnings.length > 0 && (
            <ul className="tight small muted">
              {line.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}

          <div className="row">
            <div>
              <label htmlFor={`code-${line.key}`}>Billing code</label>
              <input
                id={`code-${line.key}`}
                value={line.code}
                inputMode="numeric"
                autoComplete="off"
                onChange={(e) => update(line.key, { code: e.target.value })}
              />
            </div>
            <div>
              <label htmlFor={`type-${line.key}`}>Code system</label>
              <select
                id={`type-${line.key}`}
                value={line.code_type}
                onChange={(e) => update(line.key, { code_type: e.target.value })}
              >
                {CODE_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {collectDescription && (
            <>
              <label htmlFor={`desc-${line.key}`}>Description on the bill</label>
              <input
                id={`desc-${line.key}`}
                value={line.description}
                onChange={(e) => update(line.key, { description: e.target.value })}
              />
            </>
          )}

          <div className="row">
            <div>
              <label htmlFor={`setting-${line.key}`}>Where it happened</label>
              <select
                id={`setting-${line.key}`}
                value={line.care_setting}
                onChange={(e) => update(line.key, { care_setting: e.target.value })}
              >
                {SETTING_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor={`units-${line.key}`}>Units</label>
              <input
                id={`units-${line.key}`}
                value={line.units}
                inputMode="decimal"
                onChange={(e) => update(line.key, { units: e.target.value })}
              />
            </div>
          </div>

          <label htmlFor={`billed-${line.key}`}>Amount billed ($)</label>
          <input
            id={`billed-${line.key}`}
            value={line.billed_amount}
            inputMode="decimal"
            placeholder="450.00"
            onChange={(e) => update(line.key, { billed_amount: e.target.value })}
          />

          {insured && (
            <>
              <label htmlFor={`allowed-${line.key}`}>Allowed amount ($), if your EOB shows one</label>
              <input
                id={`allowed-${line.key}`}
                value={line.allowed_amount}
                inputMode="decimal"
                onChange={(e) => update(line.key, { allowed_amount: e.target.value })}
              />
              <p className="muted small">
                The allowed amount is the total your plan recognized for this service. It is the number
                that can be compared to your plan&apos;s published negotiated rate.
              </p>
            </>
          )}

          <label htmlFor={`pr-${line.key}`}>Amount you were asked to pay ($)</label>
          <input
            id={`pr-${line.key}`}
            value={line.patient_responsibility}
            inputMode="decimal"
            onChange={(e) => update(line.key, { patient_responsibility: e.target.value })}
          />

          {lines.length > 1 && (
            <button type="button" className="link" onClick={() => remove(line.key)}>
              Remove line {i + 1}
            </button>
          )}
        </fieldset>
      ))}

      <button type="button" onClick={() => onChange([...lines, blankLine(lines[0]?.care_setting)])}>
        + Add another line
      </button>
    </>
  );
}
