/**
 * Settings → Reminders → "Desktop notification each morning", Settings → Calendar → "Sync with
 * your own calendar" and Settings → Data → "Encrypted backup" on the real demo, where jsdom can't
 * look: nothing scrolls sideways at 320 px, the notification preview, the app-menu line and long
 * calendar addresses wrap inside their cards, focus is never hidden under the fixed bars, the passphrase and
 * disconnect dialogs fit a phone as a sheet, all pass axe in light and dark mode — and a backup
 * made through the browser really is an Ordnung backup file, after which the card says the last backup
 * was made today. Settings → Your computers says that the demo never syncs (hand-off sync's two real
 * computers are e2e/real-app-sync.spec.ts).
 */
import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { apiGet, expect, expectAccessible, open, setTour, settle, test } from "./helpers";

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function noSidewaysScroll(page: Page): Promise<void> {
  const width = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(width[0], "the page scrolls sideways").toBeLessThanOrEqual(width[1]!);
}

async function inside(inner: Locator, outer: Locator): Promise<void> {
  const a = (await inner.boundingBox())!;
  const b = (await outer.boundingBox())!;
  expect(a.x).toBeGreaterThanOrEqual(b.x - 0.5);
  expect(a.x + a.width).toBeLessThanOrEqual(b.x + b.width + 0.5);
}

/** Tab through `stops` controls; none may end up under the sticky top bar or the phone tab bar. */
async function focusStaysVisible(page: Page, stops: number): Promise<void> {
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press("Tab");
    const covered = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const r = el.getBoundingClientRect();
      if (!r.height || r.height > innerHeight - 160) return null;
      for (const y of [r.top + 1, r.bottom - 1]) {
        const top = document.elementFromPoint(r.left + Math.min(r.width / 2, 12), Math.min(Math.max(0, y), innerHeight - 1));
        if (!top || el.contains(top) || top.contains(el)) continue;
        for (let n: Element | null = top; n; n = n.parentElement) {
          const pos = getComputedStyle(n).position;
          if ((pos === "fixed" || pos === "sticky") && !n.contains(el)) return (el.getAttribute("aria-label") ?? el.textContent ?? el.tagName).trim().slice(0, 60);
        }
      }
      return null;
    });
    expect(covered, "a focused control is hidden under a fixed bar").toBeNull();
  }
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
  [1280, 800],
]) {
  test(`desktop notification at ${width}×${height}: the preview wraps in its card, nothing scrolls sideways`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/settings?section=reminders", "Settings");
    const card = page.getByRole("region", { name: "Desktop notification each morning" });
    await card.scrollIntoViewIfNeeded();
    const on = card.getByRole("switch", { name: /Notify me each morning/ });
    await expect(on).toHaveAttribute("aria-checked", "false");
    await on.click();
    await expect(card.getByRole("radio", { name: "Discreet" })).toBeChecked();
    await card.getByRole("radio", { name: "With details" }).click();
    await settle(page);
    await expect(card.getByLabel("Show it at")).toHaveValue("08:00");
    const preview = card.getByRole("figure");
    await expect(preview).toContainText("Today it would say");
    await inside(preview, card);
    await noSidewaysScroll(page);
    // the command to start at login wraps rather than running off the card
    await inside(card.getByText("ordnung autostart enable", { exact: true }), card);
    // and so does the app-menu line (the demo's: it opens with `ordnung demo`, nothing to copy)
    await inside(card.getByRole("heading", { level: 4, name: "Open Ordnung from your app menu" }), card);
    await inside(card.getByText(/^The demo opens with/), card);
    // unsaved: the save bar is on screen and Discard puts it back
    await expect(card.getByRole("button", { name: "Save changes" })).toBeInViewport();
    await card.getByRole("radio", { name: "With details" }).focus();
    await focusStaysVisible(page, 8);
    await card.getByRole("button", { name: "Discard" }).click();
    await expect(on).toHaveAttribute("aria-checked", "false");
    await expect(card.getByRole("radiogroup")).toHaveCount(0);
  });

  test(`backup dialog at ${width}×${height}: fits the screen and takes a suggested passphrase`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/settings?section=data", "Settings");
    const card = page.getByRole("region", { name: "Encrypted backup" });
    await expect(card).toContainText(/Now: \d+ letters · \d+ files · about/);
    // when the last backup was made: none yet in the demo (until this file's own download, further down) — and
    // never as a warning there, since the demo never says one is due
    const { last_copy } = await apiGet<{ last_copy: { last_backup_at: string | null; due: boolean } }>(page, "/api/backup");
    expect(last_copy.due).toBe(false);
    if (last_copy.last_backup_at === null) await expect(card.getByText("Ordnung has no record of a backup made on this computer.")).toBeVisible();
    else await expect(card).toContainText("Last backup: today");
    await inside(card.getByText(/^(Ordnung has no record of a backup made on this computer\.|Last backup:)/).first(), card);
    await inside(card.getByText(/^ordnung restore /), card);
    // the date in the file name is never split over two lines (it is copied by hand sometimes)
    const dateLines = await card.getByText(/^ordnung restore /).evaluate((code) => {
      const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!/\d{4}\u2011\d{2}\u2011\d{2}/.test(n.textContent ?? "")) continue;
        const range = document.createRange();
        range.selectNodeContents(n);
        return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
      }
      return -1;
    });
    expect(dateLines).toBe(1);
    // the footer's button lines up with the card's text (at 320 px its label is wider than the row)
    const button = (await card.getByRole("button", { name: "Download encrypted backup…" }).boundingBox())!;
    const heading = (await card.getByRole("heading", { name: "Encrypted backup" }).boundingBox())!;
    expect(button.x).toBeGreaterThanOrEqual(heading.x - 0.5);
    await noSidewaysScroll(page);
    await card.getByRole("button", { name: "Download encrypted backup…" }).click();
    const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
    await expect(dialog.getByLabel("Passphrase", { exact: true })).toBeFocused();
    await dialog.getByRole("button", { name: "Suggest a strong one" }).click();
    // five made-up words, as hand-off sync suggests
    await expect(dialog.getByLabel("Passphrase", { exact: true })).toHaveValue(/^[a-z]{5}(-[a-z]{5}){4}$/);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
    await expect(dialog.getByRole("button", { name: "Download backup" })).toBeInViewport();
    await noSidewaysScroll(page);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });
}

