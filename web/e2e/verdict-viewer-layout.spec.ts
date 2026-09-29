/**
 * The verdict card and the page viewer on real pages (UI audit round 1): the verdict leads in English
 * and with the right to-do, its headline breaks German compounds only at their joints, and the page
 * viewer has no scroll box of its own on phones and tablets (a swipe scrolled only the box).
 */
import type { Locator, Page } from "@playwright/test";
import { documentId, expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function openLetter(page: Page, title: RegExp) {
  await open(page, `/documents/${await documentId(page, title)}`);
}

/** Words of `el` broken across two lines without a hyphen (a compound cut mid-syllable). */
async function brokenWords(el: Locator): Promise<string[]> {
  return el.evaluate((root) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
      const text = node.data;
      for (const m of text.matchAll(/[\p{L}\u00ad]{8,}/gu)) {
        const range = document.createRange();
        range.setStart(node, m.index!);
        range.setEnd(node, m.index! + m[0].length);
        const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
        // a break at a soft hyphen shows a hyphen: fine; anywhere else it cut the word
        if (lines.size > 1 && !m[0].includes("\u00ad")) out.push(m[0]);
      }
    }
    return out;
  });
}

test.describe("phone 320 px: the verdict", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("the headline never cuts a German compound mid-word and the page never scrolls sideways", async ({ page }) => {
    for (const title of [/Immatrikulationsbescheinigung/, /Heizkostenabrechnung/, /Mahnung/]) {
      await openLetter(page, title);
      const h1 = page.getByRole("article").first().getByRole("heading", { level: 1 });
      expect(await brokenWords(h1), `${title}`).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${title} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  });

  test("leads in English, with the letter's German below it", async ({ page }) => {
    await openLetter(page, /Re-registration for Summer Semester 2027/);
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText(/^Pay €312\.40 to /)).toBeVisible();
    await expect(verdict.getByText(/^The letter warns of a late fee/)).toBeVisible();
    await expect(verdict.locator("q[lang=de]").first()).toContainText("Semesterbeitrag");
  });
});

test.describe("phone 390 px: what the verdict leads with, and the viewer", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("an invoice its payment reminder replaced sends you to the reminder — never Pay twice", async ({ page }) => {
    await openLetter(page, /^TechMarkt Online invoice/);
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText("Nothing to pay on this letter — a payment reminder replaced it.")).toBeVisible();
    await expect(verdict.getByRole("button", { name: /^Pay/ })).toHaveCount(0);
    await expect(verdict.getByText(/overdue/)).toHaveCount(0);
    await expect(verdict.getByRole("link", { name: /Open the payment reminder/ })).toBeVisible();
    // the list below says so too, uncounted (UI audit round 2: "25 days overdue" in red under this verdict)
    const todos = page.getByRole("region", { name: /To-dos & dates/ });
    await expect(todos).not.toContainText("overdue");
    await expect(todos).toContainText("Replaced by the payment reminder of");
    await expect(todos.getByRole("heading", { level: 2 })).toContainText("0 open");
  });

  test("an archived lease's deposit is 'Still open?', not '362 days overdue'", async ({ page }) => {
    await openLetter(page, /Rental Lease Agreement/);
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText(/overdue/)).toHaveCount(0);
    await expect(verdict.getByRole("list", { name: "Probably dealt with" })).toContainText("Still open? Security deposit");
    // … and so does the list below; the lease you can cancel any month has no "decide by … tomorrow" (UI audit round 2)
    const todos = page.getByRole("region", { name: /To-dos & dates/ });
    await expect(todos).not.toContainText("overdue");
    await expect(todos).toContainText("Already past when the letter was added");
    const contract = page.getByRole("region", { name: "Contract" });
    await expect(contract).toContainText("Cancel any time");
    await expect(contract).not.toContainText(/decide by/i);
  });

  test("the pages are no scroll box of their own; the pager turns them", async ({ page }) => {
    await openLetter(page, /Operating and Heating Cost Statement/);
    const pages = page.getByRole("region", { name: "Letter pages" });
    const images = pages.getByRole("group", { name: "Page images" });
    const box = await images.evaluate((el) => ({ overflowY: getComputedStyle(el).overflowY, scroll: el.scrollHeight - el.clientHeight }));
    expect(box.overflowY).not.toMatch(/auto|scroll/);
    expect(box.scroll).toBeLessThanOrEqual(1);
    const pager = pages.getByRole("navigation", { name: "Turn pages" });
    await pager.getByRole("button", { name: "Next" }).click();
    await expect(pages.getByRole("img", { name: "Page 2 of 2" })).toBeVisible();
  });

  test("a fact on a photo: the quote sits under the photo, Escape closes it, and 'Back to …' returns", async ({ page }) => {
    await openLetter(page, /^Passport of/);
    const chip = page.getByRole("button", { name: /show “.*” on the page/ }).first();
    await chip.scrollIntoViewIfNeeded();
    const before = (await chip.boundingBox())!.y;
    await chip.click();
    const quote = page.getByTestId("evidence-quote");
    await expect(quote).toBeVisible();
    const photo = (await page.getByRole("img", { name: /^Page 1 of/ }).boundingBox())!;
    expect((await quote.boundingBox())!.y).toBeGreaterThanOrEqual(photo.y + photo.height - 1);
    await page.keyboard.press("Escape");
    await expect(quote).toHaveCount(0);
    await page.getByRole("button", { name: /^Back to/ }).click();
    await expect.poll(async () => Math.round((await chip.boundingBox())!.y)).toBe(Math.round(before));
  });
});
