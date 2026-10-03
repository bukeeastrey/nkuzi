import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// LAN mode (started by run-lan.ps1, which sets NKUZI_LAN=1) lets a friend on
// the same Wi-Fi or hotspot open Nkuzi from their own laptop or phone:
//   - the dev server listens on the network, not just on this laptop
//   - it uses HTTPS with a self-made certificate, because browsers only allow
//     the microphone on https:// pages (or on localhost)
//   - it uses its own port, so the normal `npm run dev` can stay running
const lan = process.env.NKUZI_LAN === "1";

export default defineConfig({
  plugins: [react(), ...(lan ? [basicSsl()] : [])],
  server: {
    host: lan, // true = listen on every network address
    port: lan ? 5174 : 5173,
    strictPort: true, // fail clearly if the port is taken, rather than moving to another
    // Anything starting with /api is forwarded to the Python backend, which
    // itself only listens on this laptop. Visitors never talk to it directly.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
