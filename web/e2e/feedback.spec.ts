/**
 * Feedback components on real layouts (what jsdom can't measure): the toast stack on phones,
 * tablets and laptops (one toast plus "+N" on phones, one 400 px column from tablets up, a soft
 * shadow that isn't cut into a rectangle, never over a drawer), the keyboard route to a toast, the
 * pipeline stepper's labels at the stepper's own width, and the "Why this date?" trigger.
 */
import type { Page } from "@playwright/test";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** The design-system gallery with three toasts: a success with Undo, an error and one with an action. */
async function threeToasts(page: Page) {
  await open(page, "/dev/ui", "Design system");
  for (const name of ["Toast with undo", "Error toast", "Toast with action"]) await page.getByRole("button", { name }).click();
}

const region = (page: Page) => page.getByRole("region", { name: /^Notifications/ });

async function fitsSideways(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
}

for (const width of [320, 390]) {
  test.describe(`phone ${width} px: toasts`, () => {
    test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });

    test("one toast at a time with a +N button, full width, 28 px buttons", async ({ page }) => {
      await threeToasts(page);
      const toasts = region(page).getByRole("listitem");
      await expect(toasts).toHaveCount(1);
      await expect(toasts.first()).toContainText("3 dates added to your calendar");
      const box = (await toasts.first().boundingBox())!;
      expect(Math.round(box.x)).toBe(12);
      expect(Math.round(box.x + box.width)).toBe(width - 12);
      // the column's clip box stays on the screen
      const clip = (await page.getByTestId("toaster").boundingBox())!;
      expect(clip.x).toBeGreaterThanOrEqual(0);
      expect(Math.round(clip.x + clip.width)).toBeLessThanOrEqual(width);
      for (const b of await toasts.first().getByRole("button").all()) expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(24);
      await region(page).getByRole("button", { name: "+2 more notifications" }).click();
      await expect(toasts).toHaveCount(3);
      expect(await fitsSideways(page)).toBe(true);
    });
  });
}

test.describe("between phone and tablet (700 px): toasts", () => {
  test.use({ viewport: { width: 700, height: 900 } });

  test("fill the width like on phones instead of a 380 px card stuck on the left", async ({ page }) => {
    await threeToasts(page);
    // (below 768 px only the newest shows, as on phones)
    await expect(region(page).getByRole("listitem")).toHaveCount(1);
    const toast = region(page).getByRole("listitem").first();
    const box = (await toast.boundingBox())!;
    expect(Math.round(box.x)).toBe(12);
    expect(Math.round(box.width)).toBe(700 - 24);
  });
});

test.describe("laptop 1280 px: toasts", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a right-aligned 400 px column whose clip box leaves room for the shadow", async ({ page }) => {
    await threeToasts(page);
    const toasts = region(page).getByRole("listitem");
    await expect(toasts).toHaveCount(3);
    const column = page.getByTestId("toaster");
    const clip = (await column.boundingBox())!;
    for (const t of await toasts.all()) {
      const b = (await t.boundingBox())!;
      expect(Math.round(b.width)).toBe(400);
      expect(Math.round(1280 - (b.x + b.width))).toBe(20);
      // the shadow (up to 24 px around the card) is inside the clip box, not cut off at the card:
      // 24 px to the left, and to the screen's right and bottom edges (which it never passes)
      expect(b.x - clip.x).toBeGreaterThanOrEqual(24);
      expect(Math.round(clip.x + clip.width)).toBe(1280);
      expect(Math.round(clip.y + clip.height)).toBe(800);
    }
    // the height the stack covers is published for page bottoms to pad by
    const top = (await toasts.first().boundingBox())!.y;
    const last = (await toasts.last().boundingBox())!;
    const space = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ordnung-toast-space")));
    expect(space).toBeGreaterThanOrEqual(Math.floor(last.y + last.height - top));
    expect(await fitsSideways(page)).toBe(true);
  });

  test("Alt+N reaches the newest toast from the keyboard; Escape closes it and goes back", async ({ page }) => {
    await open(page, "/dev/ui", "Design system");
    const trigger = page.getByRole("button", { name: "Toast with undo" });
    await trigger.click();
    await expect(trigger).toBeFocused();
    await page.keyboard.press("Alt+n");
    const toast = region(page).getByRole("listitem").filter({ hasText: "Marked as done" });
    await expect(toast).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(toast.getByRole("button", { name: "Undo" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(toast).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("an error toast waits for the person; toasts step behind an open drawer", async ({ page }) => {
    await open(page, "/dev/ui", "Design system");
    await page.getByRole("button", { name: "Error toast" }).click();
    const error = region(page).getByRole("listitem").filter({ hasText: "That didn't work" });
    await expect(error).toBeVisible();
    await page.getByRole("button", { name: "Open drawer" }).click();
    const drawer = page.getByRole("dialog", { name: "Right-side sheet" });
    await expect(drawer).toBeVisible();
    // the toast is behind the drawer and its scrim now: nothing of it is on top at its spot
    const b = (await error.boundingBox())!;
    const toastOnTop = await page.evaluate(([x, y]) => Boolean(document.elementFromPoint(x!, y!)?.closest('[data-testid="toaster"]')), [b.x + b.width / 2, b.y + b.height / 2]);
    expect(toastOnTop).toBe(false);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await page.waitForTimeout(6000);
    await expect(error).toBeVisible();
  });
});

/** Labels of the gallery's first stepper, and whether any two of them overlap. */
async function stepperLabels(page: Page) {
  return page
    .getByRole("list", { name: "Progress" })
    .first()
    .evaluate((ol) => {
      const rects = [...ol.querySelectorAll("[data-step-label]")].map((l) => l.getBoundingClientRect());
      const box = ol.getBoundingClientRect();
      const overlap = rects.some((r, i) => i > 0 && r.left < rects[i - 1]!.right);
      const outside = rects.some((r) => r.left < box.left - 0.5 || r.right > box.right + 0.5);
      return { count: rects.length, overlap, outside };
    });
}

test.describe("stepper labels measure the stepper's own width", () => {
  test.describe("phone 320 px", () => {
    test.use({ viewport: { width: 320, height: 640 } });
    test("fall back to one line naming the current step", async ({ page }) => {
      await open(page, "/dev/ui", "Design system");
      const labels = await stepperLabels(page);
      expect(labels.count).toBe(0);
      await expect(page.getByText(/· step \d of 5/).first()).toBeVisible();
    });
  });

  test.describe("laptop 1280 px", () => {
    test.use({ viewport: { width: 1280, height: 800 } });
    test("show every label, none running into the next", async ({ page }) => {
      await open(page, "/dev/ui", "Design system");
      const labels = await stepperLabels(page);
      expect(labels.count).toBe(5);
      expect(labels.overlap).toBe(false);
      expect(labels.outside).toBe(false);
    });
  });
});

test.describe("phone 320 px: 'Why this date?'", () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });

  test("the trigger is a 24 px target with its help icon", async ({ page }) => {
    await open(page, "/", /Sam/);
    const why = page.getByRole("main").getByRole("button", { name: /^Why this date\?/ }).first();
    const box = (await why.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(24);
    await expect(why.locator("svg")).toHaveCount(1);
  });
});
