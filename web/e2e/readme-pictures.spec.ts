/**
 * README's two pictures that `ordnung demo` can't show: pairing a phone (the computer's QR code, the paired phone's two
 * check words, the computer showing the same two) and Settings → Your computers (this computer in use, the other
 * standing by with its latest changes). The demo never opens itself to a network and never syncs, so both come from
 * the real app as the browser tests run it: `ordnung serve` on throwaway data folders, phone access on loopback only
 * (`ORDNUNG_PHONE_TEST_ADDRESS`), each computer with the e2e password store, and a stand-in Claude that is never asked.
 *
 * `make capture` runs it last (scripts/capture.sh sets ORDNUNG_CAPTURE_OUT, the folder the pictures go to); without
 * that variable it is skipped, so CI lists its tests and writes nothing. To make just these two pictures:
 *
 *     cd web && ORDNUNG_CAPTURE_OUT=$PWD/../docs/assets npx playwright test --project pictures
 *
 * The setup goes through the API: the stories (real-app-phone.spec.ts, real-app-sync.spec.ts) test the same flows
 * through the screens. The pairing code, the two words and "just now" change on every capture.
 */
import { existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import type { Browser, Page } from "@playwright/test";
import type { components } from "@/api/schema";
import type { PhoneStatus } from "@/api/types";
import { DATA_DIR, PHONE_ADDRESS, PHONE_PORT, REAL_B_BASE_URL, REAL_B_STORAGE_STATE, REAL_DATA_DIR } from "./env";
import { apiGet, apiSend, expect, open, phoneContext, settle, test } from "./helpers";
import { SyncTool } from "./sync-tool";

type SyncStatus = components["schemas"]["SyncStatus"];

/** Where the pictures go: README's `docs/assets` when `make capture` runs this. */
const OUT = process.env.ORDNUNG_CAPTURE_OUT ? resolve(process.env.ORDNUNG_CAPTURE_OUT) : "";
/** README's tour pictures: 1440×900 at device scale 1, like the rest. */
const CANVAS = { width: 1440, height: 900 };
const PHONE_NAME = "Sam's Pixel";
const COMPUTERS = { a: "sam-laptop", b: "sam-desktop" } as const;
/** The throwaway sync folder's passphrase: five unrelated words, as the setup asks. */
const PASSPHRASE = "orbit lantern cobalt thistle quarry";
/**
 * Each computer's copy of the sync folder, built from the run's data folder (as the global setup builds every path it
 * removes), so the picture shows a throwaway path, never one of this computer's.
 */
const SYNC_ROOT = `${DATA_DIR}-pictures`;
const FOLDERS = {
  a: join(SYNC_ROOT, COMPUTERS.a, "Nextcloud", "Ordnung"),
  b: join(SYNC_ROOT, COMPUTERS.b, "Nextcloud", "Ordnung"),
};
/** Every call the stand-in Claude got this run (e2e/global-setup.ts writes it empty). */
const CLAUDE_CALLS = `${REAL_DATA_DIR}-claude-calls.jsonl`;
const CLIENT = { "X-Ordnung-Client": "web" };

test.describe.configure({ mode: "serial" });
test.skip(!OUT, "makes README's pictures of phone access and hand-off sync: make capture");

const claudeCalls = () => (existsSync(CLAUDE_CALLS) ? readFileSync(CLAUDE_CALLS, "utf8").split("\n").filter(Boolean).length : 0);
let callsBefore = 0;

test.beforeAll(() => {
  callsBefore = claudeCalls();
  rmSync(SYNC_ROOT, { recursive: true, force: true });
  for (const folder of Object.values(FOLDERS)) mkdirSync(folder, { recursive: true, mode: 0o700 });
});

test.afterAll(() => {
  // each test undoes what it turned on (phone access, the paired phone, sync, the second computer's data) itself
  rmSync(SYNC_ROOT, { recursive: true, force: true });
  expect(claudeCalls() - callsBefore, "the pictures asked no model").toBe(0);
});

/** The page in light mode and still: what a picture may show. */
async function ready(page: Page): Promise<void> {
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await settle(page);
}

const dataUri = (path: string) => `data:image/png;base64,${readFileSync(path).toString("base64")}`;

function saved(name: string, path: string): void {
  console.log(`picture → ${path} (${statSync(path).size} bytes)`);
  expect(statSync(path).size, `${name} was written`).toBeGreaterThan(0);
}

/**
 * Lay out a picture's parts (`data-part` elements in `html`) on the app's own background, 1440×900, and save it. A part
 * that doesn't fit fails the run, so a longer dialog is never cut off unseen.
 */
async function compose(browser: Browser, name: string, background: string, html: string): Promise<void> {
  const context = await browser.newContext({ viewport: CANVAS, deviceScaleFactor: 1, colorScheme: "light" });
  try {
    const page = await context.newPage();
    await page.setContent(`<!doctype html><body style="margin:0;background:${background}">${html}</body>`);
    await page.waitForFunction(() => [...document.images].every((img) => img.complete && img.naturalWidth > 0));
    const outside = await page.evaluate(
      ({ width, height }) =>
        [...document.querySelectorAll("[data-part]")]
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.top < 0 || r.left < 0 || r.bottom > height || r.right > width;
          })
          .map((el) => el.getAttribute("data-part")),
      CANVAS,
    );
    expect(outside, "every part fits the picture").toEqual([]);
    const path = join(OUT, name);
    await page.screenshot({ path });
    saved(name, path);
  } finally {
    await context.close();
  }
}

