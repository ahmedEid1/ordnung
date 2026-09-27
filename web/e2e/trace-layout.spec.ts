/**
 * "How this was read" on the real demo (its prebuilt database has a recorded trace for every letter):
 * the tab keeps its steps inside the panel at every width — no row, bar or detail past its card,
 * nothing wider than the screen — its steps open with the keyboard, the page images make room for
 * the steps on phones, and axe finds nothing serious in the opened steps.
 */
import type { Page } from "@playwright/test";
import { documentId, expect, expectAccessible, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Every step row, bar and detail that sticks out of the list of steps (or the page is wider than the screen). */
async function outOfBounds(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    if (document.documentElement.scrollWidth > document.documentElement.clientWidth) out.push("the page scrolls sideways");
    const list = document.querySelector<HTMLElement>('ol[aria-label="Steps of this reading"]');
    if (!list) return ["no list of steps"];
    const box = list.getBoundingClientRect();
    for (const el of list.querySelectorAll<HTMLElement>("li > button, dt, dd, li > button span")) {
      const r = el.getBoundingClientRect();
      if (r.width && (r.left < box.left - 0.5 || r.right > box.right + 0.5)) out.push(`"${el.textContent?.trim().slice(0, 40)}" sticks out of the steps (${Math.round(r.left)}–${Math.round(r.right)} in ${Math.round(box.left)}–${Math.round(box.right)})`);
    }
    for (const el of document.querySelectorAll<HTMLElement>('[role="tabpanel"] h1, [role="tabpanel"] dd')) {
      if (el.scrollWidth > el.clientWidth + 1) out.push(`"${el.textContent?.trim().slice(0, 40)}" is cut off`);
    }
    return out;
  });
}

async function openTrace(page: Page, title: RegExp): Promise<void> {
  const id = await documentId(page, title);
  await open(page, `/documents/${id}?view=trace`);
  await expect(page.getByRole("tab", { name: "How this was read" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("list", { name: "Steps of this reading" })).toBeVisible();
}

for (const width of [320, 390, 768, 1280, 1920]) {
  test(`How this was read at ${width}px: every step inside its panel, opened ones too`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openTrace(page, /Payment Reminder|Mahnung/);
    const steps = page.getByRole("list", { name: "Steps of this reading" });
    for (const name of [/^Claude reads the letter/, /^Quotes checked on the page/, /^Dates computed/, /^Thread, contract & payment/]) {
      await steps.getByRole("button", { name }).first().click();
    }
    expect(await outOfBounds(page)).toEqual([]);
    // phones and tablets leave the page images out on this tab; wide screens keep them beside it
    await expect(page.getByRole("region", { name: "Letter pages" })).toBeVisible({ visible: width >= 1280 });
  });
}

test("a photo's reading shows its transcribed page; steps open with the keyboard", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openTrace(page, /Traffic fine|Verwarnung/);
  const steps = page.getByRole("list", { name: "Steps of this reading" });
  const photo = steps.getByRole("button", { name: /^Read from the photo/ });
  await photo.focus();
  await page.keyboard.press("Enter");
  await expect(photo).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("list", { name: /^Steps of “Read from the photo”/ }).getByRole("button", { name: /^Page 1 read by Claude/ })).toBeVisible();
  // the demo replays recorded answers: it says what its times are
  await expect(page.getByText(/In the demo, Claude's answers are replayed/)).toBeVisible();
  expect(await outOfBounds(page)).toEqual([]);
  await expectAccessible(page, testInfo, "trace-photo");
});
