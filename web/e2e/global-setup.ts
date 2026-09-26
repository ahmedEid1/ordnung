/**
 * Log the browser in once: the demo server writes its session token to `<data>/server.json`; the
 * app normally trades `/?token=…` for an HttpOnly cookie. We write that cookie straight into a
 * storage state that every test context starts from.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { BASE_URL, DATA_DIR, STORAGE_STATE } from "./env";

export default async function globalSetup(): Promise<void> {
  const file = join(DATA_DIR, "server.json");
  let token: string;
  try {
    token = (JSON.parse(readFileSync(file, "utf8")) as { token?: string }).token ?? "";
  } catch (err) {
    throw new Error(`No demo server session in ${file} — is the webServer from playwright.config.ts running?`, { cause: err });
  }
  if (!token) throw new Error(`${file} has no session token (was the demo started with --no-token?)`);

  const res = await fetch(`${BASE_URL}/api/health`, { headers: { Authorization: `Bearer ${token}` } });
  // without a valid token the health check answers `{version, authenticated: false}` only
  const health = (await res.json()) as { authenticated?: boolean; demo?: boolean };
  if (health.authenticated === false) {
    throw new Error(
      `The server on ${BASE_URL} does not accept the token from ${file}. ` +
        "Another Ordnung is probably running on that port — stop it or set ORDNUNG_E2E_PORT.",
    );
  }
  if (!health.demo) throw new Error(`The server on ${BASE_URL} is not running the demo.`);

  const { hostname } = new URL(BASE_URL);
  mkdirSync(dirname(STORAGE_STATE), { recursive: true });
  writeFileSync(
    STORAGE_STATE,
    JSON.stringify(
      {
        cookies: [{ name: "ordnung_token", value: token, domain: hostname, path: "/", expires: -1, httpOnly: true, secure: false, sameSite: "Strict" }],
        origins: [],
      },
      null,
      2,
    ),
  );
}