test("pair-phone.png: the QR code, the phone's two words, the computer's same two", async ({ page, browser }, testInfo) => {
  // loopback only: a server without ORDNUNG_PHONE_TEST_ADDRESS refuses this address (422), and the run fails
  const on = await apiSend<PhoneStatus>(page, "PUT", "/api/phone", { enabled: true, address: PHONE_ADDRESS, port: PHONE_PORT });
  expect(on.problem, `phone access couldn't start: ${on.problem?.detail}`).toBeNull();
  const phone = await phoneContext(browser, { deviceScaleFactor: 1, colorScheme: "light" });
  try {
    await open(page, "/settings?section=phone", "Settings");
    await page.getByRole("region", { name: "Pair a phone" }).getByRole("button", { name: "Pair a phone" }).click();
    const dialog = page.getByRole("dialog", { name: "Pair a phone" });
    const holder = dialog.locator("[data-pairing-url]");
    await expect(holder).toBeVisible();
    const url = await holder.getAttribute("data-pairing-url");
    expect(url, "the dialog's pairing address").toBeTruthy();

    const mobile = await phone.newPage();
    await mobile.goto(url!);
    await expect(mobile.getByRole("heading", { level: 1, name: "Pair this phone with Ordnung" })).toBeVisible();

    // 1. the computer: the code as a QR code and as letters, and the phone that reached it — down to 16 px under the
    // QR code's frame, so the per-phone steps (with the listener's address and port) stay out of the picture
    await expect(dialog).toContainText("Your phone reached this computer");
    await page.mouse.move(8, 8);
    await ready(page);
    const card = await dialog.boundingBox();
    const qrFrame = await dialog.getByRole("img", { name: /^Pairing code as a QR code/ }).locator("..").boundingBox();
    expect(card && qrFrame, "the dialog and its QR code are on screen").toBeTruthy();
    const codePart = testInfo.outputPath("code.png");
    await page.screenshot({
      path: codePart,
      clip: { x: card!.x, y: card!.y, width: card!.width, height: Math.round(qrFrame!.y + qrFrame!.height + 16 - card!.y) },
    });
    const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);

    // 2. the phone, paired: its two words
    await mobile.getByLabel("This phone's name").fill(PHONE_NAME);
    await mobile.getByRole("button", { name: "Pair this phone" }).click();
    const words = mobile.locator("[data-check-words]");
    await expect(words).toBeVisible();
    const phoneWords = (await words.innerText()).trim();
    expect(phoneWords, "the phone shows two words").toMatch(/^\S+ \S+$/);
    await ready(mobile);
    const phonePart = testInfo.outputPath("phone.png");
    await mobile.screenshot({ path: phonePart });

    // 3. the computer: the same two words — the two screens agree
    await expect(dialog).toContainText(`Paired: ${PHONE_NAME}`, { timeout: 6_000 });
    await expect(dialog).toContainText(`Your phone should show “${phoneWords}”`);
    await ready(page);
    const pairedPart = testInfo.outputPath("paired.png");
    await dialog.screenshot({ path: pairedPart });

    const shadow = "display:block;border-radius:16px;box-shadow:0 1px 2px rgba(16,24,32,.06),0 12px 32px rgba(16,24,32,.14)";
    await compose(
      browser,
      "pair-phone.png",
      background,
      `<div style="width:${CANVAS.width}px;height:${CANVAS.height}px;display:flex;gap:56px;align-items:center;justify-content:center">` +
        `<div style="display:flex;flex-direction:column;gap:28px">` +
        `<img data-part="code" alt="" src="${dataUri(codePart)}" style="${shadow}">` +
        `<img data-part="paired" alt="" src="${dataUri(pairedPart)}" style="${shadow}">` +
        `</div>` +
        `<div data-part="phone" style="padding:10px;border-radius:38px;background:#16181d;box-shadow:0 24px 60px rgba(16,24,32,.3)">` +
        `<img alt="" src="${dataUri(phonePart)}" style="display:block;border-radius:28px"></div>` +
        `</div>`,
    );
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
  } finally {
    await phone.close();
    const status = await apiGet<PhoneStatus>(page, "/api/phone");
    for (const device of status.devices) await page.request.delete(`/api/phone/devices/${device.id}`, { headers: CLIENT });
    await page.request.put("/api/phone", { data: { enabled: false }, headers: CLIENT });
  }
});

