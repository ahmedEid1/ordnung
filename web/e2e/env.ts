/**
 * Where the e2e servers run and where their sessions live: the demo, the real app (`ordnung serve`
 * on its own data folder, port + 1, reading with the fake `claude` of `tests/fake_claude.py`), and a second
 * real app, the other computer of hand-off sync (port + 3). Shared by `playwright.config.ts`, the global setup
 * and the tests.
 *
 * - `ORDNUNG_E2E_PORT` (default 8799) and `ORDNUNG_E2E_DATA` (default `<tmp>/ordnung-e2e`, taken where it really
 *   is: {@link realPath}); the real app
 *   uses the next port and `<data>-real`, its phone access (e2e/real-app-phone.spec.ts) the port after that, and
 *   hand-off sync's second computer (e2e/real-app-sync.spec.ts) the port after that with `<data>-real-b`; the two
 *   computers' copies of the synced folder are `<data>-sync-a` and `<data>-sync-b`
 * - `ORDNUNG_BIN`: the `ordnung` executable (default: the repo's `.venv/bin/ordnung`, else `ordnung` on PATH)
 * - `ORDNUNG_E2E_REUSE=1`: reuse servers that are already running on the ports (local debugging); a real app
 *   started by hand needs `ORDNUNG_PHONE_TEST_ADDRESS=127.0.0.1` for the phone tests (see {@link PHONE_ADDRESS}),
 *   and both real apps need the e2e password store's environment for the sync tests ({@link keyringEnv})
 * - `PW_CHROMIUM_PATH`: a Chromium executable to use instead of Playwright's download
 * - `ORDNUNG_E2E_OCR=on`: the real app reads the words in pictures with the Tesseract installed here (ADR 0024;
 *   CI's end-to-end job, with Tesseract and its German data); without it every server runs with `ORDNUNG_OCR=off`
 * - `E2E_GROUP=<name>`: run one group of projects ({@link E2E_GROUPS}) on fresh servers of its own, only those it uses
 */
import { existsSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export const WEB_DIR = resolve(here, "..");
export const PORT = Number(process.env.ORDNUNG_E2E_PORT ?? 8799);
export const BASE_URL = `http://127.0.0.1:${PORT}`;
/**
 * `path` where it really is, links followed, also when it doesn't exist yet: the app resolves every folder it is
 * given (Python's `Path.resolve()`) and shows that path, while the temporary folder is often reached through a link
 * (macOS's /var is /private/var; a TMPDIR that is one). A test that looks for a folder's path on a page or in an
 * answer looks for this one.
 */
export function realPath(path: string): string {
  if (existsSync(path)) return realpathSync(path);
  const parent = dirname(path);
  return parent === path ? path : join(realPath(parent), basename(path));
}

/** The temporary folder where it really is (see {@link realPath}): the tests make their folders in it. */
export const TMP_DIR = realPath(tmpdir());
export const DATA_DIR = realPath(resolve(process.env.ORDNUNG_E2E_DATA ?? join(TMP_DIR, "ordnung-e2e")));
/**
 * Where a run keeps its own files: next to its data folder when one is given, so two runs on two ports never
 * share a session or a results folder (a second run once overwrote the first one's session token);
 * else the defaults CI uploads from.
 */
const RUN_DIR = process.env.ORDNUNG_E2E_DATA ? `${DATA_DIR}-playwright` : null;
/** Cookie jar written by `global-setup.ts` (the session token from `<data>/server.json`). */
export const STORAGE_STATE = RUN_DIR ? join(RUN_DIR, "auth", "state.json") : join(here, ".auth", "state.json");
/** Playwright's output folder (traces, screenshots of failures). */
export const OUTPUT_DIR = RUN_DIR ? join(RUN_DIR, "test-results") : join(WEB_DIR, "test-results");

function ordnungBin(): string {
  if (process.env.ORDNUNG_BIN) return process.env.ORDNUNG_BIN;
  const venv = resolve(WEB_DIR, "..", ".venv", "bin", "ordnung");
  return existsSync(venv) ? venv : "ordnung";
}

export const ORDNUNG_BIN = ordnungBin();
/**
 * Whether the real app reads the words in pictures (`ORDNUNG_E2E_OCR=on`, ADR 0024): only then does it run with
 * `ORDNUNG_OCR` on, and only it; the demo server and the second computer never do (playwright.config.ts).
 */
export const E2E_OCR = process.env.ORDNUNG_E2E_OCR === "on";

// ------------------------------------------------------------------------------------------------
// The real app (project "real-app"): `ordnung serve` with a fake Claude
// ------------------------------------------------------------------------------------------------

const REPO_DIR = resolve(WEB_DIR, "..");
export const REAL_PORT = PORT + 1;
export const REAL_BASE_URL = `http://127.0.0.1:${REAL_PORT}`;
export const REAL_DATA_DIR = `${DATA_DIR}-real`;
export const REAL_STORAGE_STATE = join(dirname(STORAGE_STATE), "real-app.json");
/** The fake `claude`: it answers every call with the transcript in {@link FAKE_CLAUDE_SCENARIO}. */
export const FAKE_CLAUDE = join(REPO_DIR, "tests", "fake_claude.py");
export const FAKE_CLAUDE_SCENARIO = `${REAL_DATA_DIR}-claude.json`;
/**
 * The `claude` the real app runs (`ORDNUNG_CLAUDE_BIN`): a link to {@link FAKE_CLAUDE} the global setup makes, so a
 * test can take it away — Claude not installed — and put it back (e2e/real-app-waiting.spec.ts).
 */
export const REAL_CLAUDE = `${REAL_DATA_DIR}-claude`;
/**
 * The letter the real-app tests upload, and whose recorded demo reading the fake Claude returns: the bank's
 * fee increase that needs consent by 30 November 2026.
 */
export const REAL_LETTER = join(REPO_DIR, "src", "ordnung", "demo", "samples", "19_bank_preisaenderung.pdf");
export const REAL_READINGS = join(REPO_DIR, "src", "ordnung", "demo", "fixtures", "extract");
/** The session cookie: the server names it after its port. */
export const tokenCookie = (baseUrl: string): string => `ordnung_token_${new URL(baseUrl).port}`;

// ------------------------------------------------------------------------------------------------
// Hand-off sync (e2e/real-app-sync.spec.ts): a second real computer, two views of one synced folder, and a
// password store for each
// ------------------------------------------------------------------------------------------------

/**
 * The second computer: another `ordnung serve` on its own data folder, on the port after phone access's (the real
 * app is `PORT + 1`, its phone listener `PORT + 2`). The global setup leaves it **not set up** (no profile), as a
 * new computer is: its welcome page offers "I already use Ordnung on another computer".
 */
export const REAL_B_PORT = PORT + 3;
export const REAL_B_BASE_URL = `http://127.0.0.1:${REAL_B_PORT}`;
export const REAL_B_DATA_DIR = `${DATA_DIR}-real-b`;
export const REAL_B_STORAGE_STATE = join(dirname(STORAGE_STATE), "real-app-b.json");
/**
 * Each computer's copy of "the" synced folder. A real sync tool (Nextcloud, Syncthing, Dropbox) keeps the two in
 * step; here `e2e/sync-tool.ts` does, only when a test says so — late, out of order, with conflict copies.
 */
export const SYNC_A_DIR = `${DATA_DIR}-sync-a`;
export const SYNC_B_DIR = `${DATA_DIR}-sync-b`;
/** `tests/e2e_support/e2e_keyring.py`: a file-backed password store the real servers load (tests only). */
export const E2E_SUPPORT_DIR = join(REPO_DIR, "tests", "e2e_support");
export const KEYRING_BACKEND = "e2e_keyring.FileKeyring";
export const KEYRING_FILE_ENV = "ORDNUNG_E2E_KEYRING_FILE";
/** Each computer's own password store (a real computer has its own keyring): plain-text JSON, deleted every run. */
export const REAL_KEYRING = `${REAL_DATA_DIR}-keyring.json`;
export const REAL_B_KEYRING = `${REAL_B_DATA_DIR}-keyring.json`;

/**
 * The environment that gives a real server the e2e password store in `file`: `keyring` loads
 * {@link KEYRING_BACKEND} from {@link E2E_SUPPORT_DIR} (added to any `PYTHONPATH` already set). CI's Ubuntu has no
 * Secret Service, and Ordnung refuses keyring's `null`/`fail` backends, so without this sync would be unavailable.
 */
export function keyringEnv(file: string): Record<string, string> {
  const pythonPath = [E2E_SUPPORT_DIR, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
  return { PYTHON_KEYRING_BACKEND: KEYRING_BACKEND, PYTHONPATH: pythonPath, [KEYRING_FILE_ENV]: file };
}

// ------------------------------------------------------------------------------------------------
// Phone access of the real app (e2e/real-app-phone.spec.ts): its second listener, HTTPS on loopback
// ------------------------------------------------------------------------------------------------

/**
 * The address the real app's phone access listens on. A real computer offers only its home-network addresses
 * (10/8, 172.16/12, 192.168/16); `ORDNUNG_PHONE_TEST_ADDRESS` (set for the real app's server in
 * playwright.config.ts) makes this loopback address the only one, so the tests never open a listener to a
 * network — a server without it refuses this address (422), and the phone tests fail instead of listening on the
 * LAN.
 */
export const PHONE_ADDRESS = "127.0.0.1";
/** The environment variable that lets the real app's phone access listen on {@link PHONE_ADDRESS} (tests only). */
export const PHONE_TEST_ADDRESS_ENV = "ORDNUNG_PHONE_TEST_ADDRESS";
/** Phone access's port: the one after the real app's. */
export const PHONE_PORT = PORT + 2;
/** Where a paired phone opens Ordnung (its own certificate: phone contexts ignore HTTPS errors, as a phone clicks through once). */
export const PHONE_BASE_URL = `https://${PHONE_ADDRESS}:${PHONE_PORT}`;
/** A phone's sign-in cookie: `__Host-` (Secure, `Path=/`, no Domain), named after the phone listener's port. */
export const phoneCookie = (baseUrl: string = PHONE_BASE_URL): string => `__Host-ordnung_phone_${new URL(baseUrl).port}`;

// ------------------------------------------------------------------------------------------------
// Groups: the projects one run takes (`E2E_GROUP`), so CI can run them as jobs side by side
// ------------------------------------------------------------------------------------------------

/** The projects against the demo server (`ordnung demo --reset`), in the order one worker runs them. */
export const DEMO_PROJECTS = ["tour", "pages", "sweep", "layout", "girocode", "high-stakes", "add-date"] as const;
/** The projects against the real app and the second computer (`ordnung serve`, twice). */
export const REAL_APP_PROJECTS = ["real-app", "pictures"] as const;

/**
 * `E2E_GROUP=<name>` runs one group's projects, in the order of the whole run, on servers of its own: each group
 * starts a fresh demo (`--reset`) and fresh real apps (the global setup deletes their data), and only the servers
 * its projects use. A group never needs what another group's projects leave behind: the demo's projects that
 * need its recorded Ask answers (the tour, the pages, the sweep, the layout guards) run before those that change
 * the ledger (the GiroCode guards, the high-stakes letters, dates of the person's own) in whichever group holds
 * them, as in the whole run, and every project copes with a demo no earlier project touched. Unset: every project,
 * every server, as before. Together the groups hold every project exactly once (playwright.config.ts checks it).
 */
export const E2E_GROUPS: Readonly<Record<string, readonly string[]>> = {
  // the layout guards (37 files) take as long as the rest of the demo's projects together, so they run apart
  demo: ["tour", "pages", "sweep", "girocode", "high-stakes", "add-date"],
  layout: ["layout"],
  // the evaluation report's page needs no server: it goes with the real apps, the shortest of the three
  real: ["eval-report", "real-app", "pictures"],
};

function groupProjects(): readonly string[] | null {
  const name = process.env.E2E_GROUP;
  if (!name) return null;
  const projects = E2E_GROUPS[name];
  if (!projects) throw new Error(`E2E_GROUP=${name}: no such group (there are ${Object.keys(E2E_GROUPS).join(", ")})`);
  return projects;
}

/** The projects this run takes: a group's (`E2E_GROUP`), or `null` for all of them. */
export const GROUP_PROJECTS = groupProjects();
/** Whether this run takes the project `name`. */
export const runsProject = (name: string): boolean => GROUP_PROJECTS === null || GROUP_PROJECTS.includes(name);
/** Whether this run starts the demo server (and logs in to it). */
export const RUNS_DEMO = DEMO_PROJECTS.some(runsProject);
/** Whether this run starts the real app and the second computer (and sets them up). */
export const RUNS_REAL_APPS = REAL_APP_PROJECTS.some(runsProject);
