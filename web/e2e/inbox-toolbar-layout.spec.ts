/**
 * The Inbox's toolbar, New-mail tray and load states on real pages (what jsdom can't measure):
 * every filter tab in view and the search wide enough for its words from 320 px up, the kind and
 * year pickers sharing a row on a phone and the search's row from `sm`, a lone last envelope that
 * takes its whole row, a loading skeleton that fits a phone, and a list that failed to load saying
 * so (never "No letters yet"). One year at a time (`?year=`) and, with people in the household, the
 * *For* picker on a row of its own on a phone and *File these N* fit and pass axe in both themes.
 * Runs in the "layout" project (its name ends in `layout.spec.ts`). The tray is answered here, so
 * the tests don't depend on which letters other tests have read; the household is answered here
 * too (the demo has nobody in it), so filing changes nothing on the demo.
 */
import type { Page } from "@playwright/test";
import { apiGet, expect, expectAccessible, open, setTour, test } from "./helpers";

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

interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
}

/** Where the toolbar's controls are, and the column of the list under them. */
function toolbar(page: Page) {
  return page.evaluate(() => {
    const box = (el: Element | null): Box | null => {
      if (!el) return null;
      const { left, right, top, bottom, width, height } = el.getBoundingClientRect();
      return { left, right, top, bottom, width, height };
    };
    const tabs = document.querySelector<HTMLElement>('[role="tablist"][aria-label="Filter letters"]')!;
    return {
      tabsHidden: tabs.scrollWidth - tabs.clientWidth,
      tabsRight: box(tabs.parentElement!)!.right,
      track: Math.round(box(tabs.parentElement!)!.height),
      search: box(document.getElementById("inbox-search"))!,
      kind: box(document.getElementById("inbox-kind"))!,
      year: box(document.getElementById("inbox-year"))!,
      who: box(document.getElementById("inbox-for")),
      column: box(document.querySelector('[role="tabpanel"][id^="inbox-filter-panel-"]'))!,
    };
  });
}

/** The same row: their tops within a pixel. */
const sameRow = (a: Box, b: Box) => Math.abs(a.top - b.top) <= 1;

