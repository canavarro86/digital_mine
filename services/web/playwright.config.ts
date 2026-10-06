import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.BASE_URL || "http://127.0.0.1:9999", viewport: { width: 1440, height: 900 }, locale: "ru-RU" },
});
