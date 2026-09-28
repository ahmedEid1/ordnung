/**
 * The watched folder on the real demo (SPEC § 8.1), where jsdom can't look: a real folder next to
 * the demo's data holds a scan with a long scanner file name and an e-mail with a PDF attached; the
 * running watcher picks them up and holds them (the demo can't read new letters). The Inbox's "From
 * your folder — waiting for you", a waiting letter and Settings → Watched folder fit from 320 to
 * 1280 px without sideways scrolling, long names wrap inside their cards, the answers are ≥ 24 px
 * targets that don't spill out of their buttons, and axe finds nothing serious in either theme.
 * Today says the letters wait (its card, the Inbox's count) instead of "all clear", and on a wide
 * screen a waiting letter's page has no empty band under its card. Afterwards the folder is unset
 * and the waiting letters deleted, so the other specs see the demo as it was.
 * Runs in the "layout" project (its name ends in `layout.spec.ts`).
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Locator, Page } from "@playwright/test";
import { BASE_URL, STORAGE_STATE, WEB_DIR } from "./env";
import { apiGet, expect, expectAccessible, open, setTour, settle, test } from "./helpers";

const CLIENT = { "X-Ordnung-Client": "web" };
const SAMPLES = resolve(WEB_DIR, "..", "src", "ordnung", "demo", "samples");
const SCAN = "Scan_2026-09-28_0914_Hausverwaltung_Kramer_Ablesung_der_Wasserzaehler.pdf";
let folder: string | null = null;

/** A sample made new to Ordnung: a comment after `%%EOF` changes its hash, not what it shows. */
const fresh = (name: string, tag: string) => Buffer.concat([readFileSync(join(SAMPLES, name)), Buffer.from(`\n% e2e copy: ${tag}\n`)]);

function emailWithPdf(pdf: Buffer): string {
  const b = "ordnung-e2e-boundary";
  return [
    "From: FunkNetz Kundenservice <rechnung@funknetz.example>",
    "Subject: Ihre Rechnung September 2026",
    "MIME-Version: 1.0",
    `Content-Type: multipart/mixed; boundary="${b}"`,
    "",
    `--${b}`,
    "Content-Type: text/plain; charset=utf-8",
    "",
    "Ihre Rechnung finden Sie im Anhang. SPECIMEN",
    `--${b}`,
    'Content-Type: application/pdf; name="Rechnung_2026-09.pdf"',
    'Content-Disposition: attachment; filename="Rechnung_2026-09.pdf"',
    "Content-Transfer-Encoding: base64",
    "",
    pdf.toString("base64").replace(/.{76}/g, "$&\r\n"),
    `--${b}--`,
    "",
  ].join("\r\n");
}

/** Once per run: the folder with its files, set in Settings, and the watcher's three waiting letters. */
async function watchedFolder(page: Page): Promise<void> {
  if (!folder) {
    folder = mkdtempSync(join(tmpdir(), "ordnung-e2e-scans-"));
    writeFileSync(join(folder, SCAN), fresh("17_auslaenderbehoerde_termin.pdf", "scan"));
    writeFileSync(join(folder, "Ihre Rechnung September 2026.eml"), emailWithPdf(fresh("08_rechnung_techmarkt.pdf", "mail")));
    const res = await page.request.put("/api/settings", { data: { inbox_dir: folder }, headers: CLIENT });
    expect(res.ok(), `PUT /api/settings → ${res.status()}`).toBe(true);
  }
  await expect.poll(async () => (await apiGet<{ waiting: number }>(page, "/api/folder")).waiting, { timeout: 45_000 }).toBe(3);
}

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
  await watchedFolder(page);
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: STORAGE_STATE, baseURL: BASE_URL });
  await ctx.request.put("/api/settings", { data: { inbox_dir: null }, headers: CLIENT });
  const waiting = (await (await ctx.request.get("/api/documents?status=held")).json()) as { id: string }[];
  for (const d of waiting) await ctx.request.delete(`/api/documents/${d.id}?purge=true`, { headers: CLIENT });
  await ctx.close();
  if (folder) rmSync(folder, { recursive: true, force: true });
});

