"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  formatDecimal,
  type Analysis,
  type BillLineOut,
  type Candidate,
  type DemoSample,
  type Facility,
  type LineInput,
  type PacketResponse,
  type PriceReference,
} from "@/lib/api";
import { COVERAGE_OPTIONS, DISCLAIMER, SETTING_OPTIONS } from "@/lib/labels";
import LineEditor, { blankLine, type EditableLine } from "@/components/LineEditor";
import Results from "@/components/Results";
import Packet from "@/components/Packet";

type Step = "start" | "setup" | "upload" | "review" | "results" | "packet" | "sent" | "legacy";
// The case credential is an HttpOnly, same-site cookie owned by the BFF. Only
// non-secret resume metadata is kept in browser storage.
type Session = { caseId: string; isDemo: boolean; consented: boolean };

const SESSION_KEY = "billproof.session";
const STEP_LABELS: [Step, string][] = [
  ["setup", "Your bill"],
  ["review", "Check the lines"],
  ["results", "Comparison"],
  ["packet", "Packet"],
];
// In screen mode the phone stops at "sent": the comparison and packet live on
// the presentation screen, so promising them here would be a lie.
const SCREEN_STEP_LABELS: [Step, string][] = [
  ["setup", "Your bill"],
  ["review", "Check the lines"],
  ["sent", "Sent to the screen"],
];

const INSURED = new Set(["commercial", "medicare_advantage", "medicaid_managed", "medicare_ffs"]);

// Kept under the backend's MAX_UPLOAD_MB because a hosted proxy (Vercel and
// friends) rejects large bodies before they ever reach the backend.
const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB ?? 4);

function toLineInput(line: EditableLine): LineInput {
  const clean = (v: string) => {
    const t = v.trim();
    return t === "" ? null : t;
  };
  return {
    code: clean(line.code),
    code_type: line.code_type,
    description: clean(line.description),
    units: clean(line.units) ?? "1",
    billed_amount: clean(line.billed_amount),
    allowed_amount: clean(line.allowed_amount),
    insurer_paid: null,
    patient_responsibility: clean(line.patient_responsibility),
    care_setting: line.care_setting,
    charge_scope: "unknown",
  };
}

function fromCandidate(c: Candidate): EditableLine {
  return {
    key: Math.random().toString(36).slice(2),
    code: c.code ?? c.code_raw ?? "",
    code_type: c.code_type ?? "UNKNOWN",
    description: c.description ?? "",
    units: c.units ?? "1",
    billed_amount: c.billed_amount ?? "",
    allowed_amount: c.allowed_amount ?? "",
    patient_responsibility: c.patient_responsibility ?? "",
    care_setting: c.care_setting ?? "unknown",
    warnings: c.warnings ?? [],
  };
}

