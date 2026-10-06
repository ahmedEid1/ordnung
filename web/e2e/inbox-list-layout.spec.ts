/**
 * The Inbox letters list on real pages (what jsdom can't measure): rows fit from 320 px to
 * 1920 px — to-do chips on one line inside their column, titles on at most two lines (or one,
 * with the full title in the tooltip, in the table layout), the table only where the list is wide
 * enough — and a letter read from New mail sits on top ("Just read"), "New" until it was opened; Enter on a
 * row takes the keyboard to the letter's heading.
 * Runs in the "layout" project (its name ends in `layout.spec.ts`).
 */
import type { Page } from "@playwright/test";
import { expect, letterDetail, open, openMail, setTour, settle, shownAs, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

interface RowReport {
  title: string;
  titleAttr: string | null;
  titleLines: number;
  table: boolean;
  chips: { text: string; height: number; inside: boolean }[];
  rowOverflow: number;
}

/** Measure every letter row: its title, the layout it uses and its to-do chips. */
async function rows(page: Page): Promise<{ sideways: number; rows: RowReport[] }> {
  return page.evaluate(() => {
    const visible = (el: Element) => el.getClientRects().length > 0;
    const out: RowReport[] = [];
    for (const li of document.querySelectorAll("section[aria-labelledby^='grp-'] > ul > li")) {
      const link = li.querySelector<HTMLAnchorElement>("a[href^='/documents/']")!;
      const lineHeight = parseFloat(getComputedStyle(link).lineHeight);
      const grid = li.firstElementChild as HTMLElement;
      const cells = getComputedStyle(grid).gridTemplateColumns.split(" ").length;
      const chips = [...li.querySelectorAll<HTMLElement>("[title*='open to-do']")].filter(visible).map((chip) => {
        const r = chip.getBoundingClientRect();
        const p = chip.parentElement!.getBoundingClientRect();
        return { text: chip.textContent ?? "", height: Math.round(r.height), inside: r.left >= p.left - 0.5 && r.right <= p.right + 0.5 };
      });
      out.push({
        title: (link.textContent ?? "").replace(/‑/g, "-"),
        titleAttr: link.getAttribute("title"),
        titleLines: Math.round(link.getBoundingClientRect().height / lineHeight),
        table: cells === 5,
        chips,
        rowOverflow: Math.round(grid.scrollWidth - grid.clientWidth),
      });
    }
    return { sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth, rows: out };
  });
}

for (const width of [320, 768, 1280, 1920]) {
  test.describe(`${width} px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("every row fits: to-do chips in words on one line, titles readable in full", async ({ page }) => {
      await open(page, "/inbox", "Inbox");
      const report = await rows(page);
      expect(report.sideways, "the page scrolls sideways").toBe(0);
      expect(report.rows.length).toBeGreaterThan(10);
      // stacked rows below 56rem of list width (phones, tablets, laptops with the sidebar); a table from there
      for (const r of report.rows) expect(r.table, r.title).toBe(width >= 1280);
      for (const r of report.rows) {
        expect(r.rowOverflow, `${r.title}: the row is wider than the card`).toBeLessThanOrEqual(0);
        expect(r.titleAttr, `${r.title}: the full title in the tooltip`).toBe(r.title);
        expect(r.titleLines, r.title).toBeLessThanOrEqual(r.table ? 1 : 2);
        for (const c of r.chips) {
          expect(c.text).toMatch(/^\d+ to-dos?$/);
          expect(c.height, `${r.title}: "${c.text}" wraps`).toBeLessThanOrEqual(24);
          expect(c.inside, `${r.title}: "${c.text}" spills out of its column`).toBe(true);
        }
      }
      if (width === 768) {
        // tablets: the title gets the whole row instead of ~200 px next to four columns
        const w = await page.locator("section[aria-labelledby^='grp-'] a[href^='/documents/']").first().evaluate((a) => a.parentElement!.getBoundingClientRect().width);
        expect(w).toBeGreaterThan(450);
      }
    });
  });
}

test("headings go h1 → h2 → h3, and the month groups say how many letters", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  const levels = await page.getByRole("main").locator("h1, h2, h3, h4").evaluateAll((hs) => hs.map((h) => Number(h.tagName[1])));
  levels.forEach((level, i) => expect(level - (levels[i - 1] ?? 0), `heading ${i} skips a level`).toBeLessThanOrEqual(1));
  await expect(page.getByRole("heading", { level: 2, name: "Your letters" })).toBeAttached();
  await expect(page.getByRole("heading", { level: 3, name: /^September \(\d+ letters\)$/ })).toBeVisible();
});

test("a letter read from New mail sits on top as 'Just read', New until its page was opened", async ({ page }) => {
  const { id } = await openMail(page, "Finanzamt Musterstadt"); // ends on the letter's page (the tour may have read it already)
  // the letter's title as read (the model's words, new with every recording of the demo)
  const title = shownAs((await letterDetail(page, id)).title);
  await expect(page.getByRole("article", { name: title })).toBeVisible();
  await open(page, "/inbox", "Inbox");
  const first = page.locator("section[aria-labelledby^='grp-']").first();
  await expect(first.getByRole("heading", { level: 3 })).toHaveText(/^Just read/);
  const row = first.getByRole("listitem").filter({ has: page.getByRole("link", { name: title }) });
  await expect(row).toBeVisible();
  // its page was just shown: no "New"
  await expect(row.getByText("New", { exact: true })).toHaveCount(0);

  // in another browser (nothing seen yet) it is New
  await page.evaluate(() => localStorage.removeItem("ordnung.seen-letters"));
  await open(page, "/inbox", "Inbox");
  await expect(row.getByText("New", { exact: true }).first()).toBeVisible();
});

// UX audit U10, final check of the fix wave: Enter on a row focused the letter page's stand-in heading while the
// letter loaded; it was replaced when the letter came, and focus fell to <body>. The letter is made to come a
// moment later, as on a busy machine, so the stand-in is always shown first.
for (const width of [390, 1280]) {
  test(`at ${width} px, Enter on a row keeps the keyboard on the letter's heading once it has loaded`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/inbox", "Inbox");
    await page.route(
      (url) => /^\/api\/documents\/doc_[^/]+$/.test(url.pathname),
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 400));
        await route.fallback();
      },
    );
    const row = page.locator("section[aria-labelledby^='grp-'] a[href^='/documents/']").first();
    await row.focus();
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/documents\/doc_/);
    // the letter's own heading, not the stand-in shown while it loads
    const h1 = page.locator("main h1:not([data-loading])");
    await expect(h1).toBeFocused();
    await expect(h1).not.toHaveText("Letter");
    await page.waitForLoadState("networkidle");
    await settle(page);
    await expect(h1).toBeFocused();
  });
}
