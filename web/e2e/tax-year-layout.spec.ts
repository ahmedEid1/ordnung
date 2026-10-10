/**
 * The Tax year page and the Export letters dialog on real pages (what jsdom can't measure), from 320 to 1280 px: no
 * sideways scroll, each letter's tax note wraps inside its row, the Year field fits, the dialog fits the screen with
 * its download in reach — and the Inbox's toolbar still fits every filter tab with the "Letters for taxes" link in
 * its header. Runs against the demo (its letters for taxes are dated 2026) in the "layout" project; it downloads
 * nothing and changes nothing.
 */
import type { Page } from "@playwright/test";
import { expect, expectAccessible, open, setTour, settle, test } from "./helpers";

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

for (const width of [320, 390, 768, 1280]) {
  test.describe(`${width} px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the Tax year page fits: its notes wrap inside their rows, the Year field in the column", async ({ page }) => {
      await open(page, "/inbox/taxes?year=2026", "Tax year 2026");
      expect(await sideways(page), "the page scrolls sideways").toBe(0);
      const m = await page.evaluate(() => {
        const box = (el: Element) => el.getBoundingClientRect();
        const main = box(document.querySelector("main")!);
        const notes = Array.from(document.querySelectorAll("[data-letter-note]")).map((note) => {
          const row = box(note.closest("li")!);
          const b = box(note);
          return { left: b.left - row.left, right: row.right - b.right, overflow: note.scrollWidth - note.clientWidth };
        });
        const year = box(document.querySelector("select")!);
        return { notes, year: { left: year.left - main.left, right: main.right - year.right } };
      });
      expect(m.notes.length, "every letter for taxes has its note").toBeGreaterThan(0);
      for (const note of m.notes) {
        expect(note.left, "a note starts outside its row").toBeGreaterThanOrEqual(0);
        expect(note.right, "a note sticks out of its row").toBeGreaterThanOrEqual(0);
        expect(note.overflow, "a note's words are cut off").toBeLessThanOrEqual(0);
      }
      expect(m.year.left).toBeGreaterThanOrEqual(0);
      expect(m.year.right).toBeGreaterThanOrEqual(0);
    });

    test("the Export letters dialog fits, with its download in reach", async ({ page }) => {
      await open(page, "/inbox/taxes?year=2026", "Tax year 2026");
      await page.getByRole("button", { name: "Export these letters…" }).click();
      const dialog = page.getByRole("dialog", { name: "Export letters" });
      await expect(dialog.getByRole("status")).toHaveText(/^\d+ letters? will be in the ZIP\.$/);
      await settle(page);
      const panel = await dialog.boundingBox();
      expect(panel!.x).toBeGreaterThanOrEqual(0);
      expect(panel!.x + panel!.width).toBeLessThanOrEqual(width + 0.5);
      expect(await sideways(page)).toBe(0);
      const download = dialog.getByRole("link", { name: "Download ZIP" });
      await download.scrollIntoViewIfNeeded();
      await expect(download).toBeInViewport();
      await expect(download).toHaveAttribute("href", /\/api\/documents\.zip\?year=2026&tax=true$/);
      await expect(dialog.getByText(/The ZIP isn't encrypted/)).toBeVisible();
      if (width === 1280) await expectAccessible(page, test.info(), "export-dialog");
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
    });

    test("the Inbox's toolbar still fits with the Letters for taxes link in the header", async ({ page }) => {
      await open(page, "/inbox", "Inbox");
      const link = page.getByRole("main").getByRole("link", { name: "Letters for taxes" });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", "/inbox/taxes");
      const m = await page.evaluate(() => {
        const tabs = document.querySelector<HTMLElement>('[role="tablist"][aria-label="Filter letters"]')!;
        const column = document.querySelector('[role="tabpanel"][id^="inbox-filter-panel-"]')!.getBoundingClientRect();
        return { tabsHidden: tabs.scrollWidth - tabs.clientWidth, tabsRight: tabs.parentElement!.getBoundingClientRect().right, columnRight: column.right };
      });
      expect(await sideways(page), "the page scrolls sideways").toBe(0);
      expect(m.tabsHidden, "a filter tab is cut off").toBeLessThanOrEqual(0);
      expect(m.tabsRight).toBeLessThanOrEqual(m.columnRight + 0.5);
      const box = await link.boundingBox();
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 0.5);
      expect(box!.height).toBeGreaterThanOrEqual(24);
    });
  });
}
