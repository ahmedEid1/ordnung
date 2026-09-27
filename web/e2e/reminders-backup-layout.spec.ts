/**
 * Settings → Reminders → "Desktop notification each morning", Settings → Calendar → "Sync with
 * your own calendar" and Settings → Data → "Encrypted backup" on the real demo, where jsdom can't
 * look: nothing scrolls sideways at 320 px, the notification preview and long calendar addresses
 * wrap inside their cards, focus is never hidden under the fixed bars, the passphrase and
 * disconnect dialogs fit a phone as a sheet, all pass axe in light and dark mode — and a backup
 * made through the browser really is an Ordnung backup file.
 */
import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { expect, expectAccessible, open, setTour, settle, test } from "./helpers";

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
    await expect(card.getByLabel("Show it from")).toHaveValue("08:00");
    const preview = card.getByRole("figure");
    await expect(preview).toContainText("Today it would say");
    await inside(preview, card);
    await noSidewaysScroll(page);
    // the command to start at login wraps rather than running off the card
    await inside(card.getByText("ordnung autostart enable", { exact: true }), card);
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
    await inside(card.getByText(/^ordnung restore /), card);
    await noSidewaysScroll(page);
    await card.getByRole("button", { name: "Download encrypted backup…" }).click();
    const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
    await expect(dialog.getByLabel("Passphrase", { exact: true })).toBeFocused();
    await dialog.getByRole("button", { name: "Suggest a strong one" }).click();
    await expect(dialog.getByLabel("Passphrase", { exact: true })).toHaveValue(/^[a-z2-9]{5}(-[a-z2-9]{5}){3}$/);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
    await expect(dialog.getByRole("button", { name: "Download backup" })).toBeInViewport();
    await noSidewaysScroll(page);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
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

test("a backup made in the browser is an encrypted Ordnung backup", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/settings?section=data", "Settings");
  await page.getByRole("region", { name: "Encrypted backup" }).getByRole("button", { name: "Download encrypted backup…" }).click();
  const dialog = page.getByRole("dialog", { name: "Download an encrypted backup" });
  await dialog.getByLabel("Passphrase", { exact: true }).fill("Sam's end-to-end passphrase");
  await dialog.getByLabel("Repeat the passphrase").fill("Sam's end-to-end passphrase");
  // Enter in a field submits: the footer's button belongs to the dialog's form
  const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByLabel("Repeat the passphrase").press("Enter")]);
  expect(download.suggestedFilename()).toMatch(/^ordnung-backup-\d{4}-\d{2}-\d{2}\.ordnung-backup$/);
  const bytes = await readFile((await download.path())!);
  expect(bytes.subarray(0, 15).toString("latin1")).toBe("ORDNUNG-BACKUP\n");
  expect(bytes.length).toBeGreaterThan(100_000); // the demo's letters and page images, encrypted
  expect(bytes.includes(Buffer.from("Sam Rivera"))).toBe(false);
  await expect(page.getByRole("region", { name: "Encrypted backup" }).getByRole("status")).toContainText(`Downloaded ${download.suggestedFilename()}`);
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
      await expect(dialog.getByText(/Use at least 12 characters/)).toBeVisible();
      await settle(page);
      await expectAccessible(page, testInfo, `backup-dialog-${scheme}`);
    });
  });
}
