import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The gateway has no CORS: the browser talks to the same origin and Vite forwards /v1 to hop ① (Toxiproxy :18081),
// so the web client goes through exactly the same faults as the phones. MEDSYNC_GATEWAY overrides the target.
const gateway = process.env.MEDSYNC_GATEWAY ?? "http://127.0.0.1:18081";
const proxy = { "/v1": { target: gateway, changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  test: { environment: "node" },
});
