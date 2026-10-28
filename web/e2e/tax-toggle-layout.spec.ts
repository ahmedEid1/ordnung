/**
 * "For taxes" on a letter's page (D3) on real pages, at 320, 390 and 1280 px in light and dark: the footer's action
 * row with the toggle fits without sideways scroll, a press shows the toast and Undo puts `aria-pressed` back (and
 * the person's choice back to none), and axe finds nothing serious with the toast open. Runs against the demo in
 * the "layout" project on the TechMarkt invoice, which Claude didn't mark; every test leaves it without a choice.
 */
import type { Page } from "@playwright/test";
import { apiGet, apiPatch, expect, expectAccessible, letterId, open, setTour, settle, test } from "./helpers";

const FILE = "08_rechnung_techmarkt.pdf";
const THEMES = ["light", "dark"] as const;

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const toggle = (page: Page) => page.getByRole("main").getByRole("button", { name: "For taxes" });
const toast = (page: Page, title: string) => page.locator("li[data-toast]").filter({ hasText: title });

/** The letter's page, scrolled to its footer; the letter without a choice of the person's to start with. */
async function openLetter(page: Page): Promise<string> {
  const id = await letterId(page, FILE);
  await apiPatch(page, `/api/documents/${id}`, { tax_choice: null });
  await open(page, `/documents/${id}`);
  await toggle(page).scrollIntoViewIfNeeded();
  await settle(page);
  return id;
}

/** The person's choice as the letter's page has it. */
const choiceOf = async (page: Page, id: string) => (await apiGet<{ tax_choice: boolean | null }>(page, `/api/documents/${id}`)).tax_choice;

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

for (const width of [320, 390, 1280]) {
  test.describe(`${width} px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the footer row with For taxes fits without sideways scroll", async ({ page }) => {
      await openLetter(page);
      for (const theme of THEMES) {
        await page.emulateMedia({ colorScheme: theme });
        await settle(page);
        expect(await sideways(page), `${theme}: the page scrolls sideways`).toBe(0);
        const m = await page.evaluate(() => {
          const button = Array.from(document.querySelectorAll("main footer button")).find((b) => b.textContent?.trim() === "For taxes")!;
          const row = button.parentElement!.getBoundingClientRect();
          const main = document.querySelector("main")!.getBoundingClientRect();
          const items = Array.from(button.parentElement!.children).map((el) => el.getBoundingClientRect());
          const b = button.getBoundingClientRect();
          return {
            button: { left: b.left, right: b.right, height: b.height },
            row: { left: row.left - main.left, right: main.right - row.right },
            outside: items.filter((r) => r.left < row.left - 0.5 || r.right > row.right + 0.5).length,
            label: button.scrollWidth - button.clientWidth,
          };
        });
        expect(m.button.left, `${theme}: the toggle starts off the screen`).toBeGreaterThanOrEqual(0);
        expect(m.button.right, `${theme}: the toggle ends off the screen`).toBeLessThanOrEqual(width + 0.5);
        expect(m.button.height, `${theme}: the toggle is a 24 px target`).toBeGreaterThanOrEqual(24);
        expect(m.label, `${theme}: the toggle's label is cut off`).toBeLessThanOrEqual(0);
        expect(m.row.left, `${theme}: the action row starts outside the page`).toBeGreaterThanOrEqual(-0.5);
        expect(m.row.right, `${theme}: the action row sticks out of the page`).toBeGreaterThanOrEqual(-0.5);
        expect(m.outside, `${theme}: an action sticks out of its row`).toBe(0);
      }
      await page.emulateMedia({ colorScheme: "light" });
    });

    test("For taxes → toast → Undo puts aria-pressed back", async ({ page }) => {
      const id = await openLetter(page);
      try {
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
        await toggle(page).click();
        const marked = toast(page, "Marked for taxes");
        await expect(marked).toBeVisible();
        await expect(marked).toContainText("It's on your Tax year 2026 page.");
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByRole("main").getByText("You marked this letter for taxes.")).toBeVisible();
        await expect(page.getByRole("main").getByRole("link", { name: "All letters for taxes from 2026" })).toHaveAttribute("href", "/inbox/taxes?year=2026");
        expect(await choiceOf(page, id)).toBe(true);
        expect(await sideways(page), "the page scrolls sideways with the toast open").toBe(0);

        await marked.getByRole("button", { name: "Undo" }).click();
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
        await expect(marked).toBeHidden();
        await expect(page.getByRole("main").getByText("You marked this letter for taxes.")).toBeHidden();
        // exactly as before: no choice of the person's, Claude's mark (none) counts again
        expect(await choiceOf(page, id)).toBeNull();
        await expect(toggle(page)).toBeFocused();
      } finally {
        await apiPatch(page, `/api/documents/${id}`, { tax_choice: null });
      }
    });

    test("a keyboard press keeps focus on For taxes while it saves and after", async ({ page }) => {
      const id = await openLetter(page);
      try {
        await toggle(page).focus();
        await page.keyboard.press("Enter");
        await expect(toast(page, "Marked for taxes")).toBeVisible();
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");
        await expect(toggle(page)).toBeFocused();
        await page.keyboard.press("Space");
        await expect(toast(page, "Not marked for taxes")).toBeVisible();
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
        await expect(toggle(page)).toBeFocused();
        expect(await choiceOf(page, id)).toBe(false);
      } finally {
        await apiPatch(page, `/api/documents/${id}`, { tax_choice: null });
      }
    });

    test("axe: no serious or critical violations on the letter page with the toast open", async ({ page }, testInfo) => {
      const id = await openLetter(page);
      try {
        await toggle(page).click();
        const marked = toast(page, "Marked for taxes");
        await expect(marked).toBeVisible();
        // the pointer on the toast keeps it open while it is scanned
        await marked.hover();
        for (const theme of THEMES) {
          await page.emulateMedia({ colorScheme: theme });
          await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /^(?![\s\S]*\bdark\b)/);
          await expect(marked).toBeVisible();
          await expectAccessible(page, testInfo, `tax-toggle-${width}-${theme}`);
        }
        await page.emulateMedia({ colorScheme: "light" });
        await marked.getByRole("button", { name: "Undo" }).click();
        await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
      } finally {
        await apiPatch(page, `/api/documents/${id}`, { tax_choice: null });
      }
    });
  });
}