/** The page scrolls sideways by this many px (0: it doesn't). */
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** Is `inner` inside `outer` horizontally (half a px of rounding allowed)? */
async function inside(inner: Locator, outer: Locator): Promise<boolean> {
  const [i, o] = [await inner.boundingBox(), await outer.boundingBox()];
  return Boolean(i && o && i.x >= o.x - 0.5 && i.x + i.width <= o.x + o.width + 0.5);
}

/** A target of at least 24 × 24 px (WCAG 2.5.8). */
async function bigEnough(target: Locator): Promise<boolean> {
  const box = await target.boundingBox();
  return Boolean(box && box.width >= 24 && box.height >= 24);
}

for (const width of [320, 390, 768, 1280]) {
  test(`${width} px: the waiting letters fit, their names wrap and both answers are full-size targets`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/inbox", "Inbox");
    const group = page.getByRole("region", { name: /From your folder — waiting for you/ });
    await expect(group).toBeVisible();
    expect(await sideways(page), "the page scrolls sideways").toBe(0);
    const list = group.getByRole("list", { name: "Letters waiting for you" });
    const links = list.getByRole("link");
    await expect(links).toHaveCount(3);
    for (const link of await links.all()) {
      expect(await inside(link, list), `${await link.textContent()} stays inside the card`).toBe(true);
      // wrapped, never cut: the whole name is on screen (and in the tooltip, with the file name)
      expect(await link.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      const shown = (await link.textContent())?.trim().replace(/\u2011/g, "-") ?? "";
      expect((await link.getAttribute("title")) ?? "").toContain(shown);
    }
    // the e-mail is named by its subject and sender, read on this computer
    await expect(list.getByText(/^Attached to “Ihre Rechnung September 2026 · FunkNetz Kundenservice”$/)).toBeVisible();
    for (const name of ["Keep private", /^Read these 3 with Claude$/]) {
      const button = group.getByRole("button", { name });
      expect(await bigEnough(button), `${name} is a 24 px target`).toBe(true);
      expect(await inside(button, group), `${name} stays inside the group`).toBe(true);
    }
  });
}

for (const width of [320, 1280]) {
  test(`${width} px: Settings → Watched folder and a waiting letter fit`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/settings?section=folder", "Settings");
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 2, name: "Watched folder" })).toBeVisible();
    await expect(main.getByText("Watching", { exact: true })).toBeVisible();
    await expect(main.getByRole("link", { name: /3 letters waiting for you in the Inbox/ })).toBeVisible();
    const recent = main.getByRole("list", { name: "Last files from the folder" });
    await expect(recent.getByRole("listitem")).toHaveCount(2);
    expect(await sideways(page), "the page scrolls sideways").toBe(0);
    const status = main.locator("section[aria-labelledby='folder-status']");
    expect(await inside(status.getByText(folder!, { exact: true }), status), "the long folder path wraps inside its card").toBe(true);

    const waiting = await apiGet<{ id: string; filename: string }[]>(page, "/api/documents?status=held");
    const scan = waiting.find((d) => d.filename === SCAN)!;
    await open(page, `/documents/${scan.id}`);
    const card = page.getByRole("article", { name: SCAN });
    await expect(card.getByText("Waiting for you")).toBeVisible();
    for (const name of ["Read it with Claude", "Keep private"]) {
      const button = card.getByRole("button", { name });
      expect(await bigEnough(button)).toBe(true);
      expect(await inside(button, card), `${name} stays inside the card`).toBe(true);
      // the label never spills out of its button
      expect(await button.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), `${name}'s label fits`).toBe(true);
    }
    expect(await inside(card.getByRole("heading", { level: 1 }), card), "the long file name wraps inside the card").toBe(true);
    expect(await sideways(page), "the page scrolls sideways").toBe(0);
    if (width >= 1280) {
      // the page image spans both rows: the first is only as tall as the card, so no empty band under it
      // measured to the letter's footer (its rule), not the words in its chip: the chip's own padding and
      // border (UI audit round 1) are not a band under the card
      const next = page.getByRole("main").locator("footer").filter({ hasText: /Waiting for you — not read by AI yet/ }).first();
      const [cardBox, nextBox] = [await card.boundingBox(), await next.boundingBox()];
      expect(cardBox && nextBox && nextBox.y - (cardBox.y + cardBox.height), "the gap under the waiting card").toBeLessThan(48);
    }
  });
}

