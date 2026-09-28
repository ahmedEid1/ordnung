import { defineConfig, devices } from "@playwright/test";
import { BASE_URL, DATA_DIR, ORDNUNG_BIN, OUTPUT_DIR, PORT, STORAGE_STATE } from "./e2e/env";

/**
 * End-to-end tests against the real demo (FastAPI + the built UI from `npm run build`, recorded
 * Claude answers). One fresh demo server (`--reset`) per run; the tests share it, so they run in
 * one worker, in order — the demo's New-mail letters and tour are shared state.
 *
 * Local: `npm run build && PW_CHROMIUM_PATH=/path/to/chrome npm run e2e`. See `e2e/env.ts` for
 * the knobs (port, data folder, reuse a running server).
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: OUTPUT_DIR,
  // `e2e/*.ts` helpers import the app's own copy tables (`@/lib/copy`)
  tsconfig: "./tsconfig.node.json",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: BASE_URL,
    storageState: STORAGE_STATE,
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "Europe/Berlin",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  // Same browser twice, only to fix the order: the guided tour runs first, on the untouched demo
  // (before other tests open New-mail letters); then every page, then the layout guards (with the
  // feedback components: toasts, stepper, receipts — and the app shell), and last the high-stakes
  // letters, which re-file demo letters (PATCH kind) and so add the law's to-dos to the shared demo.
  // The GiroCode guards run between the two: they change the parking fine's amount (PATCH) to ask for the
  // paper letter again, and an edited to-do stays marked as edited when its amount is set back — Ask's
  // recorded answers replay only against the untouched demo, so the layout project's Ask guards come first.
  // One worker runs projects in order.
  projects: [
    { name: "tour", testMatch: /tour\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "pages", testMatch: /pages\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    {
      name: "layout",
      testMatch: /(layout|feedback|shell)\.spec\.ts$/,
      testIgnore: /girocode-layout\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    { name: "girocode", testMatch: /girocode-layout\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "high-stakes", testMatch: /high-stakes\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `"${ORDNUNG_BIN}" demo --serve --no-browser --port ${PORT} --data-dir "${DATA_DIR}" --reset`,
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
    stdout: "ignore",
    stderr: "pipe",
    timeout: 120_000,
  },
});
