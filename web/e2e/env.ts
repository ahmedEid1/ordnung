/**
 * Where the e2e demo server runs and where its session lives. Shared by `playwright.config.ts`,
 * the global setup and the tests.
 *
 * - `ORDNUNG_E2E_PORT` (default 8799) and `ORDNUNG_E2E_DATA` (default `<tmp>/ordnung-e2e`)
 * - `ORDNUNG_BIN`: the `ordnung` executable (default: the repo's `.venv/bin/ordnung`, else `ordnung` on PATH)
 * - `ORDNUNG_E2E_REUSE=1`: reuse a demo server that is already running on the port (local debugging)
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