for (const width of [320, 390, 768, 1280]) {
  test.describe(`${width} px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the toolbar fits: every filter tab in view, the search as wide as it can be", async ({ page }) => {
      await open(page, "/inbox", "Inbox");
      const m = await toolbar(page);
      expect(await sideways(page), "the page scrolls sideways").toBe(0);
      expect(m.tabsHidden, "a filter tab is cut off").toBeLessThanOrEqual(0);
      expect(m.tabsRight).toBeLessThanOrEqual(m.column.right + 0.5);
      // one height for the row's controls
      expect(m.track).toBe(Math.round(m.search.height));
      expect(Math.round(m.kind.height)).toBe(Math.round(m.search.height));
      expect(Math.round(m.year.height)).toBe(Math.round(m.search.height));
      // nobody in the demo's household: no For picker
      expect(m.who).toBeNull();
      if (width < 640) {
        // phones: the search gets the whole row; the kind and the year share the next one, half each
        expect(Math.abs(m.search.width - m.column.width)).toBeLessThanOrEqual(1);
        expect(sameRow(m.kind, m.year), "the kind and the year share a row").toBe(true);
        expect(m.kind.top).toBeGreaterThan(m.search.bottom);
        expect(Math.abs(m.kind.left - m.column.left)).toBeLessThanOrEqual(1);
        expect(Math.abs(m.year.right - m.column.right)).toBeLessThanOrEqual(1);
        expect(Math.abs(m.kind.width - m.year.width)).toBeLessThanOrEqual(1);
      } else {
        expect(m.search.width).toBeGreaterThanOrEqual(280);
        // from sm both pickers sit on the search's row
        expect(sameRow(m.kind, m.search), "the kind beside the search").toBe(true);
        expect(sameRow(m.year, m.search), "the year beside the search").toBe(true);
        expect(m.year.left).toBeGreaterThan(m.kind.right);
        expect(m.year.right).toBeLessThanOrEqual(m.column.right + 0.5);
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

// ------------------------------------------------------------------------------------------------
// One year at a time, and your household's letters
// ------------------------------------------------------------------------------------------------

const ALEX = "hhm_alex00000001";
/** A long name: the For picker and the card's button cut it, never the page. */
const ALEX_NAME = "Alexandra Maria Rivera-Hernández";

interface Letter {
  id: string;
  kind: string | null;
  status: string;
}

/**
 * A household with people, answered for `GET /api/household` (the demo's has nobody): Alex has the health insurer's
 * letter filed, and the two payment reminders are addressed to Alex, not filed yet. `PATCH` files as the API would.
 */
async function withHousehold(page: Page): Promise<{ filings: Record<string, string | null>[]; reminders: string[] }> {
  const docs = await apiGet<Letter[]>(page, "/api/documents");
  const insurer = docs.find((d) => d.kind === "health_insurance")!;
  const reminders = docs.filter((d) => d.kind === "dunning" && d.status !== "held").map((d) => d.id);
  expect(reminders.length, "the demo's payment reminders").toBeGreaterThanOrEqual(2);
  const links: Record<string, string> = { [insurer.id]: ALEX };
  const filings: Record<string, string | null>[] = [];
  const answer = () => {
    const filed = Object.fromEntries(Object.entries(links).filter(([, v]) => v !== "me"));
    return {
      members: [
        { id: ALEX, name: ALEX_NAME, signs: true, letters: Object.values(filed).filter((v) => v === ALEX).length },
        { id: "hhm_mia000000001", name: "Mia Rivera", signs: false, letters: 0 },
      ],
      filed,
      mine: [],
      suggested: Object.fromEntries(reminders.filter((id) => !(id in links)).map((id) => [id, ALEX])),
      version: "0123456789abcdef",
    };
  };
  await page.route("**/api/household", async (route) => {
    if (route.request().method() === "PATCH") {
      const { letters } = route.request().postDataJSON() as { letters: Record<string, string | null> };
      filings.push(letters);
      for (const [id, to] of Object.entries(letters)) {
        if (to == null) delete links[id];
        else links[id] = to;
      }
    }
    await route.fulfill({ json: answer() });
  });
  return { filings, reminders };
}

for (const scheme of ["light", "dark"] as const) {
  for (const width of [320, 375, 390, 768, 1280]) {
    test.describe(`${width} px, ${scheme}`, () => {
      test.use({ viewport: { width, height: 900 }, colorScheme: scheme });

      test("the year select narrows the list and fits", async ({ page }, testInfo) => {
        await open(page, "/inbox?year=2025", "Inbox");
        const select = page.getByRole("combobox", { name: "Year, by the date on the letter" });
        await expect(select).toHaveValue("2025");
        await expect(page.getByRole("status").filter({ hasText: /^Showing \d+ of \d+ letters$/ })).toHaveCount(1);
        // every month says its year while one year shows
        const months = await page.locator("section[aria-labelledby^='grp-'] h3").evaluateAll((hs) => hs.map((h) => h.textContent ?? ""));
        expect(months.length).toBeGreaterThan(0);
        for (const m of months.filter((t) => !/^(Being read|Just read|Last 7 days)/.test(t))) expect(m).toMatch(/^[A-Z][a-z]+ \d{4}/);
        await expect(page.getByRole("link", { name: "Letters for taxes" })).toHaveAttribute("href", /\/inbox\/taxes(\?year=2025)?$/);
        expect(await sideways(page), "the page scrolls sideways").toBe(0);
        const m = await toolbar(page);
        expect(m.year.right).toBeLessThanOrEqual(m.column.right + 0.5);
        await expectAccessible(page, testInfo, `inbox-year-${width}-${scheme}`);

        // a year with no letters stays a choice, and the page says why it is empty
        await open(page, "/inbox?year=2019", "Inbox");
        await expect(page.getByRole("heading", { name: "No letters dated 2019" })).toBeVisible();
        await expect(select.locator("option", { hasText: "2019 (0)" })).toHaveCount(1);
        expect(await sideways(page)).toBe(0);
      });

      test("For gets its own row on a phone and joins the pickers from sm; File these N fits and files what it lists", async ({ page }, testInfo) => {
        const { filings, reminders } = await withHousehold(page);
        await open(page, "/inbox", "Inbox");
        const who = page.getByRole("combobox", { name: "Whose letters" });
        await expect(who).toBeVisible();
        const m = await toolbar(page);
        expect(m.who).not.toBeNull();
        const w = m.who!;
        expect(Math.round(w.height)).toBe(Math.round(m.search.height));
        expect(w.right).toBeLessThanOrEqual(m.column.right + 0.5);
        if (width < 640) {
          // phones: tabs, search, kind and year, then For on a row of its own
          expect(sameRow(m.kind, m.year)).toBe(true);
          expect(w.top).toBeGreaterThan(m.kind.bottom);
          expect(Math.abs(w.width - m.column.width)).toBeLessThanOrEqual(1);
        } else {
          // from sm: For stays with the kind and the year (beside the search, or under it when they don't fit)
          expect(sameRow(w, m.kind) && sameRow(w, m.year), "For with the other pickers").toBe(true);
          expect(w.left).toBeGreaterThan(m.year.right);
          expect(m.search.width).toBeGreaterThanOrEqual(280);
        }
        // the Everyone view tags the letter filed for Alex
        await expect(page.locator("section[aria-labelledby^='grp-'] [data-person-tag]").filter({ visible: true })).toHaveCount(1);
        expect(await sideways(page), "the page scrolls sideways").toBe(0);

        await who.selectOption(ALEX);
        await expect(page).toHaveURL(new RegExp(`[?&]for=${ALEX}`));
        const card = page.getByRole("region", { name: new RegExp(`^Addressed to ${ALEX_NAME}, not filed yet`) });
        await expect(card).toBeVisible();
        const button = card.getByRole("button", { name: `File these ${reminders.length} for ${ALEX_NAME}` });
        await expect(button).toBeVisible();
        // the button's words are cut inside it, never spill out of the card or widen the page
        const fit = await button.evaluate((b) => {
          const r = b.getBoundingClientRect();
          const c = b.closest("section")!.getBoundingClientRect();
          return { inside: r.left >= c.left - 0.5 && r.right <= c.right + 0.5, height: Math.round(r.height) };
        });
        expect(fit.inside, "File these N spills out of its card").toBe(true);
        expect(fit.height).toBeGreaterThanOrEqual(24);
        expect(await sideways(page), "the page scrolls sideways").toBe(0);
        await expectAccessible(page, testInfo, `inbox-for-${width}-${scheme}`);

        // one press files exactly the letters listed; Undo puts them back as not answered
        await button.click();
        await expect.poll(() => filings.length).toBe(1);
        expect(Object.keys(filings[0]!).sort()).toEqual([...reminders].sort());
        expect(new Set(Object.values(filings[0]!))).toEqual(new Set([ALEX]));
        await expect(card).toHaveCount(0);
        const toast = page.locator("li[data-toast]").filter({ hasText: `Filed ${reminders.length} letters for ${ALEX_NAME}` });
        await expect(toast).toBeVisible();
        expect(await sideways(page), "the toast pushes the page sideways").toBe(0);
        await toast.getByRole("button", { name: "Undo" }).click();
        await expect.poll(() => filings.length).toBe(2);
        expect(Object.values(filings[1]!).every((v) => v === null)).toBe(true);
        await expect(card).toBeVisible();
      });
    });
  }
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
