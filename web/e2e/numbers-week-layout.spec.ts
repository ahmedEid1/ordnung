/**
 * My numbers and the weekly review on the real demo, where jsdom can't look: nothing sticks out of
 * its card or past the screen at 320–1920 px, hidden numbers become readable with Show, the step list
 * or the stepper fits its width (a name under every dot on a phone), moving to a step puts the focus
 * on its heading with its "Step n of m" (and a phone's stepper) clear of the top bar, the amounts of
 * Pay this week line up, and Today's prompt has real targets. Nothing here changes the shared demo:
 * "Finish" is answered by the test.
 */
import type { Page } from "@playwright/test";
import { expect, expectAccessible, expectNoRawEnums, open, READ, setTheme, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/**
 * No horizontal page scroll, and every card's content inside its card — also text that runs past its
 * own box (a block's box does not grow with a word too long for it, so its scroll width is compared;
 * text cut on purpose with an ellipsis is fine).
 */
async function outOfBounds(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth) out.push(`the page scrolls sideways (${root.scrollWidth} > ${root.clientWidth})`);
    for (const card of document.querySelectorAll<HTMLElement>("main .card")) {
      const r = card.getBoundingClientRect();
      if (r.right > root.clientWidth + 0.5) out.push(`card "${card.textContent?.slice(0, 30)}" ends past the screen`);
      for (const el of card.querySelectorAll<HTMLElement>("p, h2, h3, button, a")) {
        const e = el.getBoundingClientRect();
        if (e.width && (e.right > r.right + 0.5 || e.left < r.left - 0.5)) out.push(`"${el.textContent?.slice(0, 30)}" sticks out of its card`);
        const style = getComputedStyle(el);
        const cut = style.textOverflow === "ellipsis" || style.overflowX === "hidden" || style.overflowX === "clip";
        if (el.clientWidth && !cut && el.scrollWidth > el.clientWidth + 1) out.push(`"${el.textContent?.slice(0, 30)}" runs past its box`);
      }
    }
    return out;
  });
}

const WIDTHS = [320, 390, 768, 1280, 1920];

/** Each page (and step) opened once, at the first width, then resized in place: the views re-measure on resize. */
async function atEachWidth(page: Page, check: (width: number) => Promise<void>): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 800 });
    await settle(page);
    await check(width);
  }
}

test("My numbers at 320, 390, 768, 1280 and 1920 px: inside the screen, hidden until Show", async ({ page }) => {
  await page.setViewportSize({ width: WIDTHS[0]!, height: 800 });
  await open(page, "/numbers", "My numbers");
  const tabs = page.getByRole("tablist", { name: "Which numbers" });
  const show = page.getByRole("main").getByRole("button", { name: "Show Tax ID (Steuer-ID)" });
  const number = page.getByRole("main").getByText("57 216 480 354");
  await atEachWidth(page, async (width) => {
    expect(await outOfBounds(page), `${width} px`).toEqual([]);
    // every tab inside the tab row, none cut (a phone shows "You", "Cases", "Orgs")
    const row = (await tabs.boundingBox())!;
    for (const tab of await tabs.getByRole("tab").all()) {
      const box = (await tab.boundingBox())!;
      expect(box.x, `tab starts inside the row at ${width} px`).toBeGreaterThanOrEqual(row.x - 0.5);
      expect(box.x + box.width, `tab ends inside the row at ${width} px`).toBeLessThanOrEqual(row.x + row.width + 0.5);
    }
    await expect(show).not.toHaveAttribute("aria-pressed");
    const box = await show.boundingBox();
    expect(box!.height, `${width} px`).toBeGreaterThanOrEqual(24);
    await show.click();
    await expect(number).toBeVisible();
    expect(await outOfBounds(page), `${width} px, shown`).toEqual([]);
    // hidden again, so the next width starts as a page load would
    await page.getByRole("main").getByRole("button", { name: "Hide Tax ID (Steuer-ID)" }).click();
    await expect(number).toBeHidden();
  });

  await open(page, "/numbers?tab=organisations", "My numbers");
  await atEachWidth(page, async (width) => expect(await outOfBounds(page), `organisations at ${width} px`).toEqual([]));
  await open(page, "/numbers?tab=cases", "My numbers");
  await atEachWidth(page, async (width) => expect(await outOfBounds(page), `cases at ${width} px`).toEqual([]));
});