/** Calendar sync available (the demo itself refuses to connect): the form, as on your own Ordnung. */
const AVAILABLE = {
  available: true,
  unavailable: null,
  install_command: null,
  connected: false,
  url: null,
  username: null,
  calendar_name: null,
  mode: "discreet",
  password_saved: false,
  paused: false,
  events: 32,
  synced: 0,
  last_sync: null,
};

for (const [width, height] of [
  [320, 640],
  [390, 844],
]) {
  test(`calendar sync at ${width}×${height}: what "Find my calendars" says is on screen, and "Show fewer" keeps its button in view`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.route(
      (url) => url.pathname === "/api/calendar/sync",
      (route) => (route.request().method() === "GET" ? route.fulfill({ json: AVAILABLE }) : route.fallback()),
    );
    await page.route(
      (url) => url.pathname === "/api/calendar/sync/discover",
      (route) => route.fulfill({ status: 502, json: { detail: "Couldn't reach caldav.icloud.com.", code: "network" } }),
    );
    await open(page, "/settings?section=calendar", "Settings");
    const card = page.getByRole("region", { name: "Sync with your own calendar" });
    await card.getByLabel("Calendar or server address").fill("https://caldav.icloud.com");
    await card.getByLabel("User name").fill("samantha.rivera-musterfrau@icloud.com");
    await card.getByLabel("App password").fill("abcd-efgh-ijkl-mnop");
    // sent with Enter from the password field, far above the footer on a phone
    await card.getByLabel("App password").press("Enter");
    const error = card.getByRole("alert").filter({ hasText: "Couldn't reach caldav.icloud.com." });
    await expect(error).toBeFocused();
    await expect(error).toBeInViewport();
    await expect(card.getByRole("button", { name: "Find my calendars" })).toBeInViewport();
    await inside(error, card);
    await noSidewaysScroll(page);

    // the preview opens on what is still to come, and collapsing it keeps the toggle on screen
    const toggle = card.getByRole("button", { name: /^Show all \d+ events/ });
    await toggle.click();
    await card.getByRole("button", { name: "Show fewer" }).scrollIntoViewIfNeeded();
    await card.getByRole("button", { name: "Show fewer" }).click();
    const back = card.getByRole("button", { name: /^Show all \d+ events/ });
    await expect(back).toBeFocused();
    await expect(back).toBeInViewport({ ratio: 1 });
    const covered = await back.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !(top && (el === top || el.contains(top)));
    });
    expect(covered, "the focused toggle is under the top bar").toBe(false);
  });
}

