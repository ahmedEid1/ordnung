/**
 * Where the e2e servers run and where their sessions live: the demo, and the real app (`ordnung serve`
 * on its own data folder, port + 1, reading with the fake `claude` of `tests/fake_claude.py`). Shared by
 * `playwright.config.ts`, the global setup and the tests.
 *
 * - `ORDNUNG_E2E_PORT` (default 8799) and `ORDNUNG_E2E_DATA` (default `<tmp>/ordnung-e2e`); the real app
 *   uses the next port and `<data>-real`
 * - `ORDNUNG_BIN`: the `ordnung` executable (default: the repo's `.venv/bin/ordnung`, else `ordnung` on PATH)
 * - `ORDNUNG_E2E_REUSE=1`: reuse servers that are already running on the ports (local debugging)
 * - `PW_CHROMIUM_PATH`: a Chromium executable to use instead of Playwright's download
 */
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export const WEB_DIR = resolve(here, "..");
export const PORT = Number(process.env.ORDNUNG_E2E_PORT ?? 8799);
export const BASE_URL = `http://127.0.0.1:${PORT}`;
export const DATA_DIR = resolve(process.env.ORDNUNG_E2E_DATA ?? join(tmpdir(), "ordnung-e2e"));
/**
 * Where a run keeps its own files: next to its data folder when one is given, so two runs on two ports never
 * share a session or a results folder (review round 2: a second run overwrote the first one's session token);
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