test("Weekly review at 320, 390, 768, 1280 and 1920 px: the steps fit, every step inside the screen", async ({ page }) => {
  await page.setViewportSize({ width: WIDTHS[0]!, height: 800 });
  await open(page, "/week", "Weekly review");
  const list = page.getByRole("navigation", { name: "Steps of the review" });
  await atEachWidth(page, async (width) => {
    if (width >= 1280) await expect(list).toBeVisible();
    else {
      // the phone's way between the steps: a name under every dot, none over another, all on the screen
      const stepper = page.getByRole("list", { name: "Steps of the review" });
      await expect(stepper).toBeVisible();
      const dots = await stepper.getByRole("button").count();
      const labels = stepper.locator("..").locator("[data-step-label]");
      await expect(labels).toHaveCount(dots);
      const boxes = await labels.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON() as DOMRect));
      for (const [i, a] of boxes.entries()) {
        expect(a.left, `label ${i} inside the screen at ${width} px`).toBeGreaterThanOrEqual(0);
        expect(a.right, `label ${i} inside the screen at ${width} px`).toBeLessThanOrEqual(width);
        for (const b of boxes.slice(i + 1)) {
          const apart = a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top;
          expect(apart, `labels ${i} and a later one don't overlap at ${width} px`).toBe(true);
        }
      }
    }
  });
  for (const step of ["new", "check", "pay", "post", "waiting", "decide", "file"]) {
    await page.setViewportSize({ width: WIDTHS[0]!, height: 800 });
    await open(page, `/week?step=${step}`, "Weekly review");
    await atEachWidth(page, async (width) => {
      expect(await outOfBounds(page), `${step} at ${width} px`).toEqual([]);
      // the days on the steps are computed: "Not legal advice" under them, at every width
      await expect(page.getByRole("main").getByText(/Not legal advice\./), `${step} at ${width} px`).toBeVisible();
    });
  }
});

// The label as the letter prints it, and with the soft hyphens a PDF's text often carries: they are
// break points like German hyphenation's, so the guard holds on a browser without German hyphenation too.
const LONG_LABELS = {
  plain: "Rentenversicherungsnummer/Sozialversicherungsnummer/Versicherungsnummer",
  "soft hyphens": "Renten\u00adversicherungs\u00adnummer/Sozial\u00adversicherungs\u00adnummer/Versi\u00adcherungs\u00adnummer",
};

for (const [variant, label] of Object.entries(LONG_LABELS)) {
  test(`a long German label wraps inside its card at 320px (${variant})`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.route("**/api/numbers", async (route) => {
      const numbers = await (await route.fetch()).json();
      const [first, ...rest] = numbers.organisations;
      const [n, ...more] = first.numbers;
      await route.fulfill({ json: { ...numbers, organisations: [{ ...first, numbers: [{ ...n, kind: "other", name: "Your number", label }, ...more] }, ...rest] } });
    });
    await open(page, "/numbers?tab=organisations", "My numbers");
    const title = page.getByRole("main").getByText(label, { exact: true });
    await expect(title).toBeVisible();
    expect(await outOfBounds(page)).toEqual([]);
    // it broke mid-word ("…/Sozialvers" · "icherungsnummer…"); now after its
    // slashes. Hyphenation fills a line greedily ("…nummer/Versi-" · "cherungsnummer" with Chrome's German
    // dictionary), so each part that fits a line must still be on one.
    const lines = await title.evaluate((p) => {
      const texts: Text[] = [];
      const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if ((walker.currentNode.textContent ?? "").length > 1) texts.push(walker.currentNode as Text);
      return texts.map((n) => {
        const range = document.createRange();
        range.selectNodeContents(n);
        return new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top))).size;
      });
    });
    expect(lines, "each word of the label on one line").toEqual([1, 1, 1]);
  });
}