/** Calendar sync connected to a long iCloud address (the demo itself never connects). */
const CONNECTED = {
  available: true,
  unavailable: null,
  install_command: null,
  connected: true,
  url: "https://p142-caldav.icloud.com:443/11837429562/calendars/9F3B6E1A-4C2D-4F7B-9A1E-6D2C8B5E7F10/",
  username: "samantha.rivera-musterfrau@icloud.com",
  calendar_name: "Ordnung — Fristen und Termine",
  mode: "discreet",
  password_saved: true,
  paused: false,
  events: 32,
  synced: 32,
  last_sync: { at: "2026-09-28T07:58:00Z", sent: 2, removed: 1, unchanged: 29, failed: 0, error: null, error_kind: null },
};

async function connectedCalendar(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === "/api/calendar/sync",
    (route) => (route.request().method() === "GET" ? route.fulfill({ json: CONNECTED }) : route.fallback()),
  );
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
  [1280, 800],
]) {
  test(`calendar sync at ${width}×${height}: the demo's preview and a connected calendar fit their card`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/settings?section=calendar", "Settings");
    let card = page.getByRole("region", { name: "Sync with your own calendar" });
    // the demo never sends Sam's dates anywhere, and says so — the preview still shows what would go
    await expect(card.getByRole("note")).toContainText("The demo doesn't send Sam's dates anywhere");
    const events = card.getByRole("list", { name: "Events, discreet" });
    await expect(events.getByRole("listitem").first()).toContainText(/Ordnung: (deadline|payment|appointment)/);
    await inside(events, card);
    await card.getByRole("radio", { name: "With details" }).click();
    await inside(card.getByRole("list", { name: "Events, with details" }), card);
    await noSidewaysScroll(page);

    await connectedCalendar(page);
    await page.reload();
    card = page.getByRole("region", { name: "Sync with your own calendar" });
    await expect(card.getByText("Connected to Ordnung — Fristen und Termine")).toBeVisible();
    await inside(card.getByText(/p142-caldav\.icloud\.com/), card);
    await noSidewaysScroll(page);
    await card.getByRole("button", { name: "Sync now" }).focus();
    await focusStaysVisible(page, 6);
    await card.getByRole("button", { name: "Disconnect…" }).click();
    const dialog = page.getByRole("dialog", { name: "Disconnect Ordnung — Fristen und Termine?" });
    await expect(dialog.getByRole("checkbox", { name: /Also remove Ordnung's 32 events/ })).toBeChecked();
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
    await expect(dialog.getByRole("button", { name: "Disconnect" })).toBeInViewport();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });
}

test("a backup that fails at 320×640 shows why on screen, not under the sheet's footer", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.route(
    (url) => new URL(url.href).pathname === "/api/backup",
    (route) => (route.request().method() === "POST" ? route.fulfill({ status: 507, json: { detail: "There is no space left on the drive" } }) : route.fallback()),
  );
  await open(page, "/settings?section=data", "Settings");
  await page.getByRole("region", { name: "Encrypted backup" }).getByRole("button", { name: "Download encrypted backup…" }).click();
  const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
  await dialog.getByRole("button", { name: "Suggest a strong one" }).click();
  await dialog.getByRole("button", { name: "Download backup" }).click();
  const reason = dialog.getByRole("alert");
  await expect(reason).toContainText("Nothing was saved.");
  await expect(page.locator("#backup-error")).toBeFocused();
  // its title is where a finger could tap it: on top, not under the footer's buttons
  const title = reason.getByText("Couldn't make the backup");
  await expect(title).toBeInViewport();
  const onTop = await title.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + 4, r.top + r.height / 2);
    return Boolean(hit && (el.contains(hit) || hit.contains(el)));
  });
  expect(onTop, "the error's title is covered").toBe(true);
  await page.unroute((url) => new URL(url.href).pathname === "/api/backup");
});

