import { useEffect, useState } from "react";
import { API_BASE } from "../config.js";
import { getRecap } from "../api.js";

// Seconds -> "12 min"
function minutes(seconds) {
  const whole = Math.round(seconds / 60);
  return whole < 1 ? "< 1 min" : `${whole} min`;
}

// Copy text to the clipboard. The modern way needs a secure page (localhost
// or https); the old way works everywhere, so we fall back to it.
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.style.position = "fixed";
    box.style.opacity = "0";
    document.body.appendChild(box);
    box.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(box);
    return ok;
  }
}

function SummaryCard({ kind, value, label }) {
  return (
    <div className={`summary-card ${kind}`}>
      <div className="summary-value">{value}</div>
      <div className="summary-label">{label}</div>
    </div>
  );
}

export default function Recap({ sessionId, onBackToSession, onNewSession }) {
  const [recap, setRecap] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(""); // "", "yes" or "failed"

  useEffect(() => {
    let cancelled = false;
    getRecap(sessionId)
      .then((data) => !cancelled && setRecap(data))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function handleCopy() {
    const ok = await copyText(recap.whatsapp_text);
    setCopied(ok ? "yes" : "failed");
    setTimeout(() => setCopied(""), 2500);
  }

  if (error) {
    return (
      <section>
        <button type="button" className="link" onClick={onNewSession}>← New session</button>
        <p className="error" role="alert">{error}</p>
      </section>
    );
  }
  if (!recap) return <p className="muted">Building your recap…</p>;

  const unit = recap.unit;
  const nothingRecorded = recap.transcript_lines === 0;

  return (
    <section className="recap">
      <button type="button" className="link" onClick={onBackToSession}>← Back to the session</button>
      <h1 className="screen-title">{recap.title}</h1>
      <p className="muted recap-meta">
        {[recap.explainer, recap.date].filter(Boolean).join(" · ")}
      </p>

      {nothingRecorded && (
        <p className="banner warn">
          Nkuzi didn't hear anything in this session, so every point is listed as missed. Go back and press Start
          listening to record your explanation.
        </p>
      )}

      <div className="summary">
        <SummaryCard kind="ok" value={`${recap.covered.length}/${recap.total}`} label="Covered" />
        <SummaryCard kind="miss" value={recap.missed.length} label="Missed" />
        <SummaryCard kind="warn" value={recap.corrections.length} label="Corrections" />
        <SummaryCard kind="plain" value={minutes(recap.duration_seconds)} label="Duration" />
      </div>

      <div className="recap-actions">
        <button type="button" className="button primary" onClick={handleCopy}>
          {copied === "yes" ? "Copied!" : copied === "failed" ? "Couldn't copy" : "Copy for WhatsApp"}
        </button>
        <a className="button" href={`${API_BASE}/sessions/${sessionId}/transcript.txt`} download>
          Download transcript
        </a>
        <button type="button" className="button" onClick={onNewSession}>New session</button>
      </div>
      {copied === "failed" && (
        <p className="muted">Your browser blocked the copy. Select the message below and copy it by hand.</p>
      )}

      <h2 className="recap-heading miss">Missed ({recap.missed.length})</h2>
      {recap.missed.length === 0 ? (
        <p className="muted">Nothing missed. Every point on the outline was covered.</p>
      ) : (
        <ul className="recap-list">
          {recap.missed.map((point) => (
            <li key={point.id}>
              {point.text}
              {point.slide && <span className="missed-slide"> {unit.toLowerCase()} {point.slide}</span>}
            </li>
          ))}
        </ul>
      )}

      <h2 className="recap-heading warn">Corrections ({recap.corrections.length})</h2>
      {recap.corrections.length === 0 ? (
        <p className="muted">
          None. Corrections come from "Check me" during the session, each backed by a quote from your slides.
        </p>
      ) : (
        <ul className="recap-list">
          {recap.corrections.map((issue) => (
            <li key={issue.id}>
              <div>Said: “{issue.heard}”</div>
              <div>{unit} {issue.slide} says: “{issue.slide_quote}”</div>
              {issue.fix && <div className="recap-fix">{issue.fix}</div>}
            </li>
          ))}
        </ul>
      )}

      <details className="recap-details">
        <summary>Covered ({recap.covered.length})</summary>
        {recap.covered.length === 0 ? (
          <p className="muted">No points were ticked.</p>
        ) : (
          <ul className="recap-list">
            {recap.covered.map((point) => (
              <li key={point.id}>{point.text}</li>
            ))}
          </ul>
        )}
      </details>

      <details className="recap-details">
        <summary>The WhatsApp message</summary>
        <pre className="whatsapp-preview">{recap.whatsapp_text}</pre>
      </details>
    </section>
  );
}
