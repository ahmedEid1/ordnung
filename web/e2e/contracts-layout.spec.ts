/**
 * The Contracts page on the real demo, where jsdom can't look (UI audit round 1, contracts): the
 * cost summary never cuts a figure off ("€982.3…", "Thu 8 …") and goes four across only when its
 * column has room; the cards stay inside their column at every width; the electricity contract,
 * whose end date is only the end of its minimum term, is drawn running on (not "Ends in 2 days");
 * and a contract picked in the chart takes the keyboard focus along to its card. A contract whose
 * notice period the letter didn't give gets it on its card (UI audit round 1, leftovers): the form
 * fits a phone, and the rules engine works the dates out from it.
 */
import type { Page } from "@playwright/test";
import { apiGet, apiPatch, expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Everything that sticks out: a card past its list, a summary figure past its cell or cut off. */
async function outOfBounds(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const list = document.querySelector<HTMLElement>('ul[aria-label$=" contracts"]')!;
    const lr = list.getBoundingClientRect();
    for (const li of list.children) {
      const r = li.getBoundingClientRect();
      if (r.left < lr.left - 0.5 || r.right > lr.right + 0.5) out.push(`card "${li.textContent?.slice(0, 30)}" is ${Math.round(r.width)} px in a ${Math.round(lr.width)} px list`);
      for (const el of li.querySelectorAll<HTMLElement>("dd, dt, h3, footer > *")) {
        const e = el.getBoundingClientRect();
        if (e.right > r.right + 0.5) out.push(`"${el.textContent?.slice(0, 30)}" sticks out of its card`);
      }
    }
    for (const v of document.querySelectorAll<HTMLElement>("dl [data-part=value]")) {
      const cell = v.closest("dl > div")!.getBoundingClientRect();
      if (v.scrollWidth > v.clientWidth + 0.5 || v.getBoundingClientRect().right > cell.right + 0.5) out.push(`figure "${v.textContent}" is cut off`);
    }
    return out;
  });
}

/** How many rows the four figures of the cost summary take. */
const summaryRows = (page: Page) =>
  page.evaluate(() => new Set([...document.querySelectorAll("dl [data-part=value]")].map((v) => Math.round(v.getBoundingClientRect().top))).size);

for (const [width, rows] of [
  [320, 2],
  [390, 2],
  [1100, 2],
  [1280, 1],
] as const) {
  test(`Contracts at ${width}px: no figure cut off, cards inside their column`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/contracts", "Contracts");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    expect(await outOfBounds(page)).toEqual([]);
    // four across only when the content column has room for four (not at 1100 beside the sidebar)
    expect(await summaryRows(page)).toBe(rows);
  });
}

test("the electricity contract runs on after its minimum term; the fixed-term job ends", async ({ page }) => {
  await open(page, "/contracts", "Contracts");
  const chart = page.getByRole("group", { name: "Contract terms and notice windows" });
  const lane = (name: RegExp) => chart.getByRole("listitem", { name });
  const power = lane(/^Stromliefervertrag/);
  await expect(power.getByRole("button", { name: /^Minimum term\./ })).toHaveCount(1);
  await expect(power.getByRole("button", { name: /^Fixed term\./ })).toHaveCount(0);
  await expect(power.getByRole("button", { name: /^Ends ·/ })).toHaveCount(0);
  await expect(power).toContainText("Earliest end · 2 Nov");
  await expect(lane(/^Befristeter Arbeitsvertrag/).getByRole("button", { name: /^Fixed term\./ })).toHaveCount(1);
});