test("a backup made in the browser is an encrypted Ordnung backup", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/settings?section=data", "Settings");
  await page.getByRole("region", { name: "Encrypted backup" }).getByRole("button", { name: "Download encrypted backup…" }).click();
  const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
  // strong enough for a new backup (the rule of a new sync folder): five words that don't belong together
  await dialog.getByLabel("Passphrase", { exact: true }).fill("Sam's orbit velvet canyon maple");
  await dialog.getByLabel("Repeat the passphrase").fill("Sam's orbit velvet canyon maple");
  // Enter in a field submits: the footer's button belongs to the dialog's form
  const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByLabel("Repeat the passphrase").press("Enter")]);
  expect(download.suggestedFilename()).toMatch(/^ordnung-backup-\d{4}-\d{2}-\d{2}\.ordnung-backup$/);
  const bytes = await readFile((await download.path())!);
  expect(bytes.subarray(0, 15).toString("latin1")).toBe("ORDNUNG-BACKUP\n");
  expect(bytes.length).toBeGreaterThan(100_000); // the demo's letters and page images, encrypted
  expect(bytes.includes(Buffer.from("Sam Rivera"))).toBe(false);
  await expect(page.getByRole("region", { name: "Encrypted backup" }).getByRole("status")).toContainText(`Downloaded ${download.suggestedFilename()}`);
  // the server noted it: the card asks again and says when
  await expect(page.getByRole("region", { name: "Encrypted backup" })).toContainText("Last backup: today");
});

/** `ordnung.sync.DEMO_MESSAGE`: the demo's answer to hand-off sync (tests/test_e2e_support.py keeps the two equal). */
const SYNC_DEMO_MESSAGE = "This is the demo, so it doesn't sync. Your own Ordnung can.";

test("the demo never syncs: Settings → Your computers says so, and setting it up is refused", async ({ page }) => {
  const status = (await (await page.request.get("/api/sync")).json()) as { available: boolean; unavailable: string | null; connected: boolean; mode: string };
  expect(status).toMatchObject({ available: false, unavailable: SYNC_DEMO_MESSAGE, connected: false, mode: "off" });
  // refused before anything is looked at: no folder is inspected or written, no passphrase is kept
  const refused = await page.request.put("/api/sync", {
    data: { folder: "/nonexistent/ordnung-sync", name: "demo", passphrase: "orbit velvet canyon maple thunder", keep: null },
    headers: { "X-Ordnung-Client": "web" },
  });
  expect(refused.status()).toBe(409);
  expect(await refused.json()).toEqual({ detail: SYNC_DEMO_MESSAGE, code: "unavailable" });
  await open(page, "/settings?section=computers", "Settings");
  await expect(page.getByRole("main").getByText(SYNC_DEMO_MESSAGE).first()).toBeVisible();
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`without axe violations (${scheme})`, () => {
    test.use({ colorScheme: scheme });

    test("the desktop notification card with a preview", async ({ page }) => {
      await open(page, "/settings?section=reminders", "Settings");
      const card = page.getByRole("region", { name: "Desktop notification each morning" });
      await card.getByRole("switch", { name: /Notify me each morning/ }).click();
      await expect(card.getByRole("figure")).toContainText("Today it would say");
      // the whole card on screen, just below the top bar: nothing of it under a sticky bar (a
      // page scan would count whatever else the scroll position puts half under the top bar)
      await card.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 72));
      await settle(page);
      const results = await new AxeBuilder({ page }).include('section[aria-labelledby="set-desktop"]').withTags(AXE_TAGS).analyze();
      const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
      await card.getByRole("button", { name: "Discard" }).click();
    });

    for (const connected of [false, true]) {
      test(`calendar sync ${connected ? "connected" : "in the demo"}`, async ({ page }) => {
        if (connected) await connectedCalendar(page);
        await open(page, "/settings?section=calendar", "Settings");
        const card = page.getByRole("region", { name: "Sync with your own calendar" });
        await expect(card.getByRole("list", { name: "Events, discreet" })).toBeVisible();
        await card.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 72));
        await settle(page);
        const results = await new AxeBuilder({ page }).include('section[aria-labelledby="set-cal-sync"]').withTags(AXE_TAGS).analyze();
        const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
      });
    }

    test("the backup dialog with its errors", async ({ page }, testInfo) => {
      await open(page, "/settings?section=data", "Settings");
      await page.getByRole("region", { name: "Encrypted backup" }).getByRole("button", { name: "Download encrypted backup…" }).click();
      const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
      await dialog.getByLabel("Passphrase", { exact: true }).fill("too short");
      await dialog.getByRole("button", { name: "Download backup" }).click();
      await expect(dialog.getByText(/Use a passphrase of at least 12 characters/)).toBeVisible();
      await settle(page);
      await expectAccessible(page, testInfo, `backup-dialog-${scheme}`);
    });
  });
}