for (const width of [320, 1280]) {
  test(`${width} px: Today says the letters wait instead of "all clear", and so does the Inbox's count`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/");
    const card = page.getByRole("region", { name: "3 letters from your folder wait for you" });
    await expect(card).toBeVisible();
    const review = card.getByRole("link", { name: /Review them/ });
    expect(await bigEnough(review)).toBe(true);
    expect(await inside(review, card), "“Review them” stays inside the card").toBe(true);
    expect(await sideways(page), "the page scrolls sideways").toBe(0);
    await expect(page.getByText(/Nothing needs you/)).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^Inbox\b.*3 waiting for you$/ })).toBeVisible();
  });
}

test("focus never falls to the page: a refused answer keeps it, and “Undo “Keep private”” moves it to the waiting card", async ({ page }) => {
  // in a real browser a focused button that becomes `disabled` loses focus (jsdom can't show this)
  await page.setViewportSize({ width: 390, height: 844 });
  const waiting = await apiGet<{ id: string; filename: string }[]>(page, "/api/documents?status=held");
  const scan = waiting.find((d) => d.filename === SCAN)!;
  await open(page, `/documents/${scan.id}`);
  const card = page.getByRole("article", { name: SCAN });
  // the demo only replays recorded answers: "Read it with Claude" is refused
  const read = card.getByRole("button", { name: "Read it with Claude" });
  await read.focus();
  const refused = page.waitForResponse((r) => r.url().includes("/api/documents/held/read"));
  await page.keyboard.press("Enter");
  expect((await refused).ok()).toBe(false);
  await expect(read).not.toHaveAttribute("aria-busy", "true");
  await expect(read).toBeFocused();

  await card.getByRole("button", { name: "Keep private" }).click();
  const undo = page.getByRole("main").getByRole("button", { name: "Undo “Keep private”" });
  await undo.focus();
  await page.keyboard.press("Enter");
  const heading = page.getByRole("article", { name: SCAN }).getByRole("heading", { level: 1 });
  await expect(heading).toBeFocused();
  await expect.poll(async () => (await apiGet<{ waiting: number }>(page, "/api/folder")).waiting).toBe(3);
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`without axe violations (${scheme})`, () => {
    test.use({ colorScheme: scheme });
    for (const [width, height] of [
      [390, 844],
      [1280, 800],
    ]) {
      test(`${width}×${height}: the Inbox's waiting letters, Settings → Watched folder, a waiting e-mail`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height });
        await open(page, "/inbox", "Inbox");
        await expectAccessible(page, testInfo, `inbox-waiting-${width}-${scheme}`);
        await open(page, "/settings?section=folder", "Settings");
        await expectAccessible(page, testInfo, `settings-folder-${width}-${scheme}`);
        const mail = (await apiGet<{ id: string; mime: string }[]>(page, "/api/documents?status=held")).find((d) => d.mime === "message/rfc822")!;
        await open(page, `/documents/${mail.id}`);
        await expect(page.getByRole("region", { name: /Attachments/ })).toBeVisible();
        await settle(page);
        await expectAccessible(page, testInfo, `doc-waiting-email-${width}-${scheme}`);
      });
    }
  });
}
