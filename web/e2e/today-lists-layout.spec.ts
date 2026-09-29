/**
 * Today's lists on the real demo, where jsdom can't look (UI audit round 1, today-b): Coming-up
 * rows that give the title the width on phones and never cut it to one line, week headings whose
 * name has its space, Ideas whose "Show more" hands focus on and stays as "Show fewer", an Idea's
 * "Pay" that opens the Top-3 Pay panel, focus after "Not relevant" and Undo, Recent letters with
 * a clean heading, a row-wide toggle and a way to all letters, and 24 px "Read more" targets.
 */
import type { Locator, Page } from "@playwright/test";
import { apiPatch, expect, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const box = async (l: Locator) => (await l.boundingBox())!;
const coming = (page: Page) => page.getByRole("region", { name: /Coming up/ });
const ideas = (page: Page) => page.getByRole("region", { name: "Ideas from your secretary" });

async function noSideScroll(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
]) {
  test(`Coming up at ${width}px: the title gets the width, the amount leads the second line`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/", /Sam/);
    const rows = coming(page).locator("[data-part=coming-row]");
    expect(await rows.count()).toBeGreaterThan(3);
    for (const row of await rows.all()) {
      const r = await row.evaluate((el) => {
        const title = el.querySelector<HTMLElement>("span.line-clamp-2")!;
        const lh = parseFloat(getComputedStyle(title).lineHeight);
        const icon = el.querySelector<HTMLElement>(".inline-grid[aria-hidden=true]");
        const column = el.querySelector<HTMLElement>(":scope > .tabular-nums");
        return {
          // two lines are allowed; a cut one keeps its full text in the title attribute
          lines: Math.round(title.clientHeight / lh),
          cutWithoutTitle: title.scrollHeight > title.clientHeight + 1 && title.title !== title.textContent,
          titleWidth: title.getBoundingClientRect().width,
          iconShown: icon ? getComputedStyle(icon).display !== "none" && icon.getBoundingClientRect().width > 0 : false,
          columnShown: column ? getComputedStyle(column).display !== "none" : false,
        };
      });
      expect(r.lines).toBeLessThanOrEqual(2);
      expect(r.cutWithoutTitle).toBe(false);
      expect(r.iconShown, "kind icon on a phone").toBe(false);
      expect(r.columnShown, "amount column on a phone").toBe(false);
      expect(r.titleWidth).toBeGreaterThan(width - 150);
    }
    await expect(coming(page).locator("[data-part=meta] .tabular-nums").first()).toBeVisible();
    await noSideScroll(page);
  });
}

test("Coming up at 1280px: kind icons and an amount column; week names with their space", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/", /Sam/);
  const row = coming(page).locator("[data-part=coming-row]").filter({ has: page.locator(":scope > .tabular-nums") }).first();
  await expect(row.locator(":scope > .tabular-nums")).toBeVisible();
  await expect(row.locator(".inline-grid[aria-hidden=true]").first()).toBeVisible();
  await expect(row.locator("[data-part=meta] .tabular-nums")).toBeHidden();
  // Chrome's accessible name has the space ("This week 28 Sep – 4 Oct", not "This week28 Sep")
  await expect(coming(page).getByRole("heading", { level: 3, name: /^This week \d/ })).toBeVisible();
  await expect(coming(page).getByRole("heading", { level: 3, name: /^Week of/ })).toHaveCount(0);
});

test.describe("small phone 320×640", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("a week's total goes under its name instead of breaking the days", async ({ page }) => {
    await open(page, "/", /Sam/);
    const week = coming(page).getByRole("heading", { level: 3, name: /^This week/ });
    const days = week.locator("span");
    const total = week.locator("xpath=following-sibling::p[1]");
    const d = await box(days);
    const w = await box(week);
    // the days stay on one line
    expect(d.height).toBeLessThan(24);
    expect((await box(total)).y).toBeGreaterThanOrEqual(w.y + w.height - 1);
  });

  test("Read more on the note and on Ideas is a 24 px target", async ({ page }) => {
    await open(page, "/", /Sam/);
    for (const more of await page.getByRole("main").getByRole("button", { name: "Read more" }).all()) {
      const b = await box(more);
      expect(b.height).toBeGreaterThanOrEqual(24);
    }
  });

  test("Recent letters: the link to all letters is under the open list", async ({ page }) => {
    await open(page, "/", /Sam/);
    const section = page.getByRole("region", { name: /^Recent letters/ });
    await section.getByRole("button", { name: /^Recent letters/ }).click();
    await settle(page);
    const link = section.getByRole("link", { name: "All letters" });
    await expect(link).toHaveCount(1);
    await expect(link).toBeVisible();
    expect((await box(link)).y).toBeGreaterThan((await box(section.getByRole("list"))).y);
    await noSideScroll(page);
  });
});

