/**
 * "How this was read" on the real demo (its prebuilt database has a recorded trace for every letter):
 * the tab keeps its steps inside the panel at every width — no row, bar or detail past its card,
 * nothing wider than the screen — its steps open with the keyboard, the page images make room for
 * the steps on phones, and axe finds nothing serious in the opened steps. Every step opened, a value
 * never gets squeezed into a sliver beside its label (on a narrow step the label goes above it), every
 * row that opens has something to show, and the summary's figures line up however their labels wrap.
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

/** Opens every step, stage by stage. */
async function openEverything(page: Page): Promise<void> {
  const list = page.getByRole("list", { name: "Steps of this reading" });
  for (let round = 0; round < 3; round += 1) {
    const closed = list.locator('li > button[aria-expanded="false"]');
    const n = await closed.count();
    if (!n) return;
    for (let i = n - 1; i >= 0; i -= 1) await closed.nth(i).click();
  }
}

for (const width of [320, 390, 1280, 1920]) {
  test(`How this was read at ${width}px: opened steps read well and the figures line up`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openTrace(page, /Payment Reminder|Mahnung/);
    await openEverything(page);
    const problems = await page.evaluate(() => {
      const out: string[] = [];
      const list = document.querySelector<HTMLElement>('ol[aria-label="Steps of this reading"]')!;
      // a value beside its label keeps room for a few words; else it sits under the label
      for (const dd of list.querySelectorAll<HTMLElement>("dd")) {
        const dt = dd.previousElementSibling as HTMLElement | null;
        const r = dd.getBoundingClientRect();
        const beside = dt && Math.abs(dt.getBoundingClientRect().top - r.top) < 2 && dt.getBoundingClientRect().right <= r.left;
        if (beside && r.width < 150) out.push(`"${dd.textContent?.slice(0, 30)}" is ${Math.round(r.width)} px wide beside its label`);
      }
      // a row that opens shows something when it is open
      for (const button of list.querySelectorAll<HTMLButtonElement>('button[aria-expanded="true"]')) {
        const panel = document.getElementById(button.getAttribute("aria-controls") ?? "");
        if (!panel || !panel.textContent?.trim()) out.push(`"${button.textContent?.slice(0, 30)}" opens to nothing`);
      }
      // the summary's values sit on one line per row of figures
      const values = [...document.querySelectorAll<HTMLElement>('section[aria-labelledby="trace-run-title"] dl > div > dd:first-of-type')];
      const rows = new Map<number, number[]>();
      for (const v of values) {
        const tile = v.parentElement!.getBoundingClientRect();
        const key = Math.round(tile.top);
        rows.set(key, [...(rows.get(key) ?? []), Math.round(v.getBoundingClientRect().top)]);
      }
      for (const tops of rows.values()) if (new Set(tops).size > 1) out.push(`the figures of one row sit at ${[...new Set(tops)].join(", ")} px`);
      return out;
    });
    expect(problems).toEqual([]);
    expect(await outOfBounds(page)).toEqual([]);
  });
}

test("“Read again and compare” never drops keyboard focus to the start of the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openTrace(page, /Payment Reminder|Mahnung/);
  const id = await documentId(page, /Payment Reminder|Mahnung/);
  const readAgain = page.getByRole("button", { name: "Read again and compare" });
  const reprocess = `**/api/documents/${id}/reprocess`;
  // the demo is shared by the other tests, so the letter isn't really read again: the server answers here.
  // Refused: the button was busy (Chromium moves focus off a disabled button) — focus comes back to it
  await page.route(reprocess, (route) => route.fulfill({ status: 409, json: { detail: "This letter is being read right now." } }));
  await readAgain.focus();
  await page.keyboard.press("Enter");
  await expect(readAgain).toBeFocused();
  // accepted: while the letter is read, focus waits on the reading's heading
  await page.unroute(reprocess);
  const now = new Date().toISOString();
  const job = { id: "job_e2e_focus", kind: "reprocess", status: "queued", stage: null, progress: 0, doc_id: id, attempts: 0, force: true, not_before: null, waiting_reason: null, error: null, created_at: now, updated_at: now };
  await page.route(reprocess, (route) => route.fulfill({ status: 202, json: job }));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: /^Read on/ })).toBeFocused();
});