test("a contract picked in the chart takes the keyboard focus to its card", async ({ page }) => {
  await open(page, "/contracts", "Contracts");
  const chart = page.getByRole("group", { name: "Contract terms and notice windows" });
  const bar = chart.getByRole("button", { name: /^Insurance year\./ });
  await bar.focus();
  await page.keyboard.press("Enter");
  const card = page.locator("article", { has: page.getByRole("heading", { level: 3, name: /^Privat-Haftpflichtversicherung/ }) });
  await expect(card).toBeFocused();
  // the focus ring shows (a keyboard pick)
  expect(await card.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
  await expect(page).toHaveURL(/contract=/);
});

interface ContractTerms {
  id: string;
  name: string;
  notice_value: number | null;
  notice_unit: string | null;
  notice_basis: string | null;
}

test("at 320 px: the notice period entered on the card of a contract we couldn't work out", async ({ page }) => {
  const contracts = await apiGet<ContractTerms[]>(page, "/api/contracts");
  const bank = contracts.find((c) => c.name.startsWith("Girokonto"))!;
  const before = { notice_value: bank.notice_value, notice_unit: bank.notice_unit, notice_basis: bank.notice_basis };
  try {
    await page.setViewportSize({ width: 320, height: 640 });
    await open(page, "/contracts", "Contracts");
    const card = page.locator("article", { has: page.getByRole("heading", { level: 3, name: /^Girokonto/ }) });
    await card.getByRole("button", { name: /^Add notice period/ }).click();
    const form = card.getByRole("form", { name: /^Notice period for Girokonto/ });
    const value = form.getByRole("textbox", { name: "Notice period" });
    await expect(value).toBeFocused();

    // nothing typed: said at the field, and the form still fits the card and the screen
    await form.getByRole("button", { name: "Save notice period" }).click();
    await expect(form.getByText("Enter the notice period, e.g. 1 or 3")).toBeVisible();
    await expect(value).toHaveAttribute("aria-invalid", "true");
    const fits = await form.evaluate((f) => {
      const card = f.closest("article")!.getBoundingClientRect();
      const out = [...f.querySelectorAll<HTMLElement>("input, select, button, p")].filter((el) => {
        const r = el.getBoundingClientRect();
        return r.left < card.left || r.right > card.right;
      });
      const small = [...f.querySelectorAll<HTMLElement>("input, select, button")].filter((el) => el.getBoundingClientRect().height < 24);
      return { sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth, out: out.length, small: small.length };
    });
    expect(fits).toEqual({ sideways: false, out: 0, small: 0 });

    await value.fill("1");
    await form.getByRole("combobox", { name: "Can be cancelled" }).selectOption("end_of_month");
    await form.getByRole("button", { name: "Save notice period" }).click();
    await expect(page.getByText("Notice period saved", { exact: true })).toBeVisible();
    // the rules engine worked the dates out (the toast says them) and the card shows them
    await expect(page.getByText("To leave on Sat 31 Oct 2026, your notice must arrive by Wed 30 Sep 2026; send it by Mon 28 Sep.")).toBeVisible();
    // the period is the person's now (R2-inbox-timeline-contracts-1): no "Please check" for what they just
    // checked, and a way left to correct it, which keeps the focus — after a reload too
    await expect(card).toContainText("As you entered it: 1 month's notice to the end of a month");
    await expect(card).toContainText("Notice must arrive by");
    await expect(card.getByText("Please check")).toHaveCount(0);
    const change = card.getByRole("button", { name: /^Change notice period/ });
    await expect(change).toBeFocused();

    // Undo: the missing terms are back, and with them "Please check"
    await page.getByRole("button", { name: /^Undo/ }).click();
    await expect(card.getByRole("button", { name: /^Add notice period/ })).toBeVisible();
    await expect(card.getByText("Please check")).toBeVisible();

    await apiPatch(page, `/api/contracts/${bank.id}`, { notice_value: 3, notice_unit: "months", notice_basis: "end_of_month" });
    await page.reload();
    await expect(card.getByRole("button", { name: /^Change notice period/ })).toBeVisible();
    await expect(card.getByText("Please check")).toHaveCount(0);
  } finally {
    await apiPatch(page, `/api/contracts/${bank.id}`, before);
  }
});
