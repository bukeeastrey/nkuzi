import { useRef, useState } from "react";
import { createSession } from "../api.js";
import { APP_NAME, TAGLINE } from "../config.js";

const ACCEPTED = [".pdf", ".pptx", ".docx"];
const OLD_FORMATS = [".ppt", ".doc"];

function extensionOf(file) {
  const dot = file.name.lastIndexOf(".");
  return dot === -1 ? "" : file.name.slice(dot).toLowerCase();
}

// The form: topic, explainer name and the slides file.
function NewSessionForm({ onCreated }) {
  const [title, setTitle] = useState("");
  const [explainer, setExplainer] = useState("");
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  function chooseFile(chosen) {
    if (!chosen) return;
    const extension = extensionOf(chosen);
    if (OLD_FORMATS.includes(extension)) {
      setError("Please open this in PowerPoint/Word and Save As .pptx/.docx.");
      return;
    }
    if (!ACCEPTED.includes(extension)) {
      setError("Nkuzi reads .pdf, .pptx and .docx files.");
      return;
    }
    setError("");
    setFile(chosen);
  }

  function onDrop(event) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (!file) {
      setError("Add your slides first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await createSession({ file, title, explainer });
      onCreated(created.session_id);
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
        <span className="field-label">Slides</span>
        <div
          className={dragging ? "dropzone dragging" : "dropzone"}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {file ? (
            <p className="dropzone-file">{file.name}</p>
          ) : (
            <p className="muted">Drag a PDF, PowerPoint or Word file here, or</p>
          )}
          <button type="button" className="button" onClick={() => fileInput.current.click()}>
            {file ? "Choose a different file" : "Choose file"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPTED.join(",")}
            hidden
            onChange={(e) => chooseFile(e.target.files[0])}
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
      <NewSessionForm onCreated={onCreated} />
    </section>
  );
}
