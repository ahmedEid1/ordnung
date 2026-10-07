/**
 * Log the browser in once per server: each writes its session token to `<data>/server.json`; the app
 * normally trades `/?token=…` for an HttpOnly cookie named after its port. We write that cookie straight
 * into a storage state that every test context starts from.
 *
 * The real app also starts from scratch every run: Delete everything, then a finished setup without
 * Claude's own notes and reviews (the fake Claude can't write them). The fake Claude's one answer is the
 * recorded demo reading of `REAL_LETTER`, as the `result` event of Claude Code's stream-json; the real app
 * runs it through the link `REAL_CLAUDE`, made here.
 *
 * Hand-off sync's second computer starts from scratch too, but is left **new** (Delete everything, no setup): it
 * joins the first one's Ordnung (e2e/real-app-sync.spec.ts). Before that, both computers leave sync — a run cut
 * short may have left them syncing, or one standing by, which would refuse the next run's writes — and then the
 * two copies of the synced folder and both password stores are removed and the folders made again, empty. Every
 * path removed is built from `DATA_DIR` (e2e/env.ts), never a pattern.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  BASE_URL,
  DATA_DIR,
  FAKE_CLAUDE,
  FAKE_CLAUDE_SCENARIO,
  REAL_B_BASE_URL,
  REAL_B_DATA_DIR,
  REAL_B_KEYRING,
  REAL_B_STORAGE_STATE,
  REAL_BASE_URL,
  REAL_CLAUDE,
  REAL_DATA_DIR,
  REAL_KEYRING,
  REAL_LETTER,
  REAL_READINGS,
  REAL_STORAGE_STATE,
  STORAGE_STATE,
  SYNC_A_DIR,
  SYNC_B_DIR,
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

/** A real app (`ordnung serve`, not the demo) and its session token. */
interface RealServer {
  name: string;
  baseUrl: string;
  token: string;
}

async function realServer(name: string, baseUrl: string, dataDir: string): Promise<RealServer> {
  const token = sessionToken(dataDir);
  if ((await health(baseUrl, token, dataDir)).demo) throw new Error(`The server on ${baseUrl} runs the demo, not the real app.`);
  return { name, baseUrl, token };
}

/** A change on a real app with its session (the CLI's way in: a bearer token and `X-Ordnung-Client`). */
function request(server: RealServer, method: string, path: string, body: unknown): Promise<Response> {
  return fetch(`${server.baseUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${server.token}`, "X-Ordnung-Client": "e2e", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function send(server: RealServer, method: string, path: string, body: unknown): Promise<void> {
  const res = await request(server, method, path, body);
  if (!res.ok) throw new Error(`${method} ${path} on ${server.name} → ${res.status} ${await res.text()}`);
}

/**
 * The computer leaves hand-off sync if a run before left it syncing (one that isn't syncing just answers with its
 * status): its passphrase leaves its password store, `<data>/sync/` goes, and a computer standing by takes writes
 * again. Asked while its copy of the folder is still there, so it can say there that it left. A refusal is only
 * reported: Delete everything (next) leaves sync too, and says why when it can't.
 */
async function leaveSync(server: RealServer): Promise<void> {
  const res = await request(server, "DELETE", "/api/sync", { forget_passphrase: true, unreceived_ok: true });
  if (!res.ok) console.warn(`DELETE /api/sync on ${server.name} → ${res.status} ${await res.text()}`);
}

/** Each computer's copy of the synced folder, empty, and neither computer's password store yet. */
function freshSyncFolders(): void {
  for (const path of [SYNC_A_DIR, SYNC_B_DIR, REAL_KEYRING, REAL_B_KEYRING]) rmSync(path, { recursive: true, force: true });
  for (const folder of [SYNC_A_DIR, SYNC_B_DIR]) mkdirSync(folder, { recursive: true, mode: 0o700 });
}

async function realAppSession(server: RealServer): Promise<void> {
  // Claude installed (a test that took it away puts it back, but may have failed first): before the first check
  rmSync(REAL_CLAUDE, { force: true });
  symlinkSync(FAKE_CLAUDE, REAL_CLAUDE);
  const result = { type: "result", subtype: "success", is_error: false, result: "", num_turns: 1, structured_output: recordedReading() };
  const log = `${REAL_DATA_DIR}-claude-calls.jsonl`; // every call the fake Claude got, this run
  writeFileSync(log, "");
  writeFileSync(FAKE_CLAUDE_SCENARIO, JSON.stringify({ log, calls: [{ lines: [JSON.stringify(result)] }] }));

  await send(server, "DELETE", "/api/data", { confirm: "DELETE", unreceived_ok: true });
  await send(server, "POST", "/api/onboarding", { profile: { name: "Sam Rivera", region: "NW" }, skip_ai: true });
  saveSession(REAL_STORAGE_STATE, server.baseUrl, server.token);
}

/** Hand-off sync's second computer: everything deleted and nothing set up, like a computer Ordnung was just put on. */
async function newComputerSession(server: RealServer): Promise<void> {
  await send(server, "DELETE", "/api/data", { confirm: "DELETE", unreceived_ok: true });
  saveSession(REAL_B_STORAGE_STATE, server.baseUrl, server.token);
}

export default async function globalSetup(): Promise<void> {
  await demoSession();
  const real = await realServer("the real app", REAL_BASE_URL, REAL_DATA_DIR);
  const second = await realServer("the second computer", REAL_B_BASE_URL, REAL_B_DATA_DIR);
  await leaveSync(real);
  await leaveSync(second);
  freshSyncFolders();
  await realAppSession(real);
  await newComputerSession(second);
}
