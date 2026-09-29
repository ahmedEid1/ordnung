/**
 * The life-lanes chart on the real demo, where jsdom can't measure (UI audit round 1, lanes):
 * "Fit all" really fits every month (nothing scrolls, captions stay inside), a bar that runs past
 * the chart keeps its whole keyboard focus ring (no mask clips it), markers never overlap and keep
 * 24 px targets, the lane labels on phones keep the next date inside the card, and the year label
 * never hides under the TODAY pill.
 */
import type { Locator, Page } from "@playwright/test";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

type Rect = { x: number; y: number; width: number; height: number };
const box = async (l: Locator): Promise<Rect> => (await l.boundingBox())!;
const inside = (a: Rect, b: Rect, slack = 0.5) =>
  a.x >= b.x - slack && a.y >= b.y - slack && a.x + a.width <= b.x + b.width + slack && a.y + a.height <= b.y + b.height + slack;
const chart = (page: Page) => page.getByTestId("lanes-scroller").first();

for (const [route, heading] of [
  ["/timeline", "Timeline"],
  ["/contracts", "Contracts"],
] as const) {
  for (const width of [768, 1280]) {
    test(`${heading} at ${width}px: “Fit all” shows every month — nothing scrolls, captions stay inside`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page, route, heading);
      const zoom = page.getByRole("radiogroup", { name: "Zoom" }).first();
      await expect(zoom.getByRole("radio", { name: /Fit all/ })).toHaveAttribute("aria-checked", "true");
      const scroller = chart(page);
      const r = await scroller.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, left: el.scrollLeft }));
      expect(r.sw).toBeLessThanOrEqual(r.cw);
      expect(r.left).toBe(0);
      // nothing to jump to, no fade over the last months
      await expect(page.getByRole("button", { name: "Jump to today" })).toHaveCount(0);
      const frame = await box(scroller);
      // every direct caption ("Send by 8 Oct") lies whole inside the chart
      const captions = await scroller.getByTestId("lanes-caption").all();
      expect(captions.length).toBeGreaterThan(0);
      for (const c of captions) expect(inside(await box(c), frame), await c.innerText()).toBe(true);
    });
  }
}

test("zoomed in, soft edges say there is more, and “Jump to today” brings today back", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/timeline", "Timeline");
  await page.getByRole("radiogroup", { name: "Zoom" }).getByRole("radio", { name: /Zoom in/ }).click();
  const scroller = chart(page);
  await expect(page.getByTestId("lanes-fade-right")).toHaveAttribute("data-shown", "true");
  await scroller.evaluate((el) => el.scrollTo({ left: el.scrollWidth }));
  await expect(page.getByTestId("lanes-fade-right")).not.toHaveAttribute("data-shown", "true");
  await expect(page.getByTestId("lanes-fade-left")).toHaveAttribute("data-shown", "true");
  await page.getByRole("button", { name: "Jump to today" }).click();
  await expect(page.getByTestId("lanes-today")).toBeInViewport();
});

test("a bar that runs past the chart keeps its whole focus ring", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/contracts", "Contracts");
  // Tab into the chart, then walk down to the open-ended lease (it fades out at both ends)
  await page.locator("[data-mark-key][tabindex='0']").first().focus();
  for (let i = 0; i < 2; i++) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Home");
  const bar = page.locator(":focus");
  await expect(bar).toHaveAttribute("aria-label", /^Open-ended\. Contract term, since .*, no end date\./);
  await expect(bar).toHaveAttribute("data-after", "true");
  const style = await bar.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { mask: cs.maskImage, outline: cs.outlineStyle, width: parseFloat(cs.outlineWidth), offset: parseFloat(cs.outlineOffset), fade: getComputedStyle(el, "::before").maskImage };
  });
  // the fade is on the paint layer, never on the button: the ring is drawn in full, inside the bar
  expect(style.mask).toBe("none");
  expect(style.fade).toContain("linear-gradient");
  expect(style.outline).toBe("solid");
  expect(style.width).toBe(2);
  expect(style.offset).toBeLessThan(0);
  expect(inside(await box(bar), await box(chart(page)))).toBe(true);
});

test("↑/↓ reach every contract's row on the Contracts chart", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/contracts", "Contracts");
  const rows = await page.getByRole("list", { name: "Lanes" }).getByRole("listitem").count();
  await page.locator("[data-mark-key][tabindex='0']").first().focus();
  const seen = new Set<string>();
  for (let i = 0; i < rows + 2; i++) {
    seen.add((await page.locator(":focus").getAttribute("data-mark-row"))!);
    await page.keyboard.press("ArrowDown");
  }
  expect(seen.size).toBeGreaterThanOrEqual(rows);
});

for (const width of [320, 390, 1280]) {
  test(`markers at ${width}px never overlap and keep 24 px targets`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/timeline", "Timeline");
    const marks = await chart(page)
      .locator(".lane-mark")
      .evaluateAll((els) => els.map((el) => ({ row: el.getAttribute("data-mark-row"), ...el.getBoundingClientRect().toJSON() })));
    expect(marks.length).toBeGreaterThan(5);
    for (const m of marks) expect(m.width).toBeGreaterThanOrEqual(24);
    for (const a of marks)
      for (const b of marks) {
        if (a === b || a.row !== b.row) continue;
        const overlap = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        expect(overlap, `marks at ${a.left} and ${b.left} overlap`).toBeLessThanOrEqual(0.5);
      }
  });
}

for (const width of [320, 390]) {
  test(`phone ${width}px: each lane's name and next date stay inside the card, the year clear of TODAY`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/contracts", "Contracts");
    const frame = await box(chart(page));
    const labels = await chart(page).getByTestId("lanes-compact-label").all();
    expect(labels.length).toBeGreaterThan(3);
    for (const label of labels) {
      await label.scrollIntoViewIfNeeded();
      const r = await box(label);
      expect(r.x).toBeGreaterThanOrEqual(frame.x - 0.5);
      expect(r.x + r.width).toBeLessThanOrEqual(frame.x + frame.width + 0.5);
      // the second line keeps its date whole: whatever truncates, it is the label before it
      const date = label.getByTestId("lanes-next-date");
      if (await date.count()) expect(inside(await box(date.first()), r)).toBe(true);
    }
    const pill = await box(page.getByTestId("lanes-today"));
    for (const year of await page.getByTestId("lanes-year").all()) {
      if (!(await year.isVisible())) continue;
      const y = await box(year);
      const text = { x: y.x + y.width - 34, width: 34 };
      const clear = text.x >= pill.x + pill.width || text.x + text.width <= pill.x;
      expect(clear, `year ${await year.innerText()} under the TODAY pill`).toBe(true);
    }
  });
}
