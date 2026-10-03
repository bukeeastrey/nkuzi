import { API_BASE } from "./config.js";

const BACKEND_DOWN = "Can't reach the Nkuzi backend. Start it with .\\run.ps1 in the backend folder.";

// Small wrapper around fetch: returns JSON, or throws an Error with a
// friendly message that screens can show as-is.
async function request(path, options) {
  let response;
  try {
    response = await fetch(API_BASE + path, options);
  } catch {
    throw new Error(BACKEND_DOWN);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    // The backend's own errors carry a readable "detail" message.
    if (body && typeof body.detail === "string") throw new Error(body.detail);
    // No readable body + 5xx = Vite's proxy couldn't reach the backend.
    if (response.status >= 500) throw new Error(BACKEND_DOWN);
    throw new Error(`Something went wrong (error ${response.status}).`);
  }
  return response.json();
}

export function getHealth() {
  return request("/health");
}

// Upload the slides and create a session.
export function createSession({ file, title, explainer }) {
  const form = new FormData();
  form.append("pdf", file); // the field is called "pdf", but .pptx and .docx work too
  form.append("title", title);
  form.append("explainer", explainer);
  return request("/sessions", { method: "POST", body: form });
}

// Everything about one session: title, slides, outline...
export function getSession(sessionId) {
  return request(`/sessions/${sessionId}`);
}

export function getOutline(sessionId) {
  return request(`/sessions/${sessionId}/outline`);
}

// Save the outline as edited by the explainer. points: [{id, text, slide}]
export function saveOutline(sessionId, points) {
  return request(`/sessions/${sessionId}/outline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ points }),
  });
}

// Mark the moment the explanation starts.
export function startSession(sessionId) {
  return request(`/sessions/${sessionId}/start`, { method: "POST" });
}

// Send one chunk of microphone audio (Int16Array, 16 kHz mono).
// Returns {seq, text, at, whisper_seconds, newly_covered, covered, covered_count, total}.
// micLabel: short description of the mic setup (e.g. "16000hz-ns-on"), for the backend log.
export function sendAudio(sessionId, seq, chunk, micLabel = "") {
  return request(`/sessions/${sessionId}/audio?seq=${seq}&mic=${encodeURIComponent(micLabel)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: chunk,
  });
}

// Tick or untick a point by hand. Returns {covered: [ids], covered_count, total}.
export function togglePoint(sessionId, pointId) {
  return request(`/sessions/${sessionId}/points/${pointId}/toggle`, { method: "POST" });
}
