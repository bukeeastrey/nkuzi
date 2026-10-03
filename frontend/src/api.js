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
export function createSession({ pdf, title, explainer }) {
  const form = new FormData();
  form.append("pdf", pdf);
  form.append("title", title);
  form.append("explainer", explainer);
  return request("/sessions", { method: "POST", body: form });
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