/** Ask a computer for its sync status until `ok` says yes (sync looks at the folder every 15 s). */
async function until(page: Page, what: string, ok: (s: SyncStatus) => boolean, timeout = 90_000): Promise<SyncStatus> {
  let last: SyncStatus | undefined;
  await expect
    .poll(async () => ok((last = await apiGet<SyncStatus>(page, "/api/sync"))), { message: what, timeout, intervals: [500, 1_000, 2_000] })
    .toBe(true);
  return last!;
}

test("your-computers.png: this computer in use, the other standing by with its latest changes", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const tool = new SyncTool(FOLDERS);
  // the desktop: hand-off sync's second computer, new until it joins here
  const desktop = await browser.newContext({
    baseURL: REAL_B_BASE_URL,
    storageState: REAL_B_STORAGE_STATE,
    viewport: CANVAS,
    deviceScaleFactor: 1,
    colorScheme: "light",
    locale: "en-GB",
    timezoneId: "Europe/Berlin",
    reducedMotion: "reduce",
  });
  const b = await desktop.newPage();
  try {
    await apiSend(page, "PUT", "/api/sync", { folder: FOLDERS.a, name: COMPUTERS.a, passphrase: PASSPHRASE });
    await until(page, "the laptop saved to the folder", (s) => s.mode === "in_use" && s.activity === "idle" && !s.pending_changes && Boolean(s.last_saved_at));
    await tool.deliver("a");
    await apiSend(b, "PUT", "/api/sync", { folder: FOLDERS.b, name: COMPUTERS.b, passphrase: PASSPHRASE });
    await until(b, "the desktop joined, is in use and saved", (s) => s.mode === "in_use" && s.activity === "idle" && !s.pending_changes && Boolean(s.last_saved_at));
    await tool.deliver("b");
    await until(page, "the laptop stands by", (s) => s.mode === "standing_by" && s.in_use_on === COMPUTERS.b);
    await tool.deliver("a");
    const shown = await until(b, "the desktop knows the laptop stands by with its latest changes", (s) =>
      s.computers.some((c) => !c.this && c.name === COMPUTERS.a && c.has_latest === true && !c.in_use),
    );
    expect(shown.problem).toBeNull();

    await open(b, "/settings?section=computers", "Settings");
    await b.mouse.move(120, 600); // the sidebar's empty space: no hover on the picture
    await ready(b);
    const text = await b.getByRole("main").innerText();
    expect(text, "the folder shown is the throwaway one").toContain(FOLDERS.b);
    expect(text, "no path of this computer's").not.toContain(homedir());
    const path = join(OUT, "your-computers.png");
    await b.screenshot({ path });
    saved("your-computers.png", path);
  } finally {
    // both leave sync, and the second computer is new again, as real-app-sync.spec.ts expects it
    for (const p of [page, b]) await p.request.delete("/api/sync", { data: { forget_passphrase: true, unreceived_ok: true }, headers: CLIENT });
    await b.request.delete("/api/data", { data: { confirm: "DELETE", unreceived_ok: true }, headers: CLIENT });
    await desktop.close();
  }
});
