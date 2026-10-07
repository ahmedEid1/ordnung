import { defineConfig, devices } from "@playwright/test";
import {
  BASE_URL,
  DATA_DIR,
  FAKE_CLAUDE_SCENARIO,
  ORDNUNG_BIN,
  OUTPUT_DIR,
  PHONE_ADDRESS,
  PHONE_TEST_ADDRESS_ENV,
  PORT,
  REAL_BASE_URL,
  REAL_CLAUDE,
  REAL_DATA_DIR,
  REAL_PORT,
  REAL_STORAGE_STATE,
  STORAGE_STATE,
} from "./e2e/env";

/**
 * End-to-end tests against the real demo (FastAPI + the built UI from `npm run build`, recorded
 * Claude answers), then against the real app (`ordnung serve` on its own data folder, with the fake
 * `claude` of tests/fake_claude.py). One fresh demo server (`--reset`) per run, and the real app's data
 * deleted at the start of each run (e2e/global-setup.ts); the tests share them, so they run in one
 * worker, in order — the demo's New-mail letters and tour are shared state. The real app's phone access
 * (e2e/real-app-phone.spec.ts) listens on loopback only (`ORDNUNG_PHONE_TEST_ADDRESS`, e2e/env.ts), on the
 * port after the real app's, while that spec turns it on.
 *
 * Local: `npm run build && PW_CHROMIUM_PATH=/path/to/chrome npm run e2e`. See `e2e/env.ts` for
 * the knobs (ports, data folders, reuse running servers).
 */
const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };
/** The real app's specs: these files run in the project "real-app" only. */
const REAL_APP_SPECS = /real-app-[\w-]+\.spec\.ts$/;

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
  // no retries, in CI either: a test that passes only on its second try is a failure to look at
  retries: 0,
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
  // Same browser every time, only to fix the order: the guided tour runs first, on the untouched demo
  // (before other tests open New-mail letters); then every page, then the layout sweep (every page and key
  // state at 320–1920 px in light and dark: e2e/layout-sweep.spec.ts), then the layout guards (with the
  // feedback components: toasts, stepper, receipts — and the app shell), and last the high-stakes
  // letters, which re-file demo letters (PATCH kind) and so add the law's to-dos to the shared demo.
  // The GiroCode guards run between the two: they change the parking fine's amount (PATCH) to ask for the
  // paper letter again, and an edited to-do stays marked as edited when its amount is set back — Ask's
  // recorded answers replay only against the untouched demo, so the layout project's Ask guards come first.
  // Then dates of the person's own (e2e/add-date.spec.ts: added to the shared demo, then taken away), and last
  // the real app: e2e/real-app-*.spec.ts, against `ordnung serve`.
  // One worker runs projects in order.
  projects: [
    { name: "tour", testMatch: /tour\.spec\.ts$/, use: desktop },
    { name: "pages", testMatch: /pages\.spec\.ts$/, use: desktop },
    // it changes nothing and asks Ask a recorded question, on the demo as `pages` left it. It opens its own
    // contexts, dozens per test: no traces or failure screenshots of them (it attaches the first failing view
    // of each state itself)
    {
      name: "sweep",
      testMatch: /layout-sweep\.spec\.ts$/,
      use: { ...desktop, trace: "off", screenshot: "off" },
    },
    {
      name: "layout",
      testMatch: /(layout|feedback|shell)\.spec\.ts$/,
      testIgnore: [/girocode-layout\.spec\.ts$/, REAL_APP_SPECS],
      use: desktop,
    },
    { name: "girocode", testMatch: /girocode-layout\.spec\.ts$/, use: desktop },
    { name: "high-stakes", testMatch: /high-stakes\.spec\.ts$/, use: desktop },
    { name: "add-date", testMatch: /add-date\.spec\.ts$/, use: desktop },
    { name: "real-app", testMatch: REAL_APP_SPECS, use: { ...desktop, baseURL: REAL_BASE_URL, storageState: REAL_STORAGE_STATE } },
  ],
  webServer: [
    {
      command: `"${ORDNUNG_BIN}" demo --serve --no-browser --port ${PORT} --data-dir "${DATA_DIR}" --reset`,
      url: `${BASE_URL}/api/health`,
      reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
    {
      command: `"${ORDNUNG_BIN}" serve --no-browser --port ${REAL_PORT} --data-dir "${REAL_DATA_DIR}"`,
      url: `${REAL_BASE_URL}/api/health`,
      // phone access may listen on loopback only (the one address it is then offered), never on a network
      env: { ORDNUNG_CLAUDE_BIN: REAL_CLAUDE, FAKE_CLAUDE_SCENARIO, [PHONE_TEST_ADDRESS_ENV]: PHONE_ADDRESS },
      reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
  ],
});
