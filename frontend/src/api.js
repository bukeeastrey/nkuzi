import { API_BASE } from "./config.js";

// Small wrapper around fetch: returns JSON, or throws an Error with a
// friendly message that screens can show as-is.
async function request(path, options) {
  let response;
  try {
    response = await fetch(API_BASE + path, options);
  } catch {
    throw new Error("Can't reach the Nkuzi backend. Start it with .\\run.ps1 in the backend folder.");
  }
  if (!response.ok) {
    // Vite's proxy answers 500/502/504 when the backend is not running.
    if (response.status >= 500) {
      throw new Error("Can't reach the Nkuzi backend. Start it with .\\run.ps1 in the backend folder.");
    }
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export function getHealth() {
  return request("/health");
}
