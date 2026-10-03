// The app name lives here (frontend) and in backend/app/config.py. Nowhere else.
export const APP_NAME = "Nkuzi";
export const TAGLINE = "Your study-group co-pilot. Runs offline.";

// Vite forwards /api to the Python backend (see vite.config.js).
export const API_BASE = "/api";

// Length of each audio chunk sent to the backend. Must match backend CHUNK_SECONDS.
export const CHUNK_SECONDS = 8;
