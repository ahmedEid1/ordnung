/**
 * Compressed answers on the real app (`ordnung serve`): JSON answers and the web app's files go out gzipped to a
 * client that takes gzip, while the live events stream starts at once and as it is, a range request on a letter's
 * PDF keeps its 206 and downloads stay byte for byte the same. Each request here is sent with Node's own HTTP
 * client, which decodes nothing, so the test sees the bytes exactly as they came over the wire. The letter it adds
 * is deleted for good afterwards (the other real-app specs add the same file).
 */
import { readFileSync } from "node:fs";
import { request as httpRequest, type IncomingHttpHeaders } from "node:http";
import { gunzipSync } from "node:zlib";
import type { Page } from "@playwright/test";
import { REAL_BASE_URL, REAL_LETTER, tokenCookie } from "./env";
import { apiGet, apiSend, expect, open, test, type Letter } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";
const GZIP = { "Accept-Encoding": "gzip" };
/** The live stream's first keep-alive ping comes after 15 s: its headers must come long before. */
const STARTS_WITHIN_MS = 5_000;

test.describe.configure({ mode: "serial" });

interface Wire {
  status: number;
  headers: IncomingHttpHeaders;
  body: Buffer;
}

/** The page's session cookie, for requests sent outside the browser. */
async function session(page: Page): Promise<string> {
  const cookie = (await page.context().cookies(REAL_BASE_URL)).find((c) => c.name === tokenCookie(REAL_BASE_URL));
  expect(cookie, "the real app's session cookie").toBeTruthy();
  return `${cookie!.name}=${cookie!.value}`;
}

/** One GET with the page's session, answered exactly as it came over the wire (nothing decoded). */
async function wire(page: Page, path: string, headers: Record<string, string> = {}): Promise<Wire> {
  const cookie = await session(page);
  return new Promise((resolve, reject) => {
    const sent = httpRequest(`${REAL_BASE_URL}${path}`, { headers: { cookie, ...headers } }, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks) }));
      res.on("error", reject);
    });
    sent.on("error", reject);
    sent.end();
  });
}

/** How long a GET takes until its headers arrive (the request is then dropped), and the headers. */
async function headersOf(page: Page, path: string, headers: Record<string, string>): Promise<{ ms: number; status: number; headers: IncomingHttpHeaders }> {
  const cookie = await session(page);
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const sent = httpRequest(`${REAL_BASE_URL}${path}`, { headers: { cookie, ...headers } }, (res) => {
      resolve({ ms: Date.now() - started, status: res.statusCode ?? 0, headers: res.headers });
      res.destroy();
      sent.destroy();
    });
    sent.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code !== "ECONNRESET") reject(error); // dropping the stream on purpose ends the request
    });
    sent.setTimeout(20_000, () => sent.destroy(new Error(`${path} sent no headers within 20 s`)));
    sent.end();
  });
}

const vary = (headers: IncomingHttpHeaders): string[] =>
  String(headers.vary ?? "")
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);

