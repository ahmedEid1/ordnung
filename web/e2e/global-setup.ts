/**
 * Log the browser in once per server: each writes its session token to `<data>/server.json`; the app
 * normally trades `/?token=…` for an HttpOnly cookie named after its port. We write that cookie straight
 * into a storage state that every test context starts from.
 *
 * The real app also starts from scratch every run: Delete everything, then a finished setup without
 * Claude's own notes and reviews (the fake Claude can't write them). The fake Claude's one answer is the
 * recorded demo reading of `REAL_LETTER`, as the `result` event of Claude Code's stream-json.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  BASE_URL,
  DATA_DIR,
  FAKE_CLAUDE_SCENARIO,
  REAL_BASE_URL,
  REAL_DATA_DIR,
  REAL_LETTER,
  REAL_READINGS,
  REAL_STORAGE_STATE,
  STORAGE_STATE,
  tokenCookie,
} from "./env";

interface Health {
  authenticated?: boolean;
  demo?: boolean;
}

function sessionToken(dataDir: string): string {
  const file = join(dataDir, "server.json");
  let token: string;
  try {
    token = (JSON.parse(readFileSync(file, "utf8")) as { token?: string }).token ?? "";
  } catch (err) {
    throw new Error(`No server session in ${file} — are the webServers from playwright.config.ts running?`, { cause: err });
  }
  if (!token) throw new Error(`${file} has no session token (was the server started with --no-token?)`);
  return token;
}

async function health(baseUrl: string, token: string, dataDir: string): Promise<Health> {
  const res = await fetch(`${baseUrl}/api/health`, { headers: { Authorization: `Bearer ${token}` } });
  // without a valid token the health check answers `{version, authenticated: false}` only
  const body = (await res.json()) as Health;
  if (body.authenticated === false) {
    throw new Error(
      `The server on ${baseUrl} does not accept the token from ${join(dataDir, "server.json")}. ` +
        "Another Ordnung is probably running on that port — stop it or set ORDNUNG_E2E_PORT.",
    );
  }
  return body;
}

function saveSession(file: string, baseUrl: string, token: string): void {
  const { hostname } = new URL(baseUrl);
  mkdirSync(dirname(file), { recursive: true });
  const cookie = { name: tokenCookie(baseUrl), value: token, domain: hostname, path: "/", expires: -1, httpOnly: true, secure: false, sameSite: "Strict" };
  writeFileSync(file, JSON.stringify({ cookies: [cookie], origins: [] }, null, 2));
}

async function demoSession(): Promise<void> {
  const token = sessionToken(DATA_DIR);
  if (!(await health(BASE_URL, token, DATA_DIR)).demo) throw new Error(`The server on ${BASE_URL} is not running the demo.`);
  saveSession(STORAGE_STATE, BASE_URL, token);
}

/** The demo's recorded reading of `REAL_LETTER` (its recordings are keyed by the letter's SHA-256). */
function recordedReading(): unknown {
  const sha = createHash("sha256").update(readFileSync(REAL_LETTER)).digest("hex");
  for (const name of readdirSync(REAL_READINGS)) {
    const fixture = JSON.parse(readFileSync(join(REAL_READINGS, name), "utf8")) as { request: { cache_key: string }; response: { data: unknown } };
    if ((JSON.parse(fixture.request.cache_key) as { doc?: string }).doc === sha) return fixture.response.data;
  }
  throw new Error(`No recorded demo reading of ${REAL_LETTER} in ${REAL_READINGS}`);
}

async function realAppSession(): Promise<void> {
  const token = sessionToken(REAL_DATA_DIR);
  if ((await health(REAL_BASE_URL, token, REAL_DATA_DIR)).demo) throw new Error(`The server on ${REAL_BASE_URL} runs the demo, not the real app.`);
  const result = { type: "result", subtype: "success", is_error: false, result: "", num_turns: 1, structured_output: recordedReading() };
  const log = `${REAL_DATA_DIR}-claude-calls.jsonl`; // every call the fake Claude got, this run
  writeFileSync(log, "");
  writeFileSync(FAKE_CLAUDE_SCENARIO, JSON.stringify({ log, calls: [{ lines: [JSON.stringify(result)] }] }));

  const send = async (method: string, path: string, body: unknown): Promise<void> => {
    const res = await fetch(`${REAL_BASE_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "X-Ordnung-Client": "e2e", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${method} ${path} on the real app → ${res.status} ${await res.text()}`);
  };
  await send("DELETE", "/api/data", { confirm: "DELETE" });
  await send("POST", "/api/onboarding", { profile: { name: "Sam Rivera", region: "NW" }, skip_ai: true });
  saveSession(REAL_STORAGE_STATE, REAL_BASE_URL, token);
}

export default async function globalSetup(): Promise<void> {
  await demoSession();
  await realAppSession();
}
