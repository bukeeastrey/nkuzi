import { useEffect, useRef, useState } from "react";
import {
  dismissIssue,
  endSession,
  getCheck,
  getOutline,
  getSession,
  saveOutline,
  sendAudio,
  startCheck,
  startSession,
  togglePoint,
} from "../api.js";
import { startMic } from "../audio.js";
import { CHUNK_SECONDS } from "../config.js";

const TRANSCRIPT_LINES = 4; // how many recent lines the transcript panel shows
const FRESH_MS = 3000; // how long a newly ticked point stays highlighted

// React needs a different "key" for every row of a list. If two rows ever
// share a key, React can draw rows twice or leave old ones behind. So keys are
// made unique here, whatever the ids are.
let keyCounter = 1;
function newKey() {
  return `new-${Date.now().toString(36)}-${keyCounter++}`;
}

function withKeys(points) {
  const used = new Set();
  return points.map((point) => {
    let key = point.id || newKey();
    while (used.has(key)) key = newKey(); // never two rows with the same key
    used.add(key);
    return { ...point, key };
  });
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

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" fill="currentColor">
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </svg>
  );
}

// The outline while you are still preparing: every point can be edited.
function EditableOutline({ points, unit, locked, onEdit }) {
  function change(key, changes) {
    onEdit(points.map((p) => (p.key === key ? { ...p, ...changes } : p)));
  }

  function move(index, step) {
    const copy = [...points];
    [copy[index], copy[index + step]] = [copy[index + step], copy[index]];
    onEdit(copy);
  }

  return (
    <>
      <ol className="points">
        {points.map((point, index) => (
          <li key={point.key} className="point">
            <AutoTextarea
              value={point.text}
              disabled={locked}
              autoFocus={point.isNew}
              onChange={(text) => change(point.key, { text })}
            />
            <div className="point-tools">
              <label className="chip">
                {unit}
                <input
                  type="number"
                  min={1}
                  value={point.slide ?? ""}
                  disabled={locked}
                  onChange={(e) => change(point.key, { slide: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </label>
              <button type="button" className="icon-button" disabled={locked || index === 0} onClick={() => move(index, -1)} aria-label="Move up" title="Move up">
                ↑
              </button>
              <button type="button" className="icon-button" disabled={locked || index === points.length - 1} onClick={() => move(index, 1)} aria-label="Move down" title="Move down">
                ↓
              </button>
              <button type="button" className="icon-button danger" disabled={locked} onClick={() => onEdit(points.filter((p) => p.key !== point.key))} aria-label="Delete point" title="Delete point">
                ✕
              </button>
            </div>
          </li>
        ))}
      </ol>
      {!locked && (
        <button
          type="button"
          className="button"
          onClick={() => onEdit([...points, { key: newKey(), id: null, text: "", slide: null, isNew: true }])}
        >
          + Add point
        </button>
      )}
    </>
  );
}

// The outline while you are explaining: a big checklist, grouped by slide.
// covered: Set of ticked point ids. fresh: Set of ids ticked in the last few seconds.
function Checklist({ points, slides, unit, covered, fresh, onToggle }) {
  // Keep the outline's order; start a new group whenever the slide number changes.
  const groups = [];
  for (const point of points) {
    const last = groups[groups.length - 1];
    if (last && last.slide === point.slide) last.points.push(point);
    else groups.push({ slide: point.slide, points: [point] });
  }
  const titles = Object.fromEntries(slides.map((s) => [s.index, s.title]));

  return (
    <div className="checklist">
      {groups.map((group, i) => (
        <section key={`${group.slide}-${i}`} className="check-group">
          <h2 className="check-heading">
            {group.slide ? `${unit} ${group.slide}` : "Extra points"}
            {titles[group.slide] && <span className="check-heading-title"> · {titles[group.slide]}</span>}
          </h2>
          <ul>
            {group.points.map((point) => {
              const done = covered.has(point.id);
              const classes = ["check-item", done && "done", fresh.has(point.id) && "fresh"].filter(Boolean).join(" ");
              return (
                <li key={point.key}>
                  {/* Click to tick or untick by hand. Your click always wins over the automatic matching. */}
                  <button type="button" className={classes} aria-pressed={done} onClick={() => onToggle(point.id)}>
                    <span className="check-box" aria-hidden="true">{done ? "✓" : ""}</span>
                    <span>{point.text}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

// "What did I miss?": the points not ticked yet.
function MissedPanel({ points, covered, unit, onClose }) {
  const missed = points.filter((p) => !covered.has(p.id));
  return (
    <div className="missed" role="region" aria-label="Points not covered yet">
      <div className="missed-head">
        <strong>{missed.length === 0 ? "Nothing missed" : `Not covered yet (${missed.length})`}</strong>
        <button type="button" className="link" onClick={onClose}>Close</button>
      </div>
      {missed.length === 0 ? (
        <p className="missed-empty">You have covered every point on your outline.</p>
      ) : (
        <ul>
          {missed.map((point) => (
            <li key={point.key}>
              {point.text}
              {point.slide && <span className="missed-slide"> {unit.toLowerCase()} {point.slide}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// "Check me" results. Corrections only ever appear here, after the explainer asks.
// Each one shows what Nkuzi heard next to the slide's own words, so a
// mishearing is easy to spot and dismiss.
function CorrectionsPanel({ issues, status, message, unit, onDismiss, onClose }) {
  const visible = issues.filter((issue) => !issue.dismissed);
  return (
    <div className="corrections" role="region" aria-label="Corrections">
      <div className="corrections-head">
        <strong>Check me</strong>
        <button type="button" className="link" onClick={onClose}>Close</button>
      </div>

      {status === "running" && (
        <p className="corrections-status">
          <span className="spinner" aria-hidden="true" /> Checking what you said against your slides… This takes a
          minute or two on this laptop. Keep explaining: your ticks catch up when it finishes.
        </p>
      )}
      {status === "error" && <p className="error" role="alert">{message}</p>}
      {status === "done" && message && <p className="corrections-status">{message}</p>}

      {visible.map((issue) => (
        <div key={issue.id} className="correction">
          <div className="correction-row">
            <span className="correction-label">Nkuzi heard</span>
            <span>“{issue.heard}”</span>
          </div>
          <div className="correction-row">
            <span className="correction-label">{unit} {issue.slide} says</span>
            <span>“{issue.slide_quote}”</span>
          </div>
          {issue.fix && <p className="correction-fix">{issue.fix}</p>}
          <button type="button" className="button small" onClick={() => onDismiss(issue.id)}>
            That's not what I said
          </button>
        </div>
      ))}
      {status !== "running" && visible.length === 0 && !message && (
        <p className="corrections-status">No corrections so far.</p>
      )}
    </div>
  );
}

// Seconds -> "4:07"
function clock(seconds) {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

// The last few things Nkuzi heard. Collapsible, so it can be hidden on a shared screen.
function Transcript({ lines, micOn }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="transcript">
      <button type="button" className="transcript-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>What Nkuzi heard</span>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open &&
        (lines.length === 0 ? (
          <p className="transcript-empty">
            {micOn ? "Start explaining. Your words show up here a few seconds after you say them." : "Nothing yet."}
          </p>
        ) : (
          <ul className="transcript-lines">
            {lines.slice(-TRANSCRIPT_LINES).map((line) => (
              <li key={line.seq}>
                <span className="transcript-time">{clock(line.at)}</span>
                {line.text}
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

export default function Session({ sessionId, checkBlocked, onBack, onEnd }) {
  const [session, setSession] = useState(null); // title, slides, unit...
  const [loadError, setLoadError] = useState("");
  const [points, setPoints] = useState([]);
  const [status, setStatus] = useState("ready"); // generating | ready | fallback_only
  const [source, setSource] = useState("slides"); // slides | gemma | edited
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false); // unsaved edits?
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Live session state
  const [live, setLive] = useState(false); // false = editing the outline, true = the checklist
  const [micOn, setMicOn] = useState(false);
  const [starting, setStarting] = useState(false);
  const [transcript, setTranscript] = useState([]); // [{seq, at, text}]
  const [waiting, setWaiting] = useState(0); // chunks recorded but not yet transcribed
  const [elapsed, setElapsed] = useState(0); // seconds of listening so far
  const [covered, setCovered] = useState(() => new Set()); // ids of ticked points
  const [fresh, setFresh] = useState(() => new Set()); // ids ticked in the last few seconds (highlighted)
  const [showMissed, setShowMissed] = useState(false);
  const [issues, setIssues] = useState([]); // corrections found by "Check me"
  const [checkJob, setCheckJob] = useState(null); // id of the check in progress
  const [checkStatus, setCheckStatus] = useState("idle"); // idle | running | done | error
  const [checkMessage, setCheckMessage] = useState("");
  const [showCheck, setShowCheck] = useState(false);
  const [ending, setEnding] = useState(false);

  // Things the audio callbacks need, kept in refs so they are always current.
  const stopMicRef = useRef(null); // function that turns the mic off
  const queueRef = useRef([]); // chunks waiting to be sent: [{seq, chunk}]
  const sendingRef = useRef(false);
  const nextSeqRef = useRef(0);
  const micLabelRef = useRef(""); // e.g. "16000hz-ns-on", sent along for the backend log
  const meterRef = useRef(null); // the level meter's bar (updated directly: it changes many times a second)

  const generating = status === "generating";

  // Take the outline the backend sent and show it.
  function applyServerOutline(outline) {
    setPoints(withKeys(outline.points));
    setStatus(outline.status);
    setSource(outline.source);
    setMessage(outline.message);
    setProgress(outline.progress);
    setDirty(false);
  }

  // Load the session once when the screen opens.
  useEffect(() => {
    let cancelled = false;
    getSession(sessionId)
      .then((data) => {
        if (cancelled) return;
        setSession(data);
        applyServerOutline(data.outline);
        // Coming back to a session that was already started (e.g. after a reload).
        setTranscript(data.transcript);
        setIssues(data.issues);
        setCovered(new Set(Object.keys(data.covered).filter((id) => data.covered[id].covered)));
        setElapsed(data.audio_seconds || 0);
        nextSeqRef.current = data.transcript.reduce((max, line) => Math.max(max, line.seq + 1), 0);
        if (data.started_at) setLive(true);
      })
      .catch((e) => !cancelled && setLoadError(e.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // While Gemma is working, ask the backend for progress every 2 seconds.
  useEffect(() => {
    if (!generating) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const outline = await getOutline(sessionId);
        if (cancelled) return;
        setError("");
        if (outline.status === "generating") setProgress(outline.progress);
        else applyServerOutline(outline); // Gemma finished: swap its outline in
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [generating, sessionId]);

  // The timer counts only while the mic is on.
  useEffect(() => {
    if (!micOn) return;
    const timer = setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    return () => clearInterval(timer);
  }, [micOn]);

  // Leaving the screen turns the mic off.
  useEffect(() => () => stopMicRef.current?.(), []);

  function edit(newPoints) {
    setPoints(newPoints);
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      const body = points.map((p) => ({ id: p.id, text: p.text, slide: p.slide }));
      applyServerOutline(await saveOutline(sessionId, body));
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  // ----- ticks -----

  // Highlight newly ticked points for a moment, so the eye catches them.
  function highlight(ids) {
    if (ids.length === 0) return;
    setFresh((old) => new Set([...old, ...ids]));
    setTimeout(() => {
      setFresh((old) => new Set([...old].filter((id) => !ids.includes(id))));
    }, FRESH_MS);
  }

  // Manual tick / untick.
  async function handleToggle(pointId) {
    try {
      const result = await togglePoint(sessionId, pointId);
      setCovered(new Set(result.covered));
    } catch (e) {
      setError(e.message);
    }
  }

  // ----- "Check me" (Gemma; slow, so it runs in the background) -----

  async function handleCheck() {
    setShowCheck(true);
    setShowMissed(false);
    if (checkStatus === "running") return; // one at a time
    setCheckStatus("running");
    setCheckMessage("");
    try {
      const { job_id } = await startCheck(sessionId);
      setCheckJob(job_id);
    } catch (e) {
      setCheckStatus("error");
      setCheckMessage(e.message);
    }
  }

  // While a check runs, ask for its result every 2 seconds.
  useEffect(() => {
    if (checkStatus !== "running" || !checkJob) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const job = await getCheck(sessionId, checkJob);
        if (cancelled || job.status === "running") return;
        setCheckStatus(job.status);
        setCheckMessage(job.message);
        setCheckJob(null);
        if (job.issues.length > 0) setIssues((old) => [...job.issues, ...old]); // newest first
      } catch (e) {
        if (cancelled) return;
        setCheckStatus("error");
        setCheckMessage(e.message);
        setCheckJob(null);
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [checkStatus, checkJob, sessionId]);

  // "That's not what I said": hide it, and keep it out of the recap.
  async function handleDismiss(issueId) {
    try {
      await dismissIssue(sessionId, issueId);
      setIssues((old) => old.map((issue) => (issue.id === issueId ? { ...issue, dismissed: true } : issue)));
    } catch (e) {
      setError(e.message);
    }
  }

  // ----- audio: mic -> queue -> backend, one chunk at a time -----

  function stopMic() {
    stopMicRef.current?.(); // also hands us the last partial chunk
    stopMicRef.current = null;
    setMicOn(false);
  }

  // Send queued chunks in order. Never two at once: the laptop transcribes one at a time.
  async function sendQueue() {
    if (sendingRef.current) return;
    sendingRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const { seq, chunk } = queueRef.current[0];
        const result = await sendAudio(sessionId, seq, chunk, micLabelRef.current);
        queueRef.current.shift();
        setWaiting(queueRef.current.length);
        if (result.text) {
          setTranscript((lines) => [...lines, { seq: result.seq, at: result.at, text: result.text }]);
        }
        setCovered(new Set(result.covered));
        highlight(result.newly_covered);
      }
    } catch (e) {
      queueRef.current = [];
      setWaiting(0);
      setError(`${e.message} Listening is paused.`);
      stopMic();
    } finally {
      sendingRef.current = false;
    }
  }

  function handleChunk(chunk) {
    queueRef.current.push({ seq: nextSeqRef.current++, chunk });
    setWaiting(queueRef.current.length);
    sendQueue();
  }

  function handleLevel(level) {
    if (meterRef.current) meterRef.current.style.width = `${Math.round(level * 100)}%`;
  }

  async function toggleMic() {
    if (micOn) {
      stopMic();
      return;
    }
    setStarting(true);
    setError("");
    try {
      if (!live) {
        // Lock in the outline as it is now (this also stops Gemma if it is still working).
        if ((dirty || generating) && !(await save())) return;
        await startSession(sessionId);
        setLive(true);
      }
      const mic = await startMic({ chunkSeconds: CHUNK_SECONDS, onChunk: handleChunk, onLevel: handleLevel });
      stopMicRef.current = mic.stop;
      micLabelRef.current = mic.label;
      setMicOn(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  }

  function backToOutline() {
    stopMic();
    setLive(false);
  }

  // End the session and open the recap.
  async function handleEnd() {
    setEnding(true);
    setError("");
    try {
      stopMic();
      // Wait until the last chunks are transcribed, so the recap is complete.
      while (sendingRef.current || queueRef.current.length > 0) {
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      await endSession(sessionId);
      onEnd();
    } catch (e) {
      setError(e.message);
      setEnding(false);
    }
  }

  if (loadError) {
    return (
      <section>
        <button type="button" className="link" onClick={onBack}>← New session</button>
        <p className="error" role="alert">{loadError}</p>
      </section>
    );
  }
  if (!session) return <p className="muted">Opening your session…</p>;

  const unit = session.unit || "Slide";
  const percent = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const started = live || transcript.length > 0;
  const coveredCount = points.filter((p) => covered.has(p.id)).length;
  const openIssues = issues.filter((issue) => !issue.dismissed).length;
  const coveredPercent = points.length ? Math.round((coveredCount / points.length) * 100) : 0;

  let micTitle = "Start listening";
  if (micOn) micTitle = "Listening";
  else if (starting) micTitle = "Starting…";
  else if (started) micTitle = live ? "Paused" : "Resume listening";

  let micNote = "Keep this beside your call. Nkuzi hears only your mic.";
  if (micOn || live) {
    const lag = waiting > 2 ? `falling behind (${waiting} chunks waiting)` : waiting > 0 ? "transcribing…" : "";
    micNote = [clock(elapsed), `${coveredCount} / ${points.length} points covered`, lag].filter(Boolean).join(" · ");
  }

  return (
    <section className="session">
      <button type="button" className="link" onClick={onBack}>← New session</button>
      <h1 className="screen-title">{session.title}</h1>
      {session.explainer && <p className="muted session-meta">Explained by {session.explainer}</p>}

      {/* The mic bar stays in view while the checklist scrolls. */}
      <div className={micOn ? "listen-bar on" : "listen-bar"}>
        <button
          type="button"
          className="mic-button"
          onClick={toggleMic}
          disabled={saving || starting}
          aria-pressed={micOn}
          aria-label={micOn ? "Pause listening" : "Start listening"}
        >
          {micOn ? <PauseIcon /> : <MicIcon />}
        </button>
        <div className="listen-text">
          <div className="listen-title">{micTitle}</div>
          <div className="listen-note">{micNote}</div>
          {micOn && (
            <div className="meter" aria-hidden="true">
              <div className="meter-fill" ref={meterRef} />
            </div>
          )}
        </div>
        {live && (
          <div className="listen-actions">
            <button
              type="button"
              className="button small"
              onClick={() => {
                setShowMissed(!showMissed);
                setShowCheck(false);
              }}
              aria-expanded={showMissed}
            >
              What did I miss?
            </button>
            <button
              type="button"
              className="button small"
              onClick={handleCheck}
              aria-expanded={showCheck}
              disabled={Boolean(checkBlocked)}
              title={checkBlocked ? `Check me is off: ${checkBlocked}` : ""}
            >
              {checkStatus === "running" ? "Checking…" : "Check me"}
              {openIssues > 0 && checkStatus !== "running" && <span className="badge">{openIssues}</span>}
            </button>
            <button type="button" className="button small" onClick={backToOutline}>
              Edit outline
            </button>
          </div>
        )}
        {live && checkBlocked && <div className="listen-hint">Check me is off: {checkBlocked}</div>}
        {live && (
          <div className="progress listen-progress" role="progressbar" aria-label="Points covered" aria-valuenow={coveredPercent} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${coveredPercent}%` }} />
          </div>
        )}
      </div>

      {live && showMissed && (
        <MissedPanel points={points} covered={covered} unit={unit} onClose={() => setShowMissed(false)} />
      )}
      {live && showCheck && (
        <CorrectionsPanel
          issues={issues}
          status={checkStatus}
          message={checkMessage}
          unit={unit}
          onDismiss={handleDismiss}
          onClose={() => setShowCheck(false)}
        />
      )}

      {session.warning && <p className="banner warn">{session.warning}</p>}

      {!live && generating && (
        <div className="banner">
          <div className="banner-row">
            <span>
              Gemma is reading your slides… {progress.done}/{progress.total || "?"}
            </span>
            <button type="button" className="button small" disabled={saving} onClick={save}>
              Stop and edit this one
            </button>
          </div>
          <div className="progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <div className="banner-note">Below is a quick outline from your slides. You can start with it now.</div>
        </div>
      )}
      {!live && !generating && source === "gemma" && (
        <p className="banner ok">Generated by Gemma, running on this laptop. Every point is checked against your slides.</p>
      )}
      {!live && status === "fallback_only" && (
        <p className="banner warn">
          Built from your slides without Gemma.{message && ` Reason: ${message}`}
        </p>
      )}
      {!live && status === "ready" && message && <p className="banner warn">{message}</p>}

      {error && <p className="error" role="alert">{error}</p>}

      {live ? (
        <>
          <Transcript lines={transcript} micOn={micOn} />
          {points.length === 0 ? (
            <p className="banner">Your outline is empty. Press "Edit outline" and add the points you want to cover.</p>
          ) : (
            <Checklist points={points} slides={session.slides} unit={unit} covered={covered} fresh={fresh} onToggle={handleToggle} />
          )}
          <div className="actions">
            <button type="button" className="button primary" onClick={handleEnd} disabled={ending}>
              {ending ? "Finishing…" : "End session and see recap"}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="muted outline-hint">
            {session.slides.length} {unit.toLowerCase()}s · {points.length} points. This is your checklist: fix anything
            that looks wrong before you start.
          </p>
          <EditableOutline points={points} unit={unit} locked={generating} onEdit={edit} />
          {!generating && (
            <div className="actions">
              <button type="button" className="button" disabled={!dirty || saving} onClick={save}>
                {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
