import { useEffect, useRef, useState } from "react";
import { getOutline, saveOutline } from "../api.js";

// React needs a stable "key" for each row. Saved points use their id;
// points added in the browser get a temporary key until they are saved.
let nextTempKey = 1;
function withKeys(points) {
  return points.map((p) => ({ ...p, key: p.id || `new-${nextTempKey++}` }));
}

// A text box that grows to fit its text, so long points stay readable.
function AutoTextarea({ value, onChange, disabled, autoFocus }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }, [value]);
  return (
    <textarea
      ref={ref}
      className="point-text"
      rows={1}
      value={value}
      disabled={disabled}
      autoFocus={autoFocus}
      aria-label="Point"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default function OutlineReview({ session, onBack }) {
  const [points, setPoints] = useState(() => withKeys(session.outline));
  const [status, setStatus] = useState(session.outline_status); // generating | ready | fallback_only
  const [source, setSource] = useState("slides"); // slides | gemma | edited
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false); // unsaved edits?
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const generating = status === "generating";

  // Take the outline the backend sent and show it.
  function applyServerOutline(data) {
    setPoints(withKeys(data.points));
    setStatus(data.status);
    setSource(data.source);
    setMessage(data.message);
    setProgress(data.progress);
    setDirty(false);
  }

  // While Gemma is working, ask the backend for progress every 2 seconds.
  useEffect(() => {
    if (!generating) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const data = await getOutline(session.session_id);
        if (cancelled) return;
        setError("");
        if (data.status === "generating") setProgress(data.progress);
        else applyServerOutline(data); // Gemma finished: swap its outline in
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [generating, session.session_id]);

  // ----- editing (only changes the list in the browser until saved) -----

  function edit(newPoints) {
    setPoints(newPoints);
    setDirty(true);
    setNotice("");
  }

  function changePoint(key, changes) {
    edit(points.map((p) => (p.key === key ? { ...p, ...changes } : p)));
  }

  function removePoint(key) {
    edit(points.filter((p) => p.key !== key));
  }

  function movePoint(index, step) {
    const target = index + step;
    if (target < 0 || target >= points.length) return;
    const copy = [...points];
    [copy[index], copy[target]] = [copy[target], copy[index]];
    edit(copy);
  }

  function addPoint() {
    edit([...points, { key: `new-${nextTempKey++}`, id: null, text: "", slide: null, isNew: true }]);
  }

  // ----- saving -----

  async function save(successNotice) {
    setSaving(true);
    setError("");
    try {
      const body = points.map((p) => ({ id: p.id, text: p.text, slide: p.slide }));
      applyServerOutline(await saveOutline(session.session_id, body));
      setNotice(successNotice);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  const percent = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <section className="outline">
      <button type="button" className="link" onClick={onBack}>← New session</button>
      <h1 className="screen-title">{session.title}</h1>
      <p className="muted">
        {session.slides_count} slides · {points.length} points. This is your checklist: fix anything
        that looks wrong before you start.
      </p>

      {session.warning && <p className="banner warn">{session.warning}</p>}

      {generating && (
        <div className="banner">
          <div className="banner-row">
            <span>
              Gemma is reading your slides… {progress.done}/{progress.total || "?"}
            </span>
            <button type="button" className="button small" disabled={saving} onClick={() => save("Kept this outline.")}>
              Stop and edit this one
            </button>
          </div>
          <div className="progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <div className="banner-note">Below is a quick outline from your slide titles. You can start with it now.</div>
        </div>
      )}
      {!generating && source === "gemma" && (
        <p className="banner ok">Generated by Gemma, running on this laptop. Every point is checked against your slides.</p>
      )}
      {status === "fallback_only" && (
        <p className="banner warn">
          Built from your slide titles and bullets, without Gemma.{message && ` ${message}`}
        </p>
      )}

      <ol className="points">
        {points.map((point, index) => (
          <li key={point.key} className="point">
            <AutoTextarea
              value={point.text}
              disabled={generating}
              autoFocus={point.isNew}
              onChange={(text) => changePoint(point.key, { text })}
            />
            <div className="point-tools">
              <label className="chip">
                Slide
                <input
                  type="number"
                  min={1}
                  value={point.slide ?? ""}
                  disabled={generating}
                  onChange={(e) =>
                    changePoint(point.key, { slide: e.target.value === "" ? null : Number(e.target.value) })
                  }
                />
              </label>
              <button
                type="button"
                className="icon-button"
                disabled={generating || index === 0}
                onClick={() => movePoint(index, -1)}
                aria-label="Move up"
                title="Move up"
              >
                ↑
              </button>
              <button
                type="button"
                className="icon-button"
                disabled={generating || index === points.length - 1}
                onClick={() => movePoint(index, 1)}
                aria-label="Move down"
                title="Move down"
              >
                ↓
              </button>
              <button
                type="button"
                className="icon-button danger"
                disabled={generating}
                onClick={() => removePoint(point.key)}
                aria-label="Delete point"
                title="Delete point"
              >
                ✕
              </button>
            </div>
          </li>
        ))}
      </ol>

      {!generating && (
        <button type="button" className="button" onClick={addPoint}>+ Add point</button>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <div className="actions">
        {!generating && (
          <button type="button" className="button" disabled={!dirty || saving} onClick={() => save("Outline saved.")}>
            {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
          </button>
        )}
        <button
          type="button"
          className="button primary"
          disabled={saving}
          // The live screen arrives in Milestone 2. For now this saves the outline.
          onClick={() => save("Outline saved. The live session screen arrives in Milestone 2.")}
        >
          Start explaining
        </button>
      </div>
    </section>
  );
}
