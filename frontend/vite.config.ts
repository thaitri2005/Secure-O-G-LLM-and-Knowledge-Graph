/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs beside the frontend in development (python -m uvicorn backend.app:app --port 8000); behind the
// proxy in deployment both share one origin, so the frontend always calls /v1 on its own host.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // public/ holds only the example page image; the production files do not carry it.
  publicDir: mode === "examples" ? "public" : false,
  server: {
    proxy: { "/v1": "http://127.0.0.1:8000" },
    fs: { allow: [".."] }, // the example responses live in ../backend/fixtures
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false, testTimeout: 15000 },
}));