test("the cards of a row are as tall as each other, their letter lines level", async ({ page }) => {
  // short cards left gaps, the "Last letter" lines never lined up
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const tab of ["organisations", "cases"]) {
    await open(page, `/numbers?tab=${tab}`, "My numbers");
    const rows = await page
      .getByRole("main")
      .getByRole("list")
      .first()
      .evaluate((ul) => {
        const byRow = new Map<number, number[]>();
        for (const li of Array.from(ul.children)) {
          const card = li.firstElementChild!.getBoundingClientRect();
          const top = Math.round(card.top);
          byRow.set(top, [...(byRow.get(top) ?? []), Math.round(card.height)]);
        }
        return Array.from(byRow.values());
      });
    expect(rows.length, tab).toBeGreaterThan(0);
    for (const heights of rows) expect(new Set(heights).size, `${tab}: ${heights.join(", ")}`).toBe(1);
  }
});

for (const width of [390, 1280]) {
  test(`Next and Back at ${width}px: the focus on the new step's heading, its “Step n of m” clear of the top bar`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    // The review opens on its first step, and that isn't always "New": the demo's library
    // notice must be returned by Fri 2 Oct, so its send-by day is the demo's today (Mon 28 Sep) and "Act now"
    // (one row) comes first. Start on the step before "Compare with the letter" — New, with every letter of
    // the week — as the review did before
    await open(page, "/week?step=new", "Weekly review");
    await expect(page.getByRole("heading", { level: 2, name: /^New (in the last \d+ days|since your last review)$/ })).toBeVisible();
    const bar = (await page.getByRole("banner").boundingBox())!;
    const below = bar.y + bar.height - 1;
    // from the foot of a long step, as someone who read it to the end
    await page.getByRole("button", { name: /^Next: / }).scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: /^Next: / }).click();
    const heading = page.getByRole("heading", { level: 2, name: "Compare with the letter" });
    await expect(heading).toBeFocused();
    await expect(page).toHaveURL(/step=check/);
    const clear = async (what: string) => {
      await settle(page);
      const eyebrow = (await page.getByRole("main").getByText(/^Step \d of \d$/).boundingBox())!;
      expect(eyebrow.y, `${what}: "Step n of m" below the top bar`).toBeGreaterThanOrEqual(below);
      expect((await heading.boundingBox())!.y, `${what}: the heading below the top bar`).toBeGreaterThanOrEqual(below);
      if (width < 800) {
        const stepper = (await page.getByRole("list", { name: "Steps of the review" }).boundingBox())!;
        expect(stepper.y, `${what}: the stepper below the top bar`).toBeGreaterThanOrEqual(below);
      }
    };
    await clear("Next");
    await page.getByRole("button", { name: /^Next: / }).scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: /^Next: / }).click();
    await page.getByRole("button", { name: "Back" }).scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: "Back" }).click();
    await expect(heading).toBeFocused();
    await clear("Back");
  });
}

test("Pay this week: the amounts end in one column, with a Pay button or without", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/week?step=pay", "Weekly review");
  const step = page.getByRole("region", { name: "Pay this week" });
  const rights = await step.locator("li span.tabular-nums").evaluateAll((els) =>
    els.filter((el) => el.closest("li")?.querySelector("[data-pay-slot], button[aria-label^='Pay:']")).map((el) => Math.round(el.getBoundingClientRect().right)),
  );
  expect(rights.length, "amounts in the step").toBeGreaterThan(1);
  expect(new Set(rights).size, `amount right edges ${rights.join(", ")}`).toBe(1);
});

