/**
 * Today on the real demo, where jsdom can't look (UI audit round 1, today-a): the Pay panel keeps
 * "Mark as paid" in view on short screens and shows the whole IBAN on small phones, the Top-3 rank
 * sits in the card's corner, Coming up gets the page's width until there is room for the side
 * cards (then both start level, Ideas below in two columns), and focus has somewhere to go when a
 * paid card leaves and when Undo brings it back.
 */
import type { Locator, Page } from "@playwright/test";
import { apiPatch, expect, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const top3 = (page: Page) => page.getByRole("region", { name: "Top 3 this week" });
const box = async (l: Locator) => (await l.boundingBox())!;

async function openPay(page: Page): Promise<Locator> {
  await open(page, "/", /Sam/);
  await top3(page).getByRole("button", { name: /^Pay: / }).first().click();
  const panel = page.getByRole("dialog", { name: /^Pay: / });
  await expect(panel.getByRole("button", { name: "Mark as paid" })).toBeVisible();
  await settle(page);
  return panel;
}

/** Is the whole element on screen and the top-most thing at its centre (not scrolled away or covered)? */
async function reachable(l: Locator): Promise<boolean> {
  return l.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return r.top >= 0 && r.bottom <= innerHeight && Boolean(hit && el.contains(hit));
  });
}

for (const [width, height] of [
  [1280, 520],
  [1024, 480],
  [640, 360],
]) {
  test(`Pay panel at ${width}×${height}: its actions stay in view while the details scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const panel = await openPay(page);
    const markPaid = panel.getByRole("button", { name: "Mark as paid" });
    expect(await reachable(markPaid)).toBe(true);
    expect(await reachable(panel.getByRole("button", { name: "Open letter" }))).toBe(true);
    // scrolled to the end, the footer is still the last thing and still reachable
    await panel.evaluate((el) => {
      const scroller = el.matches("[data-sheet]") ? el.querySelector("[data-popover-body]")! : el;
      scroller.scrollTop = scroller.scrollHeight;
    });
    expect(await reachable(markPaid)).toBe(true);
  });
}

test.describe("small phone 320×640", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("the Pay sheet shows the whole IBAN and reference, with icon-only copy buttons", async ({ page }) => {
    const panel = await openPay(page);
    for (const label of ["IBAN", "Reference"]) {
      const value = panel.getByRole("term").filter({ hasText: new RegExp(`^${label}$`) }).locator("xpath=following-sibling::dd[1]");
      const fits = await value.evaluate((el) => el.scrollWidth <= el.clientWidth && getComputedStyle(el).textOverflow !== "ellipsis");
      expect(fits, `${label} is shown in full`).toBe(true);
      const copy = panel.getByRole("button", { name: `Copy ${label}` });
      const b = await box(copy);
      expect(b.width).toBeGreaterThanOrEqual(24);
      expect(b.height).toBeGreaterThanOrEqual(24);
      await expect(copy.getByText("Copy")).toBeHidden();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test("the Top-3 rank sits inside its card, clear of the date", async ({ page }) => {
    await open(page, "/", /Sam/);
    for (const card of await top3(page).getByRole("article").all()) {
      const c = await box(card);
      const rank = await box(card.locator("[data-part=rank]"));
      const pill = await box(card.locator("time").first());
      expect(rank.x + rank.width).toBeLessThanOrEqual(c.x + c.width - 8);
      expect(pill.x + pill.width).toBeLessThanOrEqual(rank.x);
    }
  });
});

test.describe("Coming up and the side cards", () => {
  test("share the row only when both fit; start level; Ideas below in two columns", async ({ page }) => {
    // an open sidebar at 1024 leaves too little room: one column, the side cards under Coming up
    await page.setViewportSize({ width: 1024, height: 900 });
    await open(page, "/", /Sam/);
    const coming = page.getByRole("region", { name: /Coming up/ });
    const check = page.getByRole("region", { name: /Please check/ });
    const ideas = page.getByRole("region", { name: "Ideas from your secretary" });
    let comingBox = await box(coming);
    let checkBox = await box(check);
    expect(checkBox.y).toBeGreaterThan(comingBox.y + comingBox.height - 1);
    expect(Math.abs(checkBox.width - comingBox.width)).toBeLessThan(2);

    await page.setViewportSize({ width: 1440, height: 900 });
    await settle(page);
    comingBox = await box(coming);
    checkBox = await box(check);
    expect(checkBox.x).toBeGreaterThan(comingBox.x + comingBox.width);
    // the side column starts level with Coming up's card (under its header)
    const comingCard = await box(coming.locator(":scope > .card, :scope > p.card").first());
    expect(Math.abs(checkBox.y - comingCard.y)).toBeLessThanOrEqual(2);
    // Ideas: below both, full width, two columns
    const ideasBox = await box(ideas);
    expect(ideasBox.y).toBeGreaterThan(comingBox.y + comingBox.height);
    expect(ideasBox.width).toBeGreaterThan(comingBox.width + checkBox.width);
    const [first, second] = await ideas.getByRole("article").all();
    const a = await box(first!);
    const b = await box(second!);
    expect(Math.abs(a.y - b.y)).toBeLessThan(2);
    expect(b.x).toBeGreaterThan(a.x + a.width);
  });
});

test("Mark as paid moves focus to the card now in its place; Undo brings the card back into focus", async ({ page }) => {
  const panel = await openPay(page);
  const name = (await panel.getAttribute("aria-label"))!.replace(/^Pay: /, "");
  const paid = top3(page).getByRole("heading", { level: 3 }).filter({ hasText: name });
  const id = await paid.evaluate((h) => h.id.replace(/^top-item:/, ""));
  try {
    await panel.getByRole("button", { name: "Mark as paid" }).click();
    await expect(paid).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.activeElement?.matches("[data-top-heading]") ?? false)).toBe(true);
    await expect(top3(page).getByRole("heading", { level: 3 }).first()).toBeFocused();

    await page.getByRole("button", { name: "Undo" }).click();
    await expect(paid).toBeFocused();
  } finally {
    // shared demo state: whatever happened above, the to-do is open again
    await apiPatch(page, `/api/items/${id}`, { status: "open" });
  }
});