export default function Home() {
  const [step, setStep] = useState<Step>("start");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  const [hospitals, setHospitals] = useState<Facility[]>([]);
  const [samples, setSamples] = useState<DemoSample[]>([]);
  const [pick, setPick] = useState<DemoSample | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [facility, setFacility] = useState<Facility | null>(null);
  const [priceHints, setPriceHints] = useState<PriceReference[]>([]);

  const [hospitalId, setHospitalId] = useState("");
  const [coverage, setCoverage] = useState("uninsured");
  const [payerName, setPayerName] = useState("");
  const [planName, setPlanName] = useState("");
  const [careSetting, setCareSetting] = useState("outpatient");
  const [aiConsent, setAiConsent] = useState(false);

  const [editable, setEditable] = useState<EditableLine[]>([]);
  const [extractNotes, setExtractNotes] = useState<string[]>([]);
  const [savedLines, setSavedLines] = useState<BillLineOut[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [packet, setPacket] = useState<PacketResponse | null>(null);
  const [goal, setGoal] = useState("billing_review");
  const [language, setLanguage] = useState("en");

  const fileRef = useRef<HTMLInputElement>(null);
  const insured = INSURED.has(coverage);

  // ?room=CODE turns this into a send-only device: the comparison runs on the
  // server and is displayed on the presentation screen, never here.
  const [roomCode, setRoomCode] = useState<string | null>(null);
  const screenMode = roomCode !== null;

  const store = (s: Session | null) => {
    setSession(s);
    try {
      if (s) sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* private mode: the flow still works, it just cannot survive a refresh */
    }
  };

  const fail = (e: unknown) => {
    const message =
      e instanceof ApiError
        ? e.status === 403 || e.status === 401
          ? "This session expired. Start over to check another bill."
          : e.message
        : "Something went wrong. Please try again.";
    setError(message);
    setBusy(null);
    setStatus("");
  };

  useEffect(() => {
    api.hospitals().then(setHospitals).catch(() => setHospitals([]));
    api
      .demoSamples()
      .then((list) => {
        setSamples(list);
        // Whoever scans next gets a different bill than the last person, which
        // keeps the wall varied without anyone choosing.
        setPick(list.length ? list[Math.floor(Math.random() * list.length)] : null);
      })
      .catch(() => setSamples([]));
  }, []);

  useEffect(() => {
    const room = new URLSearchParams(window.location.search).get("room");
    if (room) setRoomCode(room.toLowerCase());
  }, []);

  // Resume after an accidental refresh on a phone.
  useEffect(() => {
    let saved: Session | null = null;
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      saved = raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      saved = null;
    }
    if (!saved) return;
    if (new URLSearchParams(window.location.search).get("room")) return;
    (async () => {
      try {
        const [a, lines] = await Promise.all([
          api.latestAnalysis(saved.caseId),
          api.getBill(saved.caseId),
        ]);
        setSession(saved);
        setAnalysis(a);
        setSavedLines(lines);
        setStep("results");
      } catch (e) {
        if (e instanceof ApiError && e.code === "CASE_OUTSIDE_ACTIVE_MARKET") {
          // Keep both the non-secret case ID and the HttpOnly capability so
          // the owner can still exercise the lifecycle-only DELETE route.
          setSession(saved);
          setStep("legacy");
          return;
        }
        try {
          sessionStorage.removeItem(SESSION_KEY);
        } catch {
          /* ignore */
        }
      }
    })();
  }, []);

  const loadFacility = useCallback(async (id: string | null) => {
    if (!id) return;
    try {
      const f = await api.hospital(id);
      setFacility(f);
    } catch {
      /* the comparison does not depend on this */
    }
  }, []);

  const runAnalysis = async (s: Session) => {
    setBusy(screenMode ? "Sending to the screen…" : "Comparing against published prices…");
    setStatus("Comparing your bill against published prices.");

    if (screenMode && roomCode) {
      await api.analyze(s.caseId);
      await api.publishToScreen(s.caseId, roomCode);
      setBusy(null);
      setStatus("Sent to the screen.");
      setStep("sent");
      return;
    }

    const [a, lines, caseInfo] = await Promise.all([
      api.analyze(s.caseId),
      api.getBill(s.caseId),
      api.getCase(s.caseId),
    ]);
    setAnalysis(a);
    setSavedLines(lines);
    await loadFacility(caseInfo.hospital_id);
    setBusy(null);
    setStatus("Comparison ready.");
    setStep("results");
  };

  const shuffle = () => {
    if (samples.length < 2) return;
    const others = samples.filter((s) => s.id !== pick?.id);
    setPick(others[Math.floor(Math.random() * others.length)]);
  };

  const startDemo = async (sample?: string) => {
    setError(null);
    setBusy("Loading the example bill…");
    try {
      const created = await api.demoCase(sample);
      const s = { caseId: created.case_id, isDemo: true, consented: true };
      store(s);
      if (screenMode) {
        await runAnalysis(s);
        return;
      }
      const lines = await api.getBill(s.caseId);
      setSavedLines(lines);
      setBusy(null);
      setStep("review");
    } catch (e) {
      fail(e);
    }
  };

  const createCase = async () => {
    setError(null);
    if (!hospitalId) {
      setError("Please choose the hospital that sent the bill.");
      return;
    }
    setBusy("Starting…");
    try {
      const created = await api.createCase({
        hospital_id: hospitalId,
        coverage_type: coverage,
        payer_name: insured && payerName.trim() ? payerName.trim() : null,
        plan_name: insured && planName.trim() ? planName.trim() : null,
        care_setting: careSetting,
        language: "en",
        external_processing_consent: aiConsent,
      });
      const s = { caseId: created.case_id, isDemo: false, consented: aiConsent };
      store(s);
      await loadFacility(hospitalId);
      try {
        setPriceHints(await api.cashPrices(hospitalId));
      } catch {
        setPriceHints([]);
      }
      setBusy(null);
      setStep("upload");
    } catch (e) {
      fail(e);
    }
  };

  const uploadFile = async (file: File) => {
    if (!session) return;
    setError(null);
    // Hosted platforms cap the body of a proxied request well below the
    // backend's own limit, so stop oversized files here with a clear message
    // instead of letting the upload fail at the edge.
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(
        `That file is larger than ${MAX_UPLOAD_MB} MB. Upload a smaller file, or type the lines instead.`,
      );
      return;
    }
    setBusy("Reading your bill…");
    setStatus("Reading the document you uploaded.");
    try {
      const doc = await api.extract(session.caseId, file);
      const lines = doc.lines.map(fromCandidate);
      setEditable(lines.length > 0 ? lines : [blankLine(careSetting)]);
      setExtractNotes(
        doc.needs_manual_entry
          ? [...doc.warnings, "Type the lines from your itemized bill below. It only takes a moment."]
          : doc.warnings,
      );
      setBusy(null);
      setStatus(`Read ${lines.length} line(s). Check them before we compare.`);
      setStep("review");
    } catch (e) {
      fail(e);
    }
  };

  const useSampleFile = async () => {
    setError(null);
    setBusy("Loading the sample bill…");
    try {
      const res = await fetch("/samples/demo_bill.pdf");
      const blob = await res.blob();
      await uploadFile(new File([blob], "demo_bill.pdf", { type: "application/pdf" }));
    } catch (e) {
      fail(e);
    }
  };

  const saveAndCompare = async () => {
    if (!session) return;
    setError(null);
    const usable = editable.filter((l) => l.code.trim() || l.billed_amount.trim());
    if (usable.length === 0) {
      setError("Add at least one line with a code or an amount.");
      return;
    }
    setBusy("Saving your lines…");
    try {
      await api.saveLines(session.caseId, usable.map(toLineInput));
      await runAnalysis(session);
    } catch (e) {
      fail(e);
    }
  };

  const compareDemo = async () => {
    if (!session) return;
    setError(null);
    try {
      await runAnalysis(session);
    } catch (e) {
      fail(e);
    }
  };

  const buildPacket = async (nextGoal = goal, nextLanguage = language) => {
    if (!session) return;
    setError(null);
    setBusy("Preparing your packet…");
    try {
      const p = await api.packet(session.caseId, nextGoal, nextLanguage);
      setPacket(p);
      setBusy(null);
      setStep("packet");
    } catch (e) {
      fail(e);
    }
  };

  const restart = () => {
    store(null);
    setAnalysis(null);
    setPacket(null);
    setSavedLines([]);
    setEditable([]);
    setExtractNotes([]);
    setFacility(null);
    setPriceHints([]);
    setError(null);
    setStatus("");
    setStep("start");
  };

  const deleteCase = async () => {
    if (!session) return;
    if (!confirm("Delete this case and everything in it now?")) return;
    setBusy("Deleting…");
    try {
      await api.deleteCase(session.caseId);
      setBusy(null);
      setStatus("Your case was deleted.");
      restart();
    } catch (e) {
      fail(e);
    }
  };

  const stepLabels = screenMode ? SCREEN_STEP_LABELS : STEP_LABELS;
  const currentStepIndex = stepLabels.findIndex(([s]) => s === step);

  return (
    <>
      <div className="masthead">
        <span className="wordmark">BillBuster</span>
        <span className="tagline">public prices, cited</span>
      </div>
      <main>
      {step !== "start" && step !== "legacy" && (
        <ol className="progress">
          {stepLabels.map(([s, label], i) => (
            <li key={s} aria-current={s === step ? "step" : undefined}>
              {i > 0 && <span aria-hidden="true">› </span>}
              {label}
              {i === currentStepIndex && <span className="sr-only"> (current step)</span>}
            </li>
          ))}
        </ol>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <p className="sr-only" role="status" aria-live="polite">
        {status}
      </p>

      {busy && <p className="note">{busy}</p>}

      {step === "legacy" && session && (
        <>
          <h1>This saved case can&apos;t be reopened</h1>
          <p>
            Its hospital is no longer part of this BillBuster market, so the case cannot be viewed,
            changed, or analyzed.
          </p>
          <p className="muted">
            Your valid case session can still delete the case and all of its stored data.
          </p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => void deleteCase()}
              disabled={Boolean(busy)}
            >
              Delete this saved case
            </button>
            <button type="button" onClick={restart} disabled={Boolean(busy)}>
              Start over without deleting
            </button>
          </div>
        </>
      )}

      {step === "start" && (
        <>
          {pick ? (
            <>
              <p className="eyebrow">Example bill</p>
              <h1>{pick.title}</h1>
              <p className="lede">{pick.blurb}</p>

              <button
                type="button"
                className="primary choice"
                onClick={() => void startDemo(pick.id)}
                disabled={Boolean(busy)}
              >
                <span className="title">
                  {screenMode ? "Send this to the screen" : "Compare this bill"}
                </span>
              </button>

              <div className={samples.length > 1 ? "two-up" : "single-action"}>
                {samples.length > 1 && (
                  <button type="button" onClick={shuffle} disabled={Boolean(busy)}>
                    Show me another
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    setStep("setup");
                  }}
                  disabled={Boolean(busy)}
                >
                  Use my own bill
                </button>
              </div>
            </>
          ) : (
            <>
              <h1>{screenMode ? "Send a bill to the screen" : "Check a hospital bill"}</h1>
              <button
                type="button"
                className="primary choice"
                onClick={() => {
                  setError(null);
                  setStep("setup");
                }}
                disabled={Boolean(busy)}
              >
                <span className="title">Use my own bill</span>
              </button>
            </>
          )}

          <p className="fineprint">{DISCLAIMER}</p>
        </>
      )}

      {step === "setup" && (
        <>
          <h1>About this bill</h1>
          <p className="lede">
            Four questions. No name, date of birth or account number.
          </p>
          {screenMode && (
            <p className="note">
              <strong>Shared screen.</strong> Codes and amounts you enter appear on the screen in this
              room. Names, dates of birth, account numbers, phones and emails never do.
            </p>
          )}

          <label htmlFor="hospital">Which hospital sent the bill?</label>
          <select id="hospital" value={hospitalId} onChange={(e) => setHospitalId(e.target.value)}>
            <option value="">Choose a hospital…</option>
            {hospitals
              .filter((h) => h.facility_type === "hospital" || h.facility_type === "hospital_outpatient")
              .map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}, {h.city} {h.state}
                </option>
              ))}
          </select>
          <p className="muted small">
            Only hospitals with a verified published price file are listed in this build.
          </p>

          <label htmlFor="coverage">How was this paid for?</label>
          <select id="coverage" value={coverage} onChange={(e) => setCoverage(e.target.value)}>
            {COVERAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>

          {insured && (
            <div className="row">
              <div>
                <label htmlFor="payer">Insurance company</label>
                <input
                  id="payer"
                  value={payerName}
                  autoComplete="off"
                  placeholder="Cigna"
                  onChange={(e) => setPayerName(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="plan">Plan name, if you know it</label>
                <input
                  id="plan"
                  value={planName}
                  autoComplete="off"
                  placeholder="NPR"
                  onChange={(e) => setPlanName(e.target.value)}
                />
              </div>
            </div>
          )}

          <label htmlFor="setting">Where did the care happen?</label>
          <select id="setting" value={careSetting} onChange={(e) => setCareSetting(e.target.value)}>
            {SETTING_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>

          {!screenMode && (
            <label htmlFor="ai-consent" style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem" }}>
              <input
                id="ai-consent"
                type="checkbox"
                checked={aiConsent}
                onChange={(e) => setAiConsent(e.target.checked)}
                style={{ width: "auto", minHeight: 0, marginTop: "0.2rem" }}
              />
              <span style={{ textTransform: "none", fontWeight: 400, letterSpacing: "normal" }}>
                Allow AI-assisted explanations (optional)
                <p className="muted small" style={{ margin: "0.2rem 0 0" }}>
                  Lets you ask questions about your bill in plain language. The default explainer stays on
                  this server, but a deployment may explicitly use Google Gemini. If Gemini is enabled, your
                  bill line descriptions and comparison results may be sent to Google—never your name or an
                  identifier. Leave unchecked to skip this feature entirely.
                </p>
              </span>
            </label>
          )}

          <div className="actions">
            <button type="button" className="primary" onClick={createCase} disabled={Boolean(busy)}>
              Continue
            </button>
            <button type="button" onClick={restart} disabled={Boolean(busy)}>
              Back
            </button>
          </div>
        </>
      )}

      {step === "upload" && (
        <>
          <h1>Add your bill</h1>
          <p className="muted">
            Upload the itemized bill, or type the lines yourself. Manual entry works just as well.
          </p>

          <div className="card">
            <label htmlFor="file">Upload a PDF, photo, or text file</label>
            <input
              id="file"
              ref={fileRef}
              type="file"
              accept="application/pdf,text/plain,image/*"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void uploadFile(f);
              }}
              disabled={Boolean(busy)}
            />
            <p className="muted small">
              The file is read once to pull out the line items, then dropped. Up to {MAX_UPLOAD_MB} MB.
              Photos of bills cannot be read automatically in this build, so you will be asked to type those
              lines.
            </p>
          </div>

          <button
            type="button"
            className="block"
            onClick={() => {
              setEditable([blankLine(careSetting)]);
              setExtractNotes([]);
              setStep("review");
            }}
            disabled={Boolean(busy)}
          >
            Type the lines myself →
          </button>

          <button type="button" className="block" onClick={useSampleFile} disabled={Boolean(busy)}>
            Don&apos;t have a bill handy? Use our sample bill file →
          </button>

          <div className="actions">
            <button type="button" onClick={() => setStep("setup")} disabled={Boolean(busy)}>
              Back
            </button>
          </div>
        </>
      )}

      {step === "review" && session?.isDemo && (
        <>
          <h1>The example bill</h1>
          <p className="note">
            This patient bill is a synthetic fixture, not a real person&apos;s statement. The prices it gets
            compared against are real published hospital prices.
          </p>
          {savedLines.map((l) => (
            <div className="card" key={l.id}>
              <strong>{l.description ?? l.code}</strong>
              <p className="muted small" style={{ margin: "0.2rem 0" }}>
                Code {l.code} · {l.care_setting} · {l.units} unit(s)
              </p>
              <p style={{ margin: 0 }}>
                Billed {formatDecimal(l.billed_amount)}
                {l.allowed_amount && <> · allowed {formatDecimal(l.allowed_amount)}</>}
                {l.patient_responsibility && <> · you owe {formatDecimal(l.patient_responsibility)}</>}
              </p>
            </div>
          ))}
          <div className="actions">
            <button type="button" className="primary" onClick={compareDemo} disabled={Boolean(busy)}>
              {screenMode ? "Send to the screen →" : "Compare against published prices →"}
            </button>
            <button type="button" onClick={restart} disabled={Boolean(busy)}>
              Start over
            </button>
          </div>
        </>
      )}

      {step === "review" && !session?.isDemo && (
        <>
          <h1>Check the lines</h1>
          <p className="muted">
            Correct anything that looks wrong. What you confirm here is what gets compared.
          </p>

          {extractNotes.length > 0 && (
            <div className="note">
              <ul className="tight small" style={{ marginBottom: 0 }}>
                {extractNotes.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <LineEditor
            lines={editable}
            onChange={setEditable}
            priceHints={priceHints}
            insured={insured}
            collectDescription={!screenMode}
          />

          <div className="actions">
            <button type="button" className="primary" onClick={saveAndCompare} disabled={Boolean(busy)}>
              {screenMode ? "Send to the screen →" : "Compare against published prices →"}
            </button>
            <button type="button" onClick={restart} disabled={Boolean(busy)}>
              Start over
            </button>
          </div>
        </>
      )}

      {step === "sent" && (
        <>
          <h1>Sent. Look at the screen.</h1>
          <p>
            Your bill is being compared against the hospital&apos;s own published prices, and the result is
            on the screen in the room now.
          </p>
          <p className="muted">
            It stays up until someone sends the next one. Nothing was kept on this phone.
          </p>
          <div className="actions">
            <button type="button" className="primary" onClick={restart} disabled={Boolean(busy)}>
              Send another bill
            </button>
            <button type="button" onClick={() => void deleteCase()} disabled={Boolean(busy)}>
              Delete my data now
            </button>
          </div>
        </>
      )}

      {step === "results" && analysis && (
        <Results
          analysis={analysis}
          lines={savedLines}
          facility={facility}
          isDemo={Boolean(session?.isDemo)}
          onBuildPacket={() => void buildPacket()}
          onDelete={() => void deleteCase()}
          onRestart={restart}
          busy={Boolean(busy)}
          ask={session?.consented ? { caseId: session.caseId } : undefined}
        />
      )}

      {step === "packet" && (
        <Packet
          packet={packet}
          goal={goal}
          language={language}
          onGoalChange={setGoal}
          onLanguageChange={setLanguage}
          onRebuild={() => void buildPacket()}
          onBack={() => setStep("results")}
          busy={Boolean(busy)}
        />
      )}
    </main>
    </>
  );
}
