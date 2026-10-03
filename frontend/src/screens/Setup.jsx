import { useEffect, useRef, useState } from "react";
import { createSession, getHealth } from "../api.js";
import { APP_NAME, TAGLINE } from "../config.js";

// One row of the health strip: a tick or a warning, plus a message.
function HealthItem({ ok, label, message }) {
  return (
    <li className={ok ? "health-item ok" : "health-item bad"}>
      <span className="health-icon" aria-hidden="true">{ok ? "✓" : "!"}</span>
      <div>
        <div className="health-label">{label}</div>
        <div className="health-message">{message}</div>
      </div>
    </li>
  );
}

function HealthStrip() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await getHealth();
        if (!cancelled) {
          setHealth(data);
          setError("");
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }

    load();
    // Keep checking, so the strip turns green by itself once things are fixed.
    const timer = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <ul className="health">
        <HealthItem ok={false} label="Backend" message={error} />
      </ul>
    );
  }
  if (!health) return <p className="muted">Checking this laptop…</p>;

  return (
    <ul className="health">
      <HealthItem
        ok={health.ollama_ok && health.model_present}
        label={`Gemma (${health.model_name})`}
        message={health.ollama_message}
      />
      <HealthItem ok={health.whisper_loaded} label="Speech model" message={health.whisper_message} />
      <HealthItem ok={health.embedder_loaded} label="Embeddings" message={health.embedder_message} />
    </ul>
  );
}

// The form: topic, explainer name and the slides PDF.
function NewSessionForm({ onCreated }) {
  const [title, setTitle] = useState("");
  const [explainer, setExplainer] = useState("");
  const [pdf, setPdf] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  function choosePdf(file) {
    if (!file) return;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setError("That isn't a PDF. Export your slides to PDF and try again.");
      return;
    }
    setError("");
    setPdf(file);
  }

  function onDrop(event) {
    event.preventDefault();
    setDragging(false);
    choosePdf(event.dataTransfer.files[0]);
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (!pdf) {
      setError("Add your slides (PDF) first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onCreated(await createSession({ pdf, title, explainer }));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={onSubmit}>
      <label className="field">
        <span className="field-label">Topic</span>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Beta blockers"
        />
      </label>

      <label className="field">
        <span className="field-label">Who is explaining?</span>
        <input
          type="text"
          value={explainer}
          onChange={(e) => setExplainer(e.target.value)}
          placeholder="Your name"
        />
      </label>

      <div className="field">
        <span className="field-label">Slides (PDF)</span>
        <div
          className={dragging ? "dropzone dragging" : "dropzone"}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {pdf ? (
            <p className="dropzone-file">{pdf.name}</p>
          ) : (
            <p className="muted">Drag your slides here, or</p>
          )}
          <button type="button" className="button" onClick={() => fileInput.current.click()}>
            {pdf ? "Choose a different file" : "Choose PDF"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(e) => choosePdf(e.target.files[0])}
          />
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <button type="submit" className="button primary" disabled={busy}>
        {busy ? "Reading your slides…" : "Build outline"}
      </button>
    </form>
  );
}

export default function Setup({ onCreated }) {
  return (
    <section className="setup">
      <h1 className="app-name">{APP_NAME}</h1>
      <p className="tagline">{TAGLINE}</p>
      <HealthStrip />
      <NewSessionForm onCreated={onCreated} />
    </section>
  );
}