test("Finish ends with “All clear …” (answered by the test: the demo keeps no review)", async ({ page }) => {
  await page.route("**/api/week/done", async (route) => {
    const week = await (await page.request.get("/api/week", READ)).json();
    await route.fulfill({ json: { ...week, due: false } });
  });
  await open(page, "/week?step=file", "Weekly review");
  await page.getByRole("button", { name: /^Finish/ }).click();
  const done = page.getByRole("heading", { level: 2, name: /^(All clear|One thing|\d+ things?)/ });
  await expect(done).toBeFocused();
  await expect(page.getByRole("link", { name: "Back to Today" })).toBeVisible();
});

/** `WeeklySession.backup` as the server sends it once a backup is due (the demo never sends one: answered by the test). */
const DUE_BACKUP = {
  last_backup_at: "2026-08-12T09:00:00Z",
  last_backup_restored: false,
  sync_saved_at: null,
  sync_standing_by: false,
  days: 47,
  due: true,
  due_after_days: 30,
};

// one walk to the ending per width; what the light and dark tests each measured, measured in both themes (switched in place)
test.describe("the ending's backup reminder in light and dark", () => {
  for (const width of [320, 1280]) {
    test(`at ${width}px it follows the ending, wraps on screen and links to Settings`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 800 });
      await page.route("**/api/week/done", async (route) => {
        const week = await (await page.request.get("/api/week", READ)).json();
        await route.fulfill({ json: { ...week, due: false, backup: DUE_BACKUP } });
      });
      await open(page, "/week?step=file", "Weekly review");
      await page.getByRole("button", { name: /^Finish/ }).click();
      const done = page.getByRole("heading", { level: 2, name: /^(All clear|One thing|\d+ things?)/ });
      await expect(done).toBeFocused();
      const main = page.getByRole("main");
      const text = main.getByText("Your last backup was 47 days ago (Wed 12 Aug). A new one keeps your letters if this computer breaks or is lost.");
      const link = main.getByRole("link", { name: "Back up now" });
      await expect(link).toHaveAttribute("href", "/settings?section=data");
      // after the ending in the page's order: the keyboard reaches it from the focused heading
      expect(await done.evaluate((h, l) => Boolean(h.compareDocumentPosition(l!) & Node.DOCUMENT_POSITION_FOLLOWING), await link.elementHandle())).toBe(true);
      for (const scheme of ["light", "dark"] as const) {
        await setTheme(page, scheme);
        await expect(main.getByText("Time for a backup")).toBeVisible();
        await expect(text).toBeVisible();
        const box = (await link.boundingBox())!;
        expect(box.height, scheme).toBeGreaterThanOrEqual(24);
        const callout = (await text.boundingBox())!;
        expect(callout.x, scheme).toBeGreaterThanOrEqual(0);
        expect(callout.x + callout.width, scheme).toBeLessThanOrEqual(width + 0.5);
        expect(await outOfBounds(page), scheme).toEqual([]);
        await expectAccessible(page, testInfo, `week-backup-${scheme}-${width}`);
      }
      await setTheme(page, "light");
    });
  }
});

test("Today suggests the weekly review once, with real targets", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const prompt = page.getByRole("region", { name: "Time for your weekly review" });
  await expect(prompt).toBeVisible();
  for (const target of [prompt.getByRole("link", { name: "Start" }), prompt.getByRole("button", { name: "Not now" })]) {
    const box = await target.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(24);
    expect(box!.width).toBeGreaterThanOrEqual(24);
  }
  await prompt.getByRole("link", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/week$/);
});

test("My numbers and the weekly review: no raw enums, no serious axe findings", async ({ page }, testInfo) => {
  for (const [path, name] of [
    ["/numbers", "numbers"],
    ["/numbers?tab=organisations", "numbers-organisations"],
    ["/week", "week"],
    ["/week?step=pay", "week-pay"],
  ] as const) {
    await open(page, path);
    await expectNoRawEnums(page, path);
    await expectAccessible(page, testInfo, name);
  }
});
