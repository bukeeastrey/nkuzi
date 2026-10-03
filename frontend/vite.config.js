import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // the backend's CORS setting expects exactly this port
    // Anything starting with /api is forwarded to the Python backend.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
