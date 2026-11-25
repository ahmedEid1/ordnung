import { defineConfig, devices, type PlaywrightTestConfig, type Project } from "@playwright/test";
import {
  BASE_URL,
  DATA_DIR,
  DEMO_PROJECTS,
  E2E_GROUPS,
  E2E_OCR,
  FAKE_CLAUDE_SCENARIO,
  keyringEnv,
  ORDNUNG_BIN,
  OUTPUT_DIR,
  PHONE_ADDRESS,
  PHONE_TEST_ADDRESS_ENV,
  PORT,
  REAL_B_BASE_URL,
  REAL_B_DATA_DIR,
  REAL_B_KEYRING,
  REAL_B_PORT,
  REAL_BASE_URL,
  REAL_CLAUDE,
  REAL_DATA_DIR,
  REAL_KEYRING,
  REAL_PORT,
  REAL_APP_PROJECTS,
  REAL_STORAGE_STATE,
  runsProject,
  RUNS_DEMO,
  RUNS_REAL_APPS,
  STORAGE_STATE,
} from "./e2e/env";

/**
 * End-to-end tests against the real demo (FastAPI + the built UI from `npm run build`, recorded
 * Claude answers), then against the real app (`ordnung serve` on its own data folder, with the fake
 * `claude` of tests/fake_claude.py). One fresh demo server (`--reset`) per run, and the real app's data
 * deleted at the start of each run (e2e/global-setup.ts); the tests share them, so they run in one
 * worker, in order — the demo's New-mail letters and tour are shared state. The real app's phone access
 * (e2e/real-app-phone.spec.ts) listens on loopback only (`ORDNUNG_PHONE_TEST_ADDRESS`, e2e/env.ts), on the
 * port after the real app's, while that spec turns it on. Hand-off sync (e2e/real-app-sync.spec.ts) needs a
 * second computer: another `ordnung serve` on its own data folder, on the port after that. Both real apps keep
 * their secrets in a password store of their own made for the tests (`tests/e2e_support/e2e_keyring.py`): CI's
 * Linux has no keyring, and Ordnung refuses the ones that don't keep passwords safely. No server reads the words in
 * pictures (`ORDNUNG_OCR=off`, ADR 0024) but the real app with `ORDNUNG_E2E_OCR=on` (e2e/env.ts), so a Tesseract
 * installed here changes nothing else.
 *
 * `E2E_GROUP=<name>` (e2e/env.ts) runs one group of the projects below, in the same order, on fresh servers of its
 * own and only those its projects use, so CI can run the groups as jobs side by side. Unset, everything runs, as described.
 * CI runs the layout group in four parts with `--shard`, each on a fresh demo. A part is a run of whole files in the
 * group's order, and a layout file needs nothing a file before it did, so any such split works. The order still
 * counts on one demo: some files need what a later one changes as the demo ships it (Ask's recorded answers, a
 * contract's notice period), and the four parts run last to first on one demo failed five tests.
 *
 * Local: `npm run build && PW_CHROMIUM_PATH=/path/to/chrome npm run e2e`. See `e2e/env.ts` for
 * the knobs (ports, data folders, reuse running servers, groups).
 */
const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };
/** The real app's specs: these files run in the project "real-app" only. */
const REAL_APP_SPECS = /real-app-[\w-]+\.spec\.ts$/;
/** The guide's two screenshots from the real app: made only by `make capture` (it sets ORDNUNG_CAPTURE_OUT), else skipped. */
const PICTURES_SPEC = /readme-pictures\.spec\.ts$/;

/** One `webServer` entry. */
type WebServer = Exclude<NonNullable<PlaywrightTestConfig["webServer"]>, unknown[]>;

/**
 * The projects this run takes: all of them, or `E2E_GROUP`'s, in the order given. First it checks the groups
 * (e2e/env.ts) against `projects`: together they hold each project exactly once, each in the order of the whole
 * run, and the projects said to use the demo or the real apps are projects.
 */
function projectsOfThisRun(projects: Project[]): Project[] {
  const names = projects.map((project) => project.name ?? "");
  const grouped = Object.values(E2E_GROUPS).flat();
  const problem = (why: string) => new Error(`e2e/env.ts: ${why} (the projects: ${names.join(", ")})`);
  if (grouped.length !== names.length || names.some((name) => !grouped.includes(name))) {
    throw problem(`E2E_GROUPS must hold each project exactly once, not ${grouped.join(", ")}`);
  }
  for (const [group, members] of Object.entries(E2E_GROUPS)) {
    const at = members.map((name) => names.indexOf(name));
    if (at.some((index, i) => i > 0 && index < at[i - 1])) throw problem(`group ${group} must keep the run's order`);
  }
  const unknown = [...DEMO_PROJECTS, ...REAL_APP_PROJECTS].filter((name) => !names.includes(name));
  if (unknown.length) throw problem(`no project ${unknown.join(", ")}`);
  return projects.filter((project) => runsProject(project.name ?? ""));
}