test("API answers and the app's files arrive gzipped to a browser that takes gzip", async ({ page }) => {
  // the browser itself: every script of the page worth compressing (1 KiB and more) came gzipped, and the app works
  const scripts: Promise<{ path: string; encoding: string | null; length: number }>[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (!/^\/assets\/[^/]+\.js$/.test(path)) return;
    scripts.push(
      Promise.all([response.headerValue("content-encoding"), response.headerValue("content-length")]).then(([encoding, length]) => ({ path, encoding, length: Number(length) })),
    );
  });
  await open(page, "/inbox", "Inbox");
  const loaded = await Promise.all(scripts);
  expect(loaded.filter((s) => s.encoding === "gzip").length, "the page loaded gzipped scripts").toBeGreaterThan(0);
  for (const s of loaded) expect(s.encoding === "gzip" || s.length < 1024, `${s.path} (${s.length} B) came gzipped`).toBe(true);

  const zipped = await wire(page, "/api/rules", GZIP);
  expect(zipped.status).toBe(200);
  expect(zipped.headers["content-encoding"]).toBe("gzip");
  expect(vary(zipped.headers)).toContain("accept-encoding");
  expect(Number(zipped.headers["content-length"])).toBe(zipped.body.length);
  const plain = await wire(page, "/api/rules");
  expect(plain.headers["content-encoding"], "a client that doesn't ask gets it as it is").toBeUndefined();
  expect(gunzipSync(zipped.body).equals(plain.body)).toBe(true);
  expect(zipped.body.length).toBeLessThan(plain.body.length / 3);
  expect(JSON.parse(plain.body.toString("utf8"))).toEqual(await apiGet<unknown>(page, "/api/rules"));

  const inbox = await wire(page, "/inbox", GZIP);
  expect(inbox.headers["content-encoding"], "the page itself is never compressed").toBeUndefined();
  expect(String(inbox.headers["content-security-policy"])).toContain("frame-ancestors 'none'");
  const script = /src="(\/assets\/[^"]+\.js)"/.exec(inbox.body.toString("utf8"))?.[1];
  expect(script, "index.html names its entry script").toBeTruthy();
  const asset = await wire(page, script!, GZIP);
  expect(asset.headers["content-encoding"]).toBe("gzip");
  expect(asset.headers["cache-control"]).toBe("public, max-age=31536000, immutable");
  expect(asset.headers["content-type"]).toBe("text/javascript; charset=utf-8");
  expect(vary(asset.headers)).toContain("accept-encoding");
  expect(gunzipSync(asset.body).equals((await wire(page, script!)).body)).toBe(true);
});

test("the live events stream starts at once and as it is", async ({ page }) => {
  const stream = await headersOf(page, "/api/events", { ...GZIP, Accept: "text/event-stream" });
  expect(stream.status).toBe(200);
  expect(String(stream.headers["content-type"])).toMatch(/^text\/event-stream/);
  expect(stream.headers["content-encoding"]).toBeUndefined();
  expect(stream.ms, "the stream's headers came at once, not with its first ping").toBeLessThan(STARTS_WITHIN_MS);
});

test("a letter's PDF answers a range request with 206, and downloads stay byte for byte the same", async ({ page }) => {
  const original = readFileSync(REAL_LETTER);
  try {
    const upload = await page.request.post("/api/documents", {
      headers: { "X-Ordnung-Client": "web" },
      multipart: { files: { name: FILE, mimeType: "application/pdf", buffer: original }, combine: "false" },
    });
    expect(upload.status(), await upload.text()).toBe(201);
    let letter: (Letter & { status: string }) | undefined;
    await expect
      .poll(
        async () => {
          letter = (await apiGet<(Letter & { status: string })[]>(page, "/api/documents")).find((d) => d.filename === FILE);
          return letter?.status;
        },
        { message: `${FILE} is read`, timeout: 30_000 },
      )
      .toBe("processed");

    const part = await wire(page, `/api/documents/${letter!.id}/file`, { ...GZIP, Range: "bytes=0-99" });
    expect(part.status).toBe(206);
    expect(part.headers["content-range"]).toBe(`bytes 0-99/${original.length}`);
    expect(part.headers["content-encoding"]).toBeUndefined();
    expect(part.body.equals(original.subarray(0, 100))).toBe(true);

    for (const headers of [GZIP, {}]) {
      const whole = await wire(page, `/api/documents/${letter!.id}/file`, headers);
      expect(whole.status).toBe(200);
      expect(whole.headers["content-encoding"]).toBeUndefined();
      expect(whole.body.equals(original), "the letter's original, byte for byte").toBe(true);
    }
    const calendar = await wire(page, "/api/calendar.ics", GZIP);
    expect(calendar.status).toBe(200);
    expect(calendar.headers["content-encoding"]).toBeUndefined();
    expect(calendar.body.toString("utf8")).toMatch(/^BEGIN:VCALENDAR/);
    const zip = await wire(page, "/api/documents.zip", GZIP);
    expect(zip.status).toBe(200);
    expect(zip.headers["content-encoding"]).toBeUndefined();
    expect(zip.body.subarray(0, 4).toString("latin1"), "a ZIP").toBe("PK\x03\x04");
  } finally {
    for (const added of (await apiGet<Letter[]>(page, "/api/documents")).filter((d) => d.filename === FILE)) {
      await apiSend(page, "DELETE", `/api/documents/${added.id}?purge=true`);
    }
  }
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(FILE);
});
