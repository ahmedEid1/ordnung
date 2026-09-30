/**
 * The Contracts page on the real demo, where jsdom can't look (UI audit round 1, contracts): the
 * cost summary never cuts a figure off ("€982.3…", "Thu 8 …") and goes four across only when its
 * column has room; the cards stay inside their column at every width; the electricity contract,
 * whose end date is only the end of its minimum term, is drawn running on (not "Ends in 2 days");
 * and a contract picked in the chart takes the keyboard focus along to its card. A contract whose
 * notice period the letter didn't give gets it on its card (UI audit round 1, leftovers): the form
 * fits a phone, and the rules engine works the dates out from it.
 */
import type { Locator, Page } from "@playwright/test";
import type { Contract } from "@/api/types";
import { apiGet, apiPatch, contractOf, expect, open, setTour, shownAs, test } from "./helpers";

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
  // their lanes by the contracts' names as read (prompt 11 calls the electricity contract "MusterStrom Flex", no
  // longer "Stromliefervertrag"; the job is the working-student contract)
  const electricity = await contractOf(page, "energy");
  const job = await contractOf(page, "employment");
  await open(page, "/contracts", "Contracts");
  const chart = page.getByRole("group", { name: "Contract terms and notice windows" });
  const lane = (c: Contract) => chart.getByRole("listitem", { name: c.name, exact: true });
  const power = lane(electricity);
  await expect(power.getByRole("button", { name: /^Minimum term\./ })).toHaveCount(1);
  await expect(power.getByRole("button", { name: /^Fixed term\./ })).toHaveCount(0);
  await expect(power.getByRole("button", { name: /^Ends ·/ })).toHaveCount(0);
  await expect(power).toContainText("Earliest end · 2 Nov");
  await expect(lane(job).getByRole("button", { name: /^Fixed term\./ })).toHaveCount(1);
});

test("a contract picked in the chart takes the keyboard focus to its card", async ({ page }) => {
  // the liability insurance, by what it is: its lane and its card by its name as read
  const insurance = await contractOf(page, "insurance");
  await open(page, "/contracts", "Contracts");
  const chart = page.getByRole("group", { name: "Contract terms and notice windows" });
  const bar = chart.getByRole("listitem", { name: insurance.name, exact: true }).getByRole("button", { name: /^Insurance year\./ });
  await bar.focus();
  await page.keyboard.press("Enter");
  const card = page.locator("article", { has: page.getByRole("heading", { level: 3, name: shownAs(insurance.name, { whole: true }) }) });
  await expect(card).toBeFocused();
  // the focus ring shows (a keyboard pick)
  expect(await card.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
  await expect(page).toHaveURL(/contract=/);
});

/** What sticks out of the notice form at a phone's width: past its card or the screen, or a control under 24 px. */
function formFits(form: Locator) {
  return form.evaluate((f) => {
    const card = f.closest("article")!.getBoundingClientRect();
    const out = [...f.querySelectorAll<HTMLElement>("input, select, button, p")].filter((el) => {
      const r = el.getBoundingClientRect();
      return r.left < card.left || r.right > card.right;
    });
    const small = [...f.querySelectorAll<HTMLElement>("input, select, button")].filter((el) => el.getBoundingClientRect().height < 24);
    return { sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth, out: out.length, small: small.length };
  });
}

/** A contract as Ask's ledger fingerprint hashes it: every field but its timestamps (`ledger_fingerprint` in `assistant/ask.py`). */
function asLedgerRow({ created_at: _created, updated_at: _updated, ...row }: Contract) {
  return row;
}

// Prompt 11 reads the Deutschlandticket's own day ("by the 10th of a month"), so the rules no longer assume its
// notice period. The contract whose reading gave no notice terms at all is the current account (its letter's
// "jederzeit kostenfrei kündigen" is left unread, and § 675h BGB applies only to a notice known to run "any time"),
// so the rules can't work out how it ends: "Please check" and "Add notice period", as in UI audit round 1. The
// ticket's day could be cleared through the API instead, but not put back as it was: saving it again records it
// as the person's, a change to the ledger that the Ask answers recorded for later tests don't replay against —
// the account's empty terms come back exactly, and the test checks that they did: a contract that doesn't come
// back as it was would otherwise show up only as "No recorded answer" in some later file.
test("at 320 px: the notice period entered on the card of a contract whose letter gave none", async ({ page }) => {
  const bank = await contractOf(page, "bank");
  const snapshot = asLedgerRow(bank);
  const before = {
    notice_value: bank.notice_value,
    notice_unit: bank.notice_unit,
    notice_basis: bank.notice_basis,
    notice_day: bank.notice_day,
    notice_before_end: bank.notice_before_end,
  };
  expect(before, "the current account's reading gave no notice terms").toEqual({
    notice_value: null,
    notice_unit: null,
    notice_basis: null,
    notice_day: null,
    notice_before_end: false,
  });
  try {
    await page.setViewportSize({ width: 320, height: 640 });
    await open(page, "/contracts", "Contracts");
    const card = page.locator("article", { has: page.getByRole("heading", { level: 3, name: shownAs(bank.name, { whole: true }) }) });
    await expect(card.getByText("Please check")).toBeVisible();
    await card.getByRole("button", { name: /^Add notice period/ }).click();
    const form = card.getByRole("form", { name: `Notice period for ${bank.name}` });
    const value = form.getByRole("textbox", { name: "Notice period" });
    await expect(value).toBeFocused();

    // nothing typed: said at the field, and the form still fits the card and the screen
    await form.getByRole("button", { name: "Save notice period" }).click();
    await expect(form.getByText("Enter the notice period, e.g. 1 or 3")).toBeVisible();
    await expect(value).toHaveAttribute("aria-invalid", "true");
    expect(await formFits(form)).toEqual({ sideways: false, out: 0, small: 0 });

    await value.fill("1");
    const basis = form.getByRole("combobox", { name: "Can be cancelled" });
    // to the end of a month, the form asks for the contract's own day as well: it fits the phone too
    await basis.selectOption("end_of_month");
    const day = form.getByRole("textbox", { name: "Must arrive by day of the month" });
    await expect(day).toBeVisible();
    expect(await formFits(form)).toEqual({ sideways: false, out: 0, small: 0 });
    // "jederzeit", as the letter says: no day to give
    await basis.selectOption("any_time");
    await expect(day).toHaveCount(0);
    await form.getByRole("button", { name: "Save notice period" }).click();
    await expect(page.getByText("Notice period saved", { exact: true })).toBeVisible();
    // the rules engine worked the dates out (the toast says them: a current account's, § 675h BGB) and the card shows them
    await expect(
      page.getByText("You can cancel any time with one month's notice: if your cancellation arrives by Fri 2 Oct 2026, the contract ends on Mon 2 Nov 2026."),
    ).toBeVisible();
    // the period is the person's now (R2-inbox-timeline-contracts-1): no "Please check" for what they just
    // checked, and a way left to correct it, which keeps the focus — after a reload too
    await expect(card).toContainText("Current account: cancellable any time with 1 month's notice");
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
    // back as its letter left it: its notice terms, its evidence (no quote "confirmed by the person" left) and the
    // dates worked out from them. Soft: a failure above stays the one reported, and this one is added to it.
    const after = (await apiGet<Contract[]>(page, "/api/contracts")).find((c) => c.id === bank.id);
    expect.soft(after && asLedgerRow(after), "the current account is back as its letter left it (the ledger later Ask answers replay against)").toEqual(snapshot);
  }
});
