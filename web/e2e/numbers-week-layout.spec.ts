/**
 * My numbers and the weekly session on the real demo, where jsdom can't look: nothing sticks out of
 * its card or past the screen at 320–1920 px, hidden numbers become readable with Show, the step list
 * or the stepper fits its width, moving to a step puts the focus on its heading clear of the top bar,
 * and Today's prompt has real targets. Nothing here changes the shared demo: "Finish" is answered by
 * the test.
 */
import type { Page } from "@playwright/test";
import { expect, expectAccessible, expectNoRawEnums, open, setTour, test } from "./helpers";

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

for (const width of [320, 390, 768, 1280, 1920]) {
  test(`My numbers at ${width}px: inside the screen, hidden until Show`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/numbers", "My numbers");
    expect(await outOfBounds(page)).toEqual([]);
    // every tab inside the tab row, none cut (a phone shows "You", "Cases", "Orgs")
    const tabs = page.getByRole("tablist", { name: "Which numbers" });
    const row = (await tabs.boundingBox())!;
    for (const tab of await tabs.getByRole("tab").all()) {
      const box = (await tab.boundingBox())!;
      expect(box.x, "tab starts inside the row").toBeGreaterThanOrEqual(row.x - 0.5);
      expect(box.x + box.width, "tab ends inside the row").toBeLessThanOrEqual(row.x + row.width + 0.5);
    }
    const show = page.getByRole("main").getByRole("button", { name: "Show Tax ID (Steuer-ID)" });
    await expect(show).not.toHaveAttribute("aria-pressed");
    const box = await show.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(24);
    await show.click();
    await expect(page.getByRole("main").getByText("57 216 480 393")).toBeVisible();
    expect(await outOfBounds(page)).toEqual([]);

    await open(page, "/numbers?tab=organisations", "My numbers");
    expect(await outOfBounds(page)).toEqual([]);
    await open(page, "/numbers?tab=cases", "My numbers");
    expect(await outOfBounds(page)).toEqual([]);
  });

  test(`This week at ${width}px: the steps fit, every step inside the screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/week", "This week");
    const list = page.getByRole("navigation", { name: "Steps of the session" });
    if (width >= 1280) await expect(list).toBeVisible();
    else await expect(page.getByRole("list", { name: "Steps of the session" })).toBeVisible();
    for (const step of ["new", "check", "pay", "post", "waiting", "decide", "file"]) {
      await open(page, `/week?step=${step}`, "This week");
      expect(await outOfBounds(page), step).toEqual([]);
    }
  });
}

test("a long German label wraps inside its card at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  const label = "Rentenversicherungsnummer/Sozialversicherungsnummer/Versicherungsnummer";
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
  // UI audit R2-party-numbers-8: it broke mid-word ("…/Sozialvers" · "icherungsnummer…"); now after its slashes
  const lines = await title.evaluate((p) =>
    Array.from(p.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").length > 1)
      .map((n) => {
        const range = document.createRange();
        range.selectNodeContents(n);
        return new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top))).size;
      }),
  );
  expect(lines, "each word of the label on one line").toEqual([1, 1, 1]);
});

test("the cards of a row are as tall as each other, their letter lines level", async ({ page }) => {
  // UI audit R2-party-numbers-7: short cards left gaps, the "Last letter" lines never lined up
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

test("Next takes the focus to the new step's heading, clear of the top bar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/week", "This week");
  await page.getByRole("button", { name: /^Next: / }).click();
  const heading = page.getByRole("heading", { level: 2, name: "Compare with the letter" });
  await expect(heading).toBeFocused();
  const bar = await page.getByRole("banner").boundingBox();
  const h = await heading.boundingBox();
  expect(h!.y).toBeGreaterThanOrEqual(bar!.y + bar!.height - 1);
  await expect(page).toHaveURL(/step=check/);
});

test("Finish ends with “All clear until …” (answered by the test: the demo keeps no session)", async ({ page }) => {
  await page.route("**/api/week/done", async (route) => {
    const week = await (await page.request.get("/api/week")).json();
    await route.fulfill({ json: { ...week, due: false } });
  });
  await open(page, "/week?step=file", "This week");
  await page.getByRole("button", { name: /^Finish/ }).click();
  const done = page.getByRole("heading", { level: 2, name: /^All clear until / });
  await expect(done).toBeFocused();
  await expect(page.getByRole("link", { name: "Back to Today" })).toBeVisible();
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

test("My numbers and This week: no raw enums, no serious axe findings", async ({ page }, testInfo) => {
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
