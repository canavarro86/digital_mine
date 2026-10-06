import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:9999" } },
  build: { chunkSizeWarningLimit: 1500, sourcemap: false },
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
} as never);
