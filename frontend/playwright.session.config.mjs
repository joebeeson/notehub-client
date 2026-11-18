import base from "./playwright.config.mjs";

export default {
  ...base,
  testIgnore: [],
  testMatch: "**/workspace.spec.mjs",
  workers: 1,
  use: { ...base.use, baseURL: "http://127.0.0.1:4174" },
  webServer: {
    command: "uv run --no-sync python tests/browser/session_server.py",
    url: "http://127.0.0.1:4174/smoke/state",
    reuseExistingServer: false,
  },
};
