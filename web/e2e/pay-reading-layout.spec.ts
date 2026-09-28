/**
 * The letter's Pay panel and its "How it was read" tab on the real demo, where jsdom can't look (UI audit
 * round 2, document-pay-reading): a copy says "Copied" on its button — no toast over the popover's footer
 * (from 768 px) or unseen behind the phone's sheet — "Mark as paid" hands keyboard focus on to the verdict's
 * heading (never <body>), and the tab's title sits where the verdict's does, so switching tabs doesn't move it.
 */
import type { Page } from "@playwright/test";
import { apiGet, apiPatch, documentId, expect, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const STATEMENT = /Operating and Heating Cost Statement|Betriebs/;

interface Detail {
  items: { id: string; kind: string; status: string }[];
}

async function openStatementPay(page: Page) {
  const id = await documentId(page, STATEMENT);
  await open(page, `/documents/${id}`);
  await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €184\.30/ }).click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByRole("button", { name: "Mark as paid" })).toBeVisible();
  await settle(page);
  return { id, panel };
}

for (const [width, height] of [
  [1280, 800],
  [390, 844],
  [320, 640],
] as const) {
  test(`${width}×${height}: a copy says so on its button, and nothing covers the panel's footer`, async ({ page }) => {
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width, height });
    const { panel } = await openStatementPay(page);
    await expect(panel.getByRole("term")).toHaveText(["Recipient", "IBAN", "Amount", "Reference"]);
    const copy = panel.getByRole("button", { name: "Copy IBAN" });
    const box = (await copy.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(24);
    expect(box.height).toBeGreaterThanOrEqual(24);
    await copy.click();
    const copied = panel.getByRole("button", { name: "IBAN copied" });
    await expect(copied).toBeVisible();
    // the word shows where there is room for it (not in the narrowest sheet, where the check says it)
    if (width > 320) await expect(copied.getByText("Copied")).toBeVisible();
    await expect(page.locator("[data-toast]")).toHaveCount(0);
    const markPaid = panel.getByRole("button", { name: "Mark as paid" });
    expect(
      await markPaid.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return r.bottom <= innerHeight && Boolean(hit && el.contains(hit));
      }),
      "“Mark as paid” is on screen and uncovered",
    ).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}

test("1280×800: after “Mark as paid” with the keyboard, focus is on the verdict's heading and Tab goes on inside the verdict", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const { id, panel } = await openStatementPay(page);
  const detail = await apiGet<Detail>(page, `/api/documents/${id}`);
  const payment = detail.items.find((i) => i.kind === "payment" && i.status === "open")!;
  try {
    await panel.getByRole("button", { name: "Mark as paid" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#verdict-title")).toBeFocused();
    await expect(page.getByRole("button", { name: /^Pay €184\.30/ })).toHaveCount(0);
    await expect(page.locator("#verdict-title")).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest("article[aria-labelledby='verdict-title']")))).toBe(true);
  } finally {
    await apiPatch(page, `/api/items/${payment.id}`, { status: "open" });
  }
});

for (const [width, height] of [
  [1280, 800],
  [390, 844],
] as const) {
  test(`${width}×${height}: “How it was read” keeps the title where the verdict has it`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const id = await documentId(page, /1st Payment Reminder/);
    await open(page, `/documents/${id}`);
    const verdict = page.locator("#verdict-title");
    const before = (await verdict.boundingBox())!;
    const size = await verdict.evaluate((el) => getComputedStyle(el).fontSize);
    await page.getByRole("tab", { name: "How it was read" }).click();
    const trace = page.locator("#trace-title");
    await expect(trace).toBeVisible();
    await settle(page);
    const after = (await trace.boundingBox())!;
    expect(Math.abs(after.x - before.x), "the same left edge").toBeLessThanOrEqual(1);
    expect(Math.abs(after.y - before.y), "the same top").toBeLessThanOrEqual(2);
    expect(await trace.evaluate((el) => getComputedStyle(el).fontSize)).toBe(size);
  });
}