/** The servers this run's projects use, in the order given: the demo, or the real app and the second computer. */
const serversOfThisRun = (servers: WebServer[]): WebServer[] => servers.filter((server) => (server.name === "demo" ? RUNS_DEMO : RUNS_REAL_APPS));

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
  // feedback components: toasts, stepper, receipts — the app shell, a sender's state suggested from the postcode
  // on their letter: Yes on the demo is set back, and the screens fed by the lighter letter list), and last the high-stakes
  // letters, which re-file demo letters (PATCH kind) and so add the law's to-dos to the shared demo.
  // The GiroCode guards run between the two: they change the parking fine's amount (PATCH) to ask for the
  // paper letter again, and an edited to-do stays marked as edited when its amount is set back — Ask's
  // recorded answers replay only against the untouched demo, so the layout project's Ask guards come first.
  // Then dates of the person's own (e2e/add-date.spec.ts: added to the shared demo, then taken away), then
  // the real app: e2e/real-app-*.spec.ts, against `ordnung serve` (real-app-sync.spec.ts with the second one);
  // and last the guide's two screenshots from the real app (e2e/readme-pictures.spec.ts), which run only for
  // `make capture`. One worker runs projects in order.
  projects: projectsOfThisRun([
    { name: "tour", testMatch: /tour\.spec\.ts$/, use: desktop },
    { name: "pages", testMatch: /pages\.spec\.ts$/, use: desktop },
    // it changes nothing and asks Ask a recorded question, on the demo as `pages` left it (in CI, on a fresh demo
    // of its own: its group, e2e/env.ts). It opens its own
    // contexts, dozens per test: no traces or failure screenshots of them (it attaches the first failing view
    // of each state itself)
    {
      name: "sweep",
      testMatch: /layout-sweep\.spec\.ts$/,
      use: { ...desktop, trace: "off", screenshot: "off" },
    },
    {
      name: "layout",
      testMatch: /(layout|feedback|shell|sender-land|letter-list-rows)\.spec\.ts$/,
      testIgnore: [/girocode-layout\.spec\.ts$/, REAL_APP_SPECS],
      use: desktop,
    },
    { name: "girocode", testMatch: /girocode-layout\.spec\.ts$/, use: desktop },
    { name: "high-stakes", testMatch: /high-stakes\.spec\.ts$/, use: desktop },
    { name: "add-date", testMatch: /add-date\.spec\.ts$/, use: desktop },
    // the evaluation's report page, built from presentation.json into a folder of its own: no server, no shared state
    { name: "eval-report", testMatch: /eval-report\.spec\.ts$/, use: desktop },
    { name: "real-app", testMatch: REAL_APP_SPECS, use: { ...desktop, baseURL: REAL_BASE_URL, storageState: REAL_STORAGE_STATE } },
    { name: "pictures", testMatch: PICTURES_SPEC, use: { ...desktop, baseURL: REAL_BASE_URL, storageState: REAL_STORAGE_STATE, colorScheme: "light" } },
  ]),
  // started only for a run that takes one of their projects (E2E_GROUP), in this order
  webServer: serversOfThisRun([
    {
      name: "demo",
      command: `"${ORDNUNG_BIN}" demo --serve --no-browser --port ${PORT} --data-dir "${DATA_DIR}" --reset`,
      url: `${BASE_URL}/api/health`,
      env: { ORDNUNG_OCR: "off" },
      reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
    {
      name: "real app",
      command: `"${ORDNUNG_BIN}" serve --no-browser --port ${REAL_PORT} --data-dir "${REAL_DATA_DIR}"`,
      url: `${REAL_BASE_URL}/api/health`,
      // phone access may listen on loopback only (the one address it is then offered), never on a network
      // it reads the words in pictures only when the run asks (ORDNUNG_E2E_OCR=on, with Tesseract installed)
      env: {
        ORDNUNG_CLAUDE_BIN: REAL_CLAUDE,
        FAKE_CLAUDE_SCENARIO,
        [PHONE_TEST_ADDRESS_ENV]: PHONE_ADDRESS,
        ORDNUNG_OCR: E2E_OCR ? "on" : "off",
        ...keyringEnv(REAL_KEYRING),
      },
      reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
    {
      // hand-off sync's other computer: a data folder and a password store of its own, the same fake Claude
      name: "second computer",
      command: `"${ORDNUNG_BIN}" serve --no-browser --port ${REAL_B_PORT} --data-dir "${REAL_B_DATA_DIR}"`,
      url: `${REAL_B_BASE_URL}/api/health`,
      env: { ORDNUNG_CLAUDE_BIN: REAL_CLAUDE, FAKE_CLAUDE_SCENARIO, ORDNUNG_OCR: "off", ...keyringEnv(REAL_B_KEYRING) },
      reuseExistingServer: process.env.ORDNUNG_E2E_REUSE === "1",
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
  ]),
});
