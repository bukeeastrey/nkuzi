import { useEffect, useState } from "react";
import { getHealth } from "../api.js";
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

export default function Setup() {
  return (
    <section className="setup">
      <h1 className="app-name">{APP_NAME}</h1>
      <p className="tagline">{TAGLINE}</p>
      <HealthStrip />
      <p className="muted">Uploading slides comes next (Milestone 1).</p>
    </section>
  );
}
