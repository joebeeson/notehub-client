import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testIgnore: "**/workspace.spec.mjs",
  outputDir: "./test-results",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173/dashboard/",
    reuseExistingServer: false,
  },
});
