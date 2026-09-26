/**
 * The Inbox's toolbar, New-mail tray and load states on real pages (what jsdom can't measure):
 * every filter tab in view and the search wide enough for its words from 320 px up, a lone last
 * envelope that takes its whole row, a loading skeleton that fits a phone, and a list that failed
 * to load saying so (never "No letters yet"). Runs in the "layout" project (its name ends in
 * `layout.spec.ts`). The tray is answered here, so the tests don't depend on which letters other
 * tests have read.
 */
import type { Page } from "@playwright/test";
import { expect, open, setTour, test } from "./helpers";

const TRAY = [
  { id: "ui_1", filename: "a.jpg", sender: "Finanzamt Musterstadt", subject: "Steuerbescheid 2025", kind_hint: "tax_assessment", photo: true, opened: false, doc_id: null },
  { id: "ui_2", filename: "b.pdf", sender: "Stadtwerke Musterstadt GmbH", subject: "Preisanpassung Strom", kind_hint: "price_increase", photo: false, opened: false, doc_id: null },
  { id: "ui_3", filename: "c.pdf", sender: "Rundfunk-Beitragsservice – Zahlungszentrale", subject: "Letzte Mahnung Rundfunkbeitrag", kind_hint: "broadcasting_fee", photo: false, opened: false, doc_id: null },
];
/** `GET /api/documents` (the list and its search), not a letter's own URL. */
const DOCUMENT_LIST = /\/api\/documents(\?.*)?$/;

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
  await page.route("**/api/demo/mail", (route) => (route.request().method() === "GET" ? route.fulfill({ json: TRAY }) : route.continue()));
});

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

for (const width of [320, 390, 768, 1280]) {
  test.describe(`${width} px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the toolbar fits: every filter tab in view, the search as wide as it can be", async ({ page }) => {
      await open(page, "/inbox", "Inbox");
      const m = await page.evaluate(() => {
        const tabs = document.querySelector<HTMLElement>('[role="tablist"][aria-label="Filter letters"]')!;
        const box = (el: Element) => el.getBoundingClientRect();
        return {
          tabsHidden: tabs.scrollWidth - tabs.clientWidth,
          tabsRight: box(tabs.parentElement!).right,
          track: Math.round(box(tabs.parentElement!).height),
          search: box(document.getElementById("inbox-search")!),
          kind: box(document.getElementById("inbox-kind")!),
          column: box(document.querySelector('[role="tabpanel"][id^="inbox-filter-panel-"]')!),
        };
      });
      expect(await sideways(page), "the page scrolls sideways").toBe(0);
      expect(m.tabsHidden, "a filter tab is cut off").toBeLessThanOrEqual(0);
      expect(m.tabsRight).toBeLessThanOrEqual(m.column.right + 0.5);
      // one height for the row's controls
      expect(m.track).toBe(Math.round(m.search.height));
      expect(Math.round(m.kind.height)).toBe(Math.round(m.search.height));
      if (width < 640) {
        // phones: the search and the kind picker each get the whole row
        expect(Math.abs(m.search.width - m.column.width)).toBeLessThanOrEqual(1);
        expect(Math.abs(m.kind.width - m.column.width)).toBeLessThanOrEqual(1);
      } else {
        expect(m.search.width).toBeGreaterThanOrEqual(280);
      }
    });

    test("New mail: a lone last envelope takes its row, no envelope is squeezed", async ({ page }) => {
      await open(page, "/inbox", "Inbox");
      const tray = page.getByRole("region", { name: "New mail, 3 letters" });
      await expect(tray).toBeVisible();
      const cards = await tray.getByRole("listitem").evaluateAll((lis) =>
        lis.map((li) => {
          const r = li.getBoundingClientRect();
          return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) };
        }),
      );
      const list = await tray.getByRole("list").evaluate((ul) => Math.round(ul.getBoundingClientRect().width));
      expect(cards).toHaveLength(3);
      for (const c of cards) expect(c.w, "an envelope narrower than its sender's name").toBeGreaterThanOrEqual(240);
      if (width >= 640) {
        const last = cards[2]!;
        const sameRow = cards.filter((c) => c.y === last.y);
        // alone in its row → as wide as the list; otherwise it shares the row with the others
        if (sameRow.length === 1) expect(Math.abs(last.w - list)).toBeLessThanOrEqual(1);
        else expect(sameRow).toHaveLength(3);
      }
      expect(await sideways(page)).toBe(0);
    });
  });
}

test.describe("load states on a phone", () => {
  test.use({ viewport: { width: 320, height: 700 } });

  test("while the letters load, the skeleton fits the screen", async ({ page }) => {
    await page.route(DOCUMENT_LIST, () => {}); // never answers
    await page.goto("/inbox");
    await expect(page.getByText("Loading your letters…")).toBeAttached();
    expect(await sideways(page), "the loading skeleton pushes the page sideways").toBe(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a list that didn't load says so, with Try again — never 'No letters yet'", async ({ page }) => {
    await page.route(DOCUMENT_LIST, (route) => route.fulfill({ status: 500, json: { detail: "Internal error" } }));
    await page.goto("/inbox");
    const alert = page.getByRole("alert").filter({ has: page.getByRole("heading", { name: "Couldn't load your letters" }) });
    await expect(alert).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("No letters yet")).toHaveCount(0);
    await expect(page.getByRole("searchbox", { name: "Search letters" })).toHaveCount(0);
    expect(await sideways(page)).toBe(0);
    await page.unroute(DOCUMENT_LIST);
    await alert.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("tab", { name: /^All/ })).toBeVisible();
    await expect(alert).toHaveCount(0);
  });
});