test("Ideas: 'Show more' moves on to the first new Idea and becomes 'Show fewer'", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/", /Sam/);
  const section = ideas(page);
  const before = await section.getByRole("article").count();
  const more = section.getByRole("button", { name: /^Show \d+ more Ideas?$/ });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.focus();
  await page.keyboard.press("Enter");
  const firstNew = section.getByRole("article").nth(before).getByRole("heading", { level: 3 });
  await expect(firstNew).toBeFocused();
  await expect(section.getByText(/^\d+ more Ideas? shown$/)).toHaveCount(1);

  const fewer = section.getByRole("button", { name: "Show fewer Ideas" });
  await expect(fewer).toHaveAttribute("aria-expanded", "true");
  await fewer.click();
  await settle(page);
  await expect(section.getByRole("article")).toHaveCount(before);
  await expect(more).toBeFocused();
  await expect(more).toBeInViewport();
});

// UI audit round 2: the links in lines 5–6 of a cut Idea took focus unseen, and Chrome scrolled the cut
// box to them — the card then read from its third line on while "Read more" still said it was cut
for (const [width, height] of [
  [390, 844],
  [1280, 800],
]) {
  test(`${width}px: a link below an Idea's cut opens the text when it takes focus`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/", /Sam/);
    const section = ideas(page);
    const card = section.getByRole("article", { name: /student permit/ });
    if (!(await card.count())) await section.getByRole("button", { name: /^Show \d+ more Ideas?$/ }).click();
    const heading = card.getByRole("heading", { level: 3 });
    const toggle = card.getByRole("button", { name: "Read more" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    const text = page.locator(`[id="${await toggle.getAttribute("aria-controls")}"]`);
    const firstLink = text.getByRole("link").first();
    // hidden below the cut (its top is under the box's bottom), yet in the Tab order
    expect((await box(firstLink)).y).toBeGreaterThanOrEqual((await box(text)).y + (await box(text)).height - 2);

    await heading.evaluate((h) => {
      h.tabIndex = -1;
      h.focus();
    });
    await page.keyboard.press("Tab");
    await expect(firstLink).toBeFocused();
    await expect(card.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    expect(await text.evaluate((p) => ({ top: p.scrollTop, cut: p.scrollHeight > p.clientHeight + 1 }))).toEqual({ top: 0, cut: false });
    await expect(firstLink).toBeInViewport();
    await noSideScroll(page);
  });
}

test("an Idea's 'Pay' opens the same Pay panel as Top 3", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/", /Sam/);
  const card = ideas(page).getByRole("article").filter({ has: page.getByRole("button", { name: "Pay", exact: true }) }).first();
  const title = (await card.getByRole("heading", { level: 3 }).textContent())!;
  const pay = card.getByRole("button", { name: "Pay", exact: true });
  await expect(pay).toHaveAccessibleDescription(title);
  await pay.click();
  const panel = page.getByRole("dialog", { name: /^Pay: / });
  await expect(panel.getByRole("button", { name: "Mark as paid" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(pay).toBeFocused();
});

test("'Not relevant' hands focus to the Idea now in its place; Undo brings the Idea back into focus", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/", /Sam/);
  const section = ideas(page);
  // the first Idea that can be dismissed (a scam warning, first once an earlier test opened the scam
  // letter, offers "I checked — it's genuine" instead) and the one after it
  const articles = await section.getByRole("article").all();
  const at = await Promise.all(articles.map((a) => a.getByRole("button", { name: "Not relevant" }).count()));
  const index = at.findIndex((n) => n > 0);
  const [first, second] = articles.slice(index, index + 2);
  const gone = first!.getByRole("heading", { level: 3 });
  const goneId = (await gone.getAttribute("id"))!.replace(/^idea-/, "");
  const nextTitle = (await second!.getByRole("heading", { level: 3 }).textContent())!;
  try {
    await first!.getByRole("button", { name: "Not relevant" }).click();
    await expect(section.locator(`#idea-${goneId}`)).toHaveCount(0);
    await expect(section.getByRole("heading", { level: 3, name: nextTitle, exact: true })).toBeFocused();

    await page.getByRole("button", { name: "Undo" }).click();
    await expect(section.locator(`#idea-${goneId}`)).toBeFocused();
  } finally {
    // shared demo state: whatever happened above, the Idea is new again
    await apiPatch(page, `/api/suggestions/${goneId}`, { status: "new" });
  }
});

test("Recent letters: a clean heading, the whole row opens it, newest first, and a link to all letters", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/", /Sam/);
  const heading = page.getByRole("heading", { level: 2, name: /^Recent letters · \d+$/ });
  await expect(heading).toBeVisible();
  const section = page.getByRole("region", { name: /^Recent letters/ });
  const toggle = heading.getByRole("button");
  await expect(toggle).toHaveAccessibleDescription(/^Latest: /);
  // a click on the "Latest" line (not the button's own text) opens the list: the button covers the row
  const latest = section.getByText(/^Latest: /);
  await latest.scrollIntoViewIfNeeded();
  expect(await latest.evaluate((el, button) => {
    const r = el.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === button;
  }, await toggle.elementHandle())).toBe(true);
  await latest.click({ force: true });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await settle(page);
  const days = await section.getByRole("listitem").locator("time").evaluateAll((els) => els.map((e) => e.getAttribute("datetime")!));
  expect(days.length).toBeGreaterThan(1);
  expect(days).toEqual([...days].sort().reverse());
  const tb = await box(toggle);
  expect(tb.height).toBeGreaterThanOrEqual(24);
  await section.getByRole("link", { name: "All letters" }).click();
  await expect(page).toHaveURL(/\/inbox$/);
});
