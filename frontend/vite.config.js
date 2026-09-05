import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Builds straight into the exact directory FastAPI already serves at /ui —
// src/torque/api/ui.py and app.py are untouched. Dev mode proxies API calls
// to the FastAPI backend on :8000 so `npm run dev` needs no backend change
// either.
export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: path.resolve(__dirname, "../src/torque/ui/static"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/reports": "http://127.0.0.1:8000",
      "/agent-console": "http://127.0.0.1:8000",
      "/ai": "http://127.0.0.1:8000",
      "/demo": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/webhooks": "http://127.0.0.1:8000",
      "/internal": "http://127.0.0.1:8000",
    },
  },
});
