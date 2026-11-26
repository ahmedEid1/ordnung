/**
 * A long Inbox on real pages: it draws the first 100 letters of a view, says how many it shows, and draws 100 more or
 * all of them as asked. The demo has 22 letters, so each test answers the letter list with the demo's own letters
 * under 230 made-up ones (newer, so the demo's letters sit at the bottom and still open): the app is the released one,
 * with no switch of its own for tests.
 *
 * - "Show all", then the Inbox loaded again by its address: 100 rows (a new load starts afresh); a reload of the same
 *   entry keeps them, and nothing about them is in sessionStorage.
 * - A letter opened from far down, then Back: the rows and the place are back.
 * - Another view (a kind) starts at 100.
 * - From the keyboard, "Show 100 more" takes focus to the first new letter.
 * Runs in the "layout" project (its name ends in `layout.spec.ts`).
 */
import type { Page } from "@playwright/test";
import type { ListedLetter } from "@/api/types";
import { expect, open, setTour, test } from "./helpers";

const MADE_UP = 230;

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
  // the letter list: the demo's letters under 230 made-up invoices, as a household with years of letters has them
  await page.route(
    // the whole list, as the Inbox asks for it (no search, no other question)
    (url) => url.pathname === "/api/documents" && url.search === "",
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const response = await route.fetch();
      const real = (await response.json()) as ListedLetter[];
      // the day the newest demo letter is listed under: the made-up ones arrived that day, and were added later
      const day = real.map((d) => d.received_date ?? d.created_at.slice(0, 10)).reduce((a, b) => (b > a ? b : a));
      const madeUp = Array.from({ length: MADE_UP }, (_, i): ListedLetter => {
        const n = String(i + 1).padStart(3, "0");
        return {
          ...real[0]!,
          id: `doc_rows${n}`,
          title: `Stadtwerke Musterstadt: monthly bill ${n}`,
          kind: "invoice",
          status: "processed",
          ai_private: false,
          party_id: null,
          summary: null,
          received_date: day,
          doc_date: day,
          created_at: `2099-01-01T00:${String(Math.floor(i / 60)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}Z`,
        };
      });
      await route.fulfill({ response, json: [...madeUp, ...real] });
    },
  );
  // the made-up letters have no pages: their thumbnails are left empty rather than asked of the server
  await page.route(/\/api\/documents\/doc_rows\d+\/thumbnail/, (route) => route.fulfill({ status: 204 }));
});

/** The letter rows drawn. */
const rows = (page: Page) => page.locator("section[aria-labelledby^='grp-'] > ul > li");

async function total(page: Page): Promise<number> {
  const all = await page.getByRole("button", { name: /^Show all / }).textContent();
  return Number(all!.replace(/\D/g, ""));
}

test("draws 100 rows; Show all draws every one, kept by a reload of the entry, not by a new load", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  await expect(rows(page)).toHaveCount(100);
  const n = await total(page);
  expect(n).toBeGreaterThan(MADE_UP);
  await expect(page.getByText(`Showing 100 of ${n} letters. The search looks through all of them`)).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^Showing/ })).toHaveText(`Showing 100 of ${n} letters.`);

  await page.getByRole("button", { name: `Show all ${n}` }).click();
  await expect(rows(page)).toHaveCount(n);
  await expect(page.getByRole("button", { name: /^Show / })).toHaveCount(0);

  // the same entry, reloaded: every row again
  await page.reload();
  await expect(rows(page)).toHaveCount(n);

  // the Inbox by its address (a typed address, a bookmark): a new load starts at 100
  await page.goto("/inbox");
  await expect(rows(page)).toHaveCount(100);
  const kept = await page.evaluate(() => Object.entries(sessionStorage).filter(([k, v]) => /row/i.test(k) || v.includes("inboxRows")));
  expect(kept, "nothing about the rows in sessionStorage").toEqual([]);
});

test("a letter opened from far down, then Back: the rows and the place are back", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  const n = await total(page);
  await page.getByRole("button", { name: `Show all ${n}` }).click();
  await expect(rows(page)).toHaveCount(n);
  // a demo letter near the bottom (a real one: it opens)
  const far = rows(page).nth(n - 3).locator("a[href^='/documents/']");
  await far.scrollIntoViewIfNeeded();
  const href = await far.getAttribute("href");
  const placeBefore = await page.evaluate(() => window.scrollY);
  expect(placeBefore).toBeGreaterThan(5000);
  await far.click();
  await page.waitForURL(`**${href}`);
  await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();

  await page.goBack();
  await page.waitForURL("**/inbox");
  await expect(rows(page)).toHaveCount(n);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(placeBefore - 40);
  expect(await page.evaluate(() => window.scrollY)).toBeLessThan(placeBefore + 40);
  await expect(page.locator(`a[href='${href}']`)).toBeInViewport();
});

test("another view starts at 100 again", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  const n = await total(page);
  await page.getByRole("button", { name: `Show all ${n}` }).click();
  await expect(rows(page)).toHaveCount(n);
  await page.getByRole("combobox", { name: /Kind/ }).selectOption("invoice");
  await expect(rows(page)).toHaveCount(100);
  // what the view holds, then the rows drawn of it
  await expect(page.getByText(new RegExp(`^\\d+ of ${n} letters in this view\\.$`))).toBeVisible();
});

test("from the keyboard, Show 100 more takes focus to the first new letter", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  const more = page.getByRole("button", { name: "Show 100 more" });
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(rows(page)).toHaveCount(200);
  await expect(rows(page).nth(100).locator("a[href^='/documents/']")).toBeFocused();
  await expect(page.getByRole("status").filter({ hasText: /^Showing/ })).toHaveText(/^Showing 200 of \d+ letters\.$/);
});
