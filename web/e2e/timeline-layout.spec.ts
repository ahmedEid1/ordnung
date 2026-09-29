/**
 * The Timeline on the real demo, where jsdom can't look (UI audit round 1, timeline): on phones
 * the list is part of the page (no scroll box that traps the thumb), starts at Today and keeps its
 * month headers to one 44 px line under the top bar; "Back to today" floats above the tab bar; from
 * 768 px the card opens with the Today divider exactly under its sticky header; a lane marker
 * highlights its own row, not another bill of the same day; the area filter judges each mark by
 * its own area; and the filters never float the switch between two rows of menus.
 */
import type { Locator, Page } from "@playwright/test";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const box = async (l: Locator) => (await l.boundingBox())!;
const list = (page: Page) => page.getByRole("region", { name: "Every date" });
const lanes = (page: Page) => page.getByRole("region", { name: "Your year ahead" });

async function noSideScroll(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
]) {
  test(`Timeline at ${width}px: the list is part of the page, starts at Today, one-line month headers`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/timeline", "Timeline");
    await noSideScroll(page);
    const l = list(page);
    // no scroll box inside the scrolling page
    expect(await l.evaluate((el) => [...el.querySelectorAll("*")].some((c) => /auto|scroll/.test(getComputedStyle(c).overflowY)))).toBe(false);
    // earlier dates fold behind one button; the Today divider comes before any date
    await expect(l.getByRole("button", { name: /^Show \d+ earlier dates$/ })).toBeVisible();
    const today = l.locator("[data-today]");
    const first = l.locator("[data-entry-id]").first();
    expect((await box(today)).y).toBeLessThan((await box(first)).y);

    // month headers: one 44 px line, never spilling below it
    for (const h of await l.getByRole("heading", { level: 3 }).filter({ hasText: /\d{4}/ }).all()) {
      const r = await h.evaluate((el) => ({ h: el.getBoundingClientRect().height, sh: el.scrollHeight }));
      expect(r.h).toBe(44);
      expect(r.sh).toBeLessThanOrEqual(44);
    }

    // scrolled into the list: the month header sticks under the top bar, and "Back to today"
    // floats above the tab bar
    await page.evaluate(() => {
      const h = document.querySelectorAll<HTMLElement>("[aria-labelledby='timeline-list-title'] h3")[1]!;
      window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY + 600);
    });
    const stuck = await l.evaluate((el) => {
      const hs = [...el.querySelectorAll<HTMLElement>("h3")].filter((h) => getComputedStyle(h).position === "sticky");
      return hs.some((h) => Math.round(h.getBoundingClientRect().top) === 56);
    });
    expect(stuck).toBe(true);
    const pill = page.getByRole("button", { name: "Back to today" });
    await expect(pill).toBeVisible();
    const tabBar = page.getByRole("navigation", { name: "Primary" });
    expect((await box(pill)).y + (await box(pill)).height).toBeLessThanOrEqual((await box(tabBar)).y);
    await pill.click();
    await expect(pill).toBeHidden();
    // the divider lands right under the sticky month header
    expect(Math.round((await box(today)).y)).toBe(56 + 44);
  });
}

test("Timeline at 1280px: the card opens at Today, exactly under its header, and doesn't trap the scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/timeline", "Timeline");
  const l = list(page);
  const scroller = l.locator(".overflow-y-auto");
  const r = await scroller.evaluate((el) => {
    const mark = el.querySelector<HTMLElement>("[data-today]")!;
    return {
      offset: mark.getBoundingClientRect().top - el.getBoundingClientRect().top,
      overscroll: getComputedStyle(el).overscrollBehaviorY,
      scrolls: el.scrollHeight > el.clientHeight,
    };
  });
  expect(r.scrolls).toBe(true);
  expect(Math.round(r.offset)).toBe(44);
  expect(r.overscroll).toBe("auto");
  // no fold on wide screens: the earlier dates are above, a scroll away
  await expect(l.getByRole("button", { name: /earlier dates/ })).toHaveCount(0);
  // the list keeps a reading width, not a 1,000 px gap between a title and its amount
  expect((await box(l)).width).toBeLessThanOrEqual(896);
});

test("a lane marker highlights its own row, not another bill of the same day", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // payments only: the health contribution stands alone in its Health lane (unfiltered, it merges with the
  // objection deadline a day earlier), while the electricity instalment is due the same day in Home
  await open(page, "/timeline?type=payment", "Timeline");
  await lanes(page)
    .getByRole("button", { name: /Monthly health and long-term care insurance contribution/ })
    .first()
    .click();
  const row = list(page).locator("li[data-entry-id]").filter({ has: page.locator("[class*='bg-marker']") });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Monthly health and long-term care insurance contribution");
});

test("the area filter judges each mark by its own area: Getting around shows its contract and its payments in its own lane", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/timeline?area=mobility", "Timeline");
  const year = lanes(page);
  await expect(year).toContainText("showing Getting around only");
  await expect(year.getByRole("listitem", { name: "Contracts", exact: true })).toBeVisible();
  await expect(year.getByRole("listitem", { name: "Getting around", exact: true })).toBeVisible();
  await expect(year.getByText(/Nothing for/)).toHaveCount(0);
  await expect(year.getByRole("listitem", { name: "Residence permit", exact: true })).toHaveCount(0);
});

for (const width of [1024, 1280]) {
  test(`filters at ${width}px: "Show past" never floats between two lines of menus`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/timeline?type=appointment", "Timeline");
    const l = list(page);
    const last = await box(l.getByRole("combobox").last());
    const sw = await box(l.getByRole("switch", { name: "Show past" }));
    // on the last line of menus, or below it
    expect(sw.y + sw.height / 2).toBeGreaterThanOrEqual(last.y);
  });
}

test("filters at 1024px: menus as wide as their words", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await open(page, "/timeline?with=Beitragsservice%20Musterstadt", "Timeline");
  const l = list(page);
  // the chosen name isn't cut: its menu is wide enough for it (no count in the closed menu)
  const party = l.getByRole("combobox", { name: "People & organisations" });
  await expect(party.locator("option:checked")).toHaveText("Beitragsservice Musterstadt");
  const fits = await party.evaluate((el: HTMLSelectElement) => {
    const probe = document.createElement("span");
    probe.style.font = getComputedStyle(el).font;
    probe.textContent = el.selectedOptions[0]!.textContent;
    document.body.append(probe);
    const w = probe.getBoundingClientRect().width;
    probe.remove();
    const cs = getComputedStyle(el);
    return w <= el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) + 1;
  });
  expect(fits).toBe(true);
});
