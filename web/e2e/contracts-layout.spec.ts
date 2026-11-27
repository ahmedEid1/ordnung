/**
 * The Contracts page on the real demo, where jsdom can't look: the
 * cost summary never cuts a figure off ("€982.3…", "Thu 8 …") and goes four across only when its
 * column has room; the cards stay inside their column at every width; the electricity contract,
 * whose end date is only the end of its minimum term, is drawn running on (not "Ends in 2 days");
 * and a contract picked in the chart takes the keyboard focus along to its card. A contract whose
 * notice period the letter didn't give gets it on its card: the form
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

// The contract is the current account: § 675h BGB gives a current account's dates once its notice is known to
// run "any time", and the toast and the card say so ("cancel any time with one month's notice", "Current
// account: …"). What its reading gives changes with every re-recording of the demo — no notice terms at all
// at first, or "any time" and no period from its letter's "jederzeit kostenfrei kündigen" (prompt 11)
// — and the law fills in the period of the other contracts read without one (the lease, the job), so the
// precondition is set up through the API the card's form uses: with the account's terms cleared, nothing is
// left for a rule to work with (no start date, no term: "as written", low confidence, no dates), and the card
// asks "Please check" and offers "Add notice period". The account is the one demo contract this is done to
// safely: terms that give no dates by themselves record no quote "confirmed by the person" (`notice_evidence`
// in `api/routes/contracts.py`), so the reading's terms go back exactly — unlike the Deutschlandticket's day of
// the month, which saving again records as the person's. That matters beyond this test: the Ask answers
// recorded for later tests replay against the ledger, and a contract that doesn't come back as it was would
// show up only as "No recorded answer" in some later file — so the test checks that it did.
test("at 320 px: the notice period entered on the card of a contract whose letter gave none", async ({ page }) => {
  const bank = await contractOf(page, "bank");
  const snapshot = asLedgerRow(bank);
  const noticeTerms = (c: Contract) => ({
    notice_value: c.notice_value,
    notice_unit: c.notice_unit,
    notice_basis: c.notice_basis,
    notice_day: c.notice_day,
    notice_before_end: c.notice_before_end,
  });
  const before = noticeTerms(bank);
  const none = { notice_value: null, notice_unit: null, notice_basis: null, notice_day: null, notice_before_end: false };
  try {
    // no notice terms at all, whatever the reading gave: cleared through the API when it gave any
    const cleared = JSON.stringify(before) === JSON.stringify(none) ? bank : await apiPatch<Contract>(page, `/api/contracts/${bank.id}`, none);
    expect(noticeTerms(cleared), "the current account has no notice terms").toEqual(none);
    expect(cleared.evidence.some((e) => e.grounding === "user"), "terms that give no dates record no quote confirmed by the person").toBe(false);
    expect(cleared.computed?.confidence, "the rules can't work out how the account ends").toBe("low");
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
    // the period is the person's now: no "Please check" for what they just
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

test("a contract opened from the Timeline takes the focus: its card, in view (focus stayed on the page's heading, scrolled away)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/timeline", "Timeline");
  const row = page.getByRole("main").locator("a[href*='contract=']").first();
  const href = (await row.getAttribute("href"))!;
  const id = new URL(href, "http://x").searchParams.get("contract")!;
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/contracts\?/);
  const card = page.locator(`[id="contract-${id}"]`);
  await expect(card).toBeFocused();
  await expect(card).toBeInViewport();
});

/**
 * Once nothing has moved for ten frames (the card, the page's height, its scroll): where the card is against the
 * room the bars really leave — below the sticky top bar while it sits at the top of the window, above the fixed
 * bars at its bottom (the phone's tab bar, and the demo's tour bar floating above it) — and what is really on top
 * just inside its top and bottom edges. The bars are found the way they are drawn: at the top, every bar drawn at
 * the window's first row (the lowest bottom counts); at the bottom, every pixel row from the window's bottom up, as
 * long as a fixed bar is hit or one was hit less than 24 px below.
 */
function cardOnceStill(card: Locator) {
  return card.evaluate(async (el) => {
    const look = () => {
      const r = el.getBoundingClientRect();
      return `${r.top.toFixed(1)} ${r.height.toFixed(1)} ${window.scrollY} ${document.documentElement.scrollHeight}`;
    };
    let last = look();
    for (let still = 0; still < 10; ) {
      await new Promise((r) => requestAnimationFrame(r));
      const now = look();
      still = now === last ? still + 1 : 0;
      last = now;
    }
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const h = window.innerHeight;
    /** The fixed or sticky box drawn at row `y` (not a backdrop: those cover half the window or more). */
    const barAt = (y: number) => {
      for (const hit of document.elementsFromPoint(x, y)) {
        for (let e: Element | null = hit; e && e !== document.body; e = e.parentElement) {
          if (!["fixed", "sticky"].includes(getComputedStyle(e).position)) continue;
          const b = e.getBoundingClientRect();
          if (b.height > 0 && b.height < h / 2) return b;
          break;
        }
      }
      return null;
    };
    // the top bar: the lowest bottom of every bar at the window's top row, as the app measures it, not the first one
    // hit (while a page loads, its 2 px progress line is drawn over the header there)
    let top = 0;
    for (const hit of document.elementsFromPoint(x, 0)) {
      for (let e: Element | null = hit; e && e !== document.body; e = e.parentElement) {
        if (!["fixed", "sticky"].includes(getComputedStyle(e).position)) continue;
        const b = e.getBoundingClientRect();
        if (b.height > 0 && b.height < h / 2 && b.top <= 0.5) top = Math.max(top, b.bottom);
        break;
      }
    }
    let bottom = h;
    for (let y = h - 1; y > top && y >= bottom - 24; y--) {
      const b = barAt(y);
      if (b && b.top < bottom) bottom = b.top;
    }
    const onTop = (y: number) => el.contains(document.elementFromPoint(x, y));
    const room = bottom - top;
    const seen = Math.max(0, Math.min(r.bottom, bottom) - Math.max(r.top, top));
    return {
      focused: document.activeElement === el,
      tall: r.height > room,
      share: seen / Math.min(r.height, room),
      topBelowBar: r.top >= top - 1,
      /** How far below the top bar (or the window's top) it starts. */
      gapAbove: r.top - top,
      bottomAboveTabs: r.bottom <= bottom + 1,
      topEdgeOnTop: onTop(r.top + 2),
      bottomEdgeOnTop: onTop(r.bottom - 2),
    };
  });
}

type Seen = Awaited<ReturnType<typeof cardOnceStill>>;

/**
 * A card the room can hold is whole in view, both edges on top; a taller one starts just below the top bar (its
 * focus ring's 4 px clear of it), so it fills the room.
 */
function expectWholeInView(seen: Seen, { tall }: { tall: boolean }) {
  expect(seen.focused, "the card has the focus").toBe(true);
  expect(seen.tall, tall ? "the card is taller than the room the bars leave" : "the card fits the room the bars leave").toBe(tall);
  expect(seen.topBelowBar, "its top is below the top bar").toBe(true);
  expect(seen.topEdgeOnTop, "just inside its top edge is the card, not a bar").toBe(true);
  if (tall) {
    expect(seen.gapAbove, "it starts just below the top bar").toBeLessThanOrEqual(8);
  } else {
    expect(seen.share, "it is whole in view").toBeGreaterThanOrEqual(0.99);
    expect(seen.bottomAboveTabs, "its bottom is above the tab bar").toBe(true);
    expect(seen.bottomEdgeOnTop, "just inside its bottom edge is the card, not a bar").toBe(true);
  }
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 800 },
    { width: 320, height: 568 },
    { width: 320, height: 256 },
  ]) {
    const size = `${viewport.width}×${viewport.height}`;
    test.describe(`${size}, motion ${reducedMotion}: a contract opened from elsewhere ends whole in view`, () => {
      test.use({ viewport, reducedMotion });

      test("the Timeline's first contract", async ({ page }) => {
        await open(page, "/timeline", "Timeline");
        const row = page.getByRole("main").locator("a[href*='contract=']").first();
        const id = new URL((await row.getAttribute("href"))!, "http://x").searchParams.get("contract")!;
        await row.focus();
        await page.keyboard.press("Enter");
        await expect(page).toHaveURL(/\/contracts\?/);
        const card = page.locator(`[id="contract-${id}"]`);
        await expect(card).toBeFocused();
        // the first is a long card (the electricity contract: about 450 px wide, 533 px on a 320 px phone): taller
        // than the room on a small phone, where only its top must show
        expectWholeInView(await cardOnceStill(card), { tall: viewport.width === 320 });
      });

      for (const how of ["its link", "its bar in the chart"] as const) {
        test(`the gym contract (mid-height) by ${how}`, async ({ page }) => {
          const gym = await contractOf(page, "gym");
          if (how === "its link") {
            await open(page, "/timeline", "Timeline");
            await page.goto(`/contracts?contract=${gym.id}`);
          } else {
            await open(page, "/contracts", "Contracts");
            const chart = page.getByRole("group", { name: "Contract terms and notice windows" });
            const bar = chart.getByRole("listitem", { name: gym.name, exact: true }).getByRole("button").first();
            await bar.focus();
            await page.keyboard.press("Enter");
          }
          const card = page.locator(`[id="contract-${gym.id}"]`);
          await expect(card).toBeFocused();
          // at 320×256 (400 % zoom) no card fits; elsewhere this one does, also at 320×568 (446 px in 448)
          expectWholeInView(await cardOnceStill(card), { tall: viewport.height === 256 });
        });
      }
    });
  }

  // A fresh demo's state: the tour not finished, its bar floating above the tab bar. The room is the bars' (56 to
  // 438 px at 320×568), and the gym (446 px) and the current account (403 px) are both taller than it: each starts
  // just below the top bar. Measured against the tab bar alone, both counted as fitting and were centred, their
  // names under the top bar and their bottoms under the tour bar.
  test.describe(`320×568 with the demo tour showing, motion ${reducedMotion}: a contract opened by its link starts below the top bar`, () => {
    test.use({ viewport: { width: 320, height: 568 }, reducedMotion });

    for (const category of ["gym", "bank"] as const) {
      test(`the ${category} contract`, async ({ page }) => {
        try {
          await setTour(page, 0);
          const contract = await contractOf(page, category);
          await open(page, "/timeline", "Timeline");
          await page.goto(`/contracts?contract=${contract.id}`);
          await expect(page.getByRole("region", { name: "Demo tour" }), "the tour bar shows").toBeVisible();
          const card = page.locator(`[id="contract-${contract.id}"]`);
          await expect(card).toBeFocused();
          expectWholeInView(await cardOnceStill(card), { tall: true });
        } finally {
          await setTour(page, null);
        }
      });
    }
  });
}

/**
 * Holds every request `matches` picks until the returned `release` is called: the order of events a slow machine
 * gives now and then, given every time.
 */
async function holdUntilReleased(page: Page, matches: (url: URL) => boolean) {
  let release!: () => void;
  const released = new Promise<void>((resolve) => (release = resolve));
  let held = 0;
  await page.route(
    (url) => matches(url),
    async (route) => {
      held++;
      await released;
      await route.continue();
    },
  );
  return { release, held: () => held };
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  // What a slower machine does now and then, done every time: something changes AFTER the card was placed (on CI, the
  // tour bar arriving late). The card is put back where it belongs (left where it was, the bank contract ended 23 px
  // down with its bottom under the tour bar; the Timeline's first contract 26 px down where the page grows above it
  // in a browser that does not keep its place).
  test.describe(`320×568, motion ${reducedMotion}: the page changes after a contract was placed`, () => {
    test.use({ viewport: { width: 320, height: 568 }, reducedMotion });

    test("the tour bar arrives after the card was placed (its code loads on its own): the bank contract starts below the top bar", async ({ page }) => {
      try {
        await setTour(page, 0);
        const bank = await contractOf(page, "bank");
        await open(page, "/timeline", "Timeline");
        const tourCode = await holdUntilReleased(page, (url) => /\/assets\/DemoTour-[^/]*\.js$/.test(url.pathname));
        await page.goto(`/contracts?contract=${bank.id}`);
        const card = page.locator(`[id="contract-${bank.id}"]`);
        await expect(card).toBeFocused();
        // placed with no tour bar: 403 px fit the room above the tab bar
        expectWholeInView(await cardOnceStill(card), { tall: false });
        expect(tourCode.held(), "the tour's code was held").toBeGreaterThan(0);
        await expect(page.getByRole("region", { name: "Demo tour" })).toHaveCount(0);
        tourCode.release();
        await expect(page.getByRole("region", { name: "Demo tour" }), "the tour bar shows").toBeVisible();
        // the room is now the bars' (56 to 438 px): too little for it, so it starts just below the top bar
        expectWholeInView(await cardOnceStill(card), { tall: true });
      } finally {
        await setTour(page, null);
      }
    });

    test("the page grows above the card after it was placed, in a browser that does not keep its place: the Timeline's first contract is put back", async ({ page }) => {
      // scroll anchoring (Chromium keeps what is in view in place when the page grows above it) is not in every
      // browser: without it the card moves down with the page
      await page.addInitScript(() => {
        addEventListener("DOMContentLoaded", () => {
          const style = document.createElement("style");
          style.textContent = "* { overflow-anchor: none !important; }";
          document.head.append(style);
        });
      });
      await open(page, "/timeline", "Timeline");
      const row = page.getByRole("main").locator("a[href*='contract=']").first();
      const id = new URL((await row.getAttribute("href"))!, "http://x").searchParams.get("contract")!;
      // the people and organisations come after the contracts: their names then fill in on the cards above it
      const people = await holdUntilReleased(page, (url) => url.pathname === "/api/parties");
      await page.goto(`/contracts?contract=${id}`);
      const card = page.locator(`[id="contract-${id}"]`);
      await expect(card).toBeFocused();
      expectWholeInView(await cardOnceStill(card), { tall: true });
      expect(people.held(), "the people's request was held").toBeGreaterThan(0);
      const before = await page.evaluate(() => document.documentElement.scrollHeight);
      people.release();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight), { message: "the page grew once the names came" }).toBeGreaterThan(before);
      expectWholeInView(await cardOnceStill(card), { tall: true });
    });
  });
}

// A scroll that comes with no wheel, touch or key (an assistive technology, a script) while the reveal's own smooth
// scroll is under way: it is the person's and wins. On a fresh demo at 320×568 the late tour bar brings a second,
// smooth reveal of the bank contract; a scroll during it was fought, and the card revealed again each time the page
// stood still (12 times in 3 s, the page pulled back to the card).
test.describe("320×568, motion on: a scroll with no input during the second reveal of a contract", () => {
  test.use({ viewport: { width: 320, height: 568 }, reducedMotion: "no-preference" });

  test("is the person's: the card is not revealed again, the page stays where it was taken", async ({ page }) => {
    // every scrollIntoView on the Contracts page counted; a frame after the second one's smooth scroll has moved the
    // page (a fixed count of frames was too few on a loaded machine), a script scrolls up 15 px a frame, three bursts
    // of 10 frames with 6 still frames between
    await page.addInitScript(() => {
      const w = window as unknown as { __siv: number; __fight: { yAtReveal: number; yAtStart: number; done: boolean; gaveUp?: true } | null };
      w.__siv = 0;
      w.__fight = null;
      const own = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (this: Element, options?: boolean | ScrollIntoViewOptions) {
        if (location.pathname === "/contracts" && ++w.__siv === 2) {
          const fight: { yAtReveal: number; yAtStart: number; done: boolean; gaveUp?: true } = { yAtReveal: window.scrollY, yAtStart: 0, done: false };
          w.__fight = fight;
          let waited = 0;
          let frame = 0;
          const step = () => {
            if (frame === 0 && window.scrollY <= fight.yAtReveal) {
              if (++waited > 120) return void Object.assign(fight, { gaveUp: true, done: true });
              return void requestAnimationFrame(step);
            }
            if (frame === 1) fight.yAtStart = window.scrollY;
            const k = frame - 1;
            if (k >= 0 && k % 16 < 10) window.scrollBy(0, -15);
            frame++;
            if (k < 16 * 2 + 10) requestAnimationFrame(step);
            else fight.done = true;
          };
          requestAnimationFrame(step);
        }
        return own.call(this, options);
      };
    });
    try {
      await setTour(page, 0);
      const bank = await contractOf(page, "bank");
      await open(page, "/timeline", "Timeline");
      const tourCode = await holdUntilReleased(page, (url) => /\/assets\/DemoTour-[^/]*\.js$/.test(url.pathname));
      await page.goto(`/contracts?contract=${bank.id}`);
      const card = page.locator(`[id="contract-${bank.id}"]`);
      await expect(card).toBeFocused();
      await cardOnceStill(card);
      expect(tourCode.held(), "the tour's code was held").toBeGreaterThan(0);
      tourCode.release();
      await expect(page.getByRole("region", { name: "Demo tour" }), "the tour bar shows").toBeVisible();
      await page.waitForFunction(() => (window as unknown as { __fight: { done: boolean } | null }).__fight?.done, null, { polling: "raf" });
      // ten still frames once the script's last scroll is done: a further reveal comes after four, and would be
      // counted (and move the page) before this ends
      await cardOnceStill(card);
      const { siv, fight, top } = await page.evaluate((id) => {
        const w = window as unknown as { __siv: number; __fight: { yAtReveal: number; yAtStart: number; gaveUp?: true } };
        return { siv: w.__siv, fight: w.__fight, top: document.getElementById(`contract-${id}`)!.getBoundingClientRect().top };
      }, bank.id);
      expect(fight.gaveUp, "the second reveal's smooth scroll moved the page within 120 frames").toBeUndefined();
      expect(fight.yAtStart, "the page had not turned back before the script scrolled").toBeGreaterThan(fight.yAtReveal);
      expect(siv, "no reveal after the second").toBe(2);
      expect(top, "the page stays where the scroll took it, not back at the card").toBeGreaterThan(300);
    } finally {
      await setTour(page, null);
    }
  });
});

// The same, going the same way as the reveal: a script scrolls on by 300 px while the second reveal is under way (a
// frame after its smooth scroll moved the page; with motion reduced, in the frame after it landed). The page went past the card, and
// once it stood still the card was revealed again and the page pulled back to it (three reveals).
for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test.describe(`320×568, motion ${reducedMotion}: a scroll with no input the same way as the second reveal of a contract`, () => {
    test.use({ viewport: { width: 320, height: 568 }, reducedMotion });

    test("is the person's: the card is not revealed again, the page stays where the scroll took it", async ({ page }) => {
      // with motion on, the script waits until the reveal's smooth scroll has moved the page, then scrolls a frame
      // later (a fixed count of frames was too few on a loaded machine: the smooth scroll had not begun); with motion
      // reduced, in the frame after the reveal landed
      await page.addInitScript((smooth) => {
        type On = { yAtReveal: number; yAtStart: number; yAfter: number } | { gaveUp: true };
        const w = window as unknown as { __siv: number; __on: On | null };
        w.__siv = 0;
        w.__on = null;
        const own = Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView = function (this: Element, options?: boolean | ScrollIntoViewOptions) {
          if (location.pathname === "/contracts" && ++w.__siv === 2) {
            const yAtReveal = window.scrollY;
            let frame = 0;
            let moved = false;
            const step = () => {
              frame++;
              if (smooth && !moved) {
                if (frame > 120) return void (w.__on = { gaveUp: true });
                moved = window.scrollY > yAtReveal;
                return void requestAnimationFrame(step);
              }
              const yAtStart = window.scrollY;
              window.scrollBy(0, 300);
              w.__on = { yAtReveal, yAtStart, yAfter: window.scrollY };
            };
            requestAnimationFrame(step);
          }
          return own.call(this, options);
        };
      }, reducedMotion === "no-preference");
      try {
        await setTour(page, 0);
        const bank = await contractOf(page, "bank");
        await open(page, "/timeline", "Timeline");
        const tourCode = await holdUntilReleased(page, (url) => /\/assets\/DemoTour-[^/]*\.js$/.test(url.pathname));
        await page.goto(`/contracts?contract=${bank.id}`);
        const card = page.locator(`[id="contract-${bank.id}"]`);
        await expect(card).toBeFocused();
        await cardOnceStill(card);
        expect(tourCode.held(), "the tour's code was held").toBeGreaterThan(0);
        tourCode.release();
        await page.waitForFunction(() => (window as unknown as { __on: unknown }).__on, null, { polling: "raf" });
        // ten still frames: a further reveal comes after four, and would be counted (and move the page) before this ends
        await cardOnceStill(card);
        const { siv, on, y, top } = await page.evaluate((id) => {
          const w = window as unknown as { __siv: number; __on: { yAtReveal: number; yAtStart: number; yAfter: number; gaveUp?: true } };
          return { siv: w.__siv, on: w.__on, y: window.scrollY, top: document.getElementById(`contract-${id}`)!.getBoundingClientRect().top };
        }, bank.id);
        expect(on.gaveUp, "the second reveal's smooth scroll moved the page within 120 frames").toBeUndefined();
        if (reducedMotion === "no-preference") {
          expect(on.yAtStart, "the page had not turned back before the script scrolled").toBeGreaterThan(on.yAtReveal);
        }
        expect(on.yAfter, "the script took the page further down").toBeGreaterThan(on.yAtStart);
        expect(siv, "no reveal after the second").toBe(2);
        expect(Math.abs(y - on.yAfter), "the page stays where the scroll took it, not pulled back to the card").toBeLessThanOrEqual(1);
        expect(top, "past the card: it went up out of view").toBeLessThan(0);
      } finally {
        await setTour(page, null);
      }
    });
  });
}

// The 2 px line drawn over the top bar while a page loads fades out for a quarter of a second after the page came. On
// CI's slower machine it was now and then still there when the card stood still, and taken for the top bar, the card
// read as 58 px below it (59.7 - 2), though it sat 4 px below the real one. Its fade slowed down, it is there every
// time. With motion reduced only: with motion on, the smooth scroll outlasted even the slowed line here.
test.describe("320×568, motion reduce: the page's progress line still over the top bar", () => {
  test.use({ viewport: { width: 320, height: 568 }, reducedMotion: "reduce" });

  test("the Timeline's first contract starts just below the top bar, the line not taken for it", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Animation.enable");
    await open(page, "/timeline", "Timeline");
    await cdp.send("Animation.setPlaybackRate", { playbackRate: 0.1 });
    const row = page.getByRole("main").locator("a[href*='contract=']").first();
    const id = new URL((await row.getAttribute("href"))!, "http://x").searchParams.get("contract")!;
    await row.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/contracts\?/);
    const card = page.locator(`[id="contract-${id}"]`);
    await expect(card).toBeFocused();
    const seen = await cardOnceStill(card);
    const line = await page.evaluate(() =>
      document.elementsFromPoint(innerWidth / 2, 0).some((e) => getComputedStyle(e).position === "fixed" && e.getBoundingClientRect().height < 8),
    );
    expect(line, "the progress line was still over the top bar").toBe(true);
    expectWholeInView(seen, { tall: true });
  });
});

test.describe("390×800, motion on: a wheel during the smooth scroll to a contract", () => {
  test.use({ viewport: { width: 390, height: 800 }, reducedMotion: "no-preference" });

  test("leaves the page where the wheel took it (the smooth scroll went on to the card, against the wheel)", async ({ page }) => {
    const gym = await contractOf(page, "gym");
    // the page's scroll every frame, and where it was when the wheel came: recorded before the app's own listener runs
    await page.addInitScript(() => {
      const w = window as unknown as { __ys: number[]; __wheel: { at: number; y: number } | null };
      w.__ys = [];
      w.__wheel = null;
      addEventListener("wheel", () => (w.__wheel ??= { at: w.__ys.length, y: window.scrollY }), { capture: true });
      const look = () => {
        w.__ys.push(window.scrollY);
        requestAnimationFrame(look);
      };
      requestAnimationFrame(look);
    });
    await open(page, "/timeline", "Timeline");
    await page.goto(`/contracts?contract=${gym.id}`);
    await page.mouse.move(195, 400);
    // the smooth scroll to the card is under way: the page moves down from one frame to the next
    await page.waitForFunction(
      () => {
        const ys = (window as unknown as { __ys: number[] }).__ys;
        return ys.length > 2 && ys.at(-1)! > ys.at(-2)! && ys.at(-1)! > 0;
      },
      null,
      { polling: "raf" },
    );
    await page.mouse.wheel(0, -300);
    const card = page.locator(`[id="contract-${gym.id}"]`);
    await cardOnceStill(card);
    const { ys, wheel } = await page.evaluate(() => {
      const w = window as unknown as { __ys: number[]; __wheel: { at: number; y: number } | null };
      return { ys: w.__ys, wheel: w.__wheel };
    });
    expect(wheel, "the wheel reached the page").not.toBeNull();
    expect(ys[wheel!.at - 1]!, "the wheel came while the page was still scrolling down to the card").toBeGreaterThan(ys[wheel!.at - 2]!);
    const after = ys.slice(wheel!.at);
    expect(Math.max(...after), "the page went no further down after the wheel").toBeLessThanOrEqual(wheel!.y + 1);
    expect(after.at(-1)!, "it ends above where the wheel came").toBeLessThan(wheel!.y);
  });
});

test.describe("390×800, motion on: a modifier key during the smooth scroll to a contract", () => {
  test.use({ viewport: { width: 390, height: 800 }, reducedMotion: "no-preference" });

  // Shift is the start of Shift+Tab, Control what quiets a screen reader as the new page is read: neither scrolls,
  // so neither may stop the scroll to the card (it stopped where it was, the card far below the window)
  for (const key of ["Shift", "Control"]) {
    test(`${key} on its own: the card still ends whole in view`, async ({ page }) => {
      const gym = await contractOf(page, "gym");
      await page.addInitScript(() => {
        const w = window as unknown as { __ys: number[]; __key: number | null };
        w.__ys = [];
        w.__key = null;
        addEventListener("keydown", () => (w.__key ??= w.__ys.length), { capture: true });
        const look = () => {
          w.__ys.push(window.scrollY);
          requestAnimationFrame(look);
        };
        requestAnimationFrame(look);
      });
      await open(page, "/timeline", "Timeline");
      await page.goto(`/contracts?contract=${gym.id}`);
      await page.waitForFunction(
        () => {
          const ys = (window as unknown as { __ys: number[] }).__ys;
          return ys.length > 2 && ys.at(-1)! > ys.at(-2)! && ys.at(-1)! > 0;
        },
        null,
        { polling: "raf" },
      );
      await page.keyboard.press(key);
      const card = page.locator(`[id="contract-${gym.id}"]`);
      const seen = await cardOnceStill(card);
      const { ys, at } = await page.evaluate(() => {
        const w = window as unknown as { __ys: number[]; __key: number | null };
        return { ys: w.__ys, at: w.__key };
      });
      expect(at, "the key reached the page").not.toBeNull();
      expect(ys[at! - 1]!, "the key came while the page was still scrolling down to the card").toBeGreaterThan(ys[at! - 2]!);
      expectWholeInView(seen, { tall: false });
    });
  }
});

// Chromium sends a finger's pointerdown before its touchstart: the watch took it for a plain press and stopped
// without stopping its smooth scroll, which went on to the card under the finger (5,700 px down for the bank
// contract at 320 px). The finger is held still and lifted only at the end, so that no tap follows.
test.describe("320×568, motion on: a finger put on the screen during the smooth scroll to a contract", () => {
  test.use({ viewport: { width: 320, height: 568 }, reducedMotion: "no-preference", hasTouch: true });

  test("stops that scroll where it is: the page goes no further than the frame the finger came in", async ({ page }) => {
    const bank = await contractOf(page, "bank");
    // the page's scroll every frame, and where it was when the finger came: recorded before the app's own listener runs
    await page.addInitScript(() => {
      const w = window as unknown as { __ys: number[]; __touch: { at: number; y: number } | null };
      w.__ys = [];
      w.__touch = null;
      addEventListener("pointerdown", () => (w.__touch ??= { at: w.__ys.length, y: window.scrollY }), { capture: true });
      const look = () => {
        w.__ys.push(window.scrollY);
        requestAnimationFrame(look);
      };
      requestAnimationFrame(look);
    });
    await open(page, "/timeline", "Timeline");
    await page.goto(`/contracts?contract=${bank.id}`);
    await page.waitForFunction(
      () => {
        const ys = (window as unknown as { __ys: number[] }).__ys;
        return ys.length > 2 && ys.at(-1)! > ys.at(-2)! && ys.at(-1)! > 0;
      },
      null,
      { polling: "raf" },
    );
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 160, y: 300 }] });
    try {
      const card = page.locator(`[id="contract-${bank.id}"]`);
      const seen = await cardOnceStill(card);
      const { ys, touch } = await page.evaluate(() => {
        const w = window as unknown as { __ys: number[]; __touch: { at: number; y: number } | null };
        return { ys: w.__ys, touch: w.__touch };
      });
      expect(touch, "the finger reached the page").not.toBeNull();
      expect(ys[touch!.at - 1]!, "the finger came while the page was still scrolling down to the card").toBeGreaterThan(ys[touch!.at - 2]!);
      // the step of the smooth scroll already under way when the finger came is kept (18 to 42 px measured)
      const next = ys[touch!.at]!;
      const after = ys.slice(touch!.at);
      expect(Math.max(...after), "the page went no further after the frame the finger came in").toBeLessThanOrEqual(next + 1);
      expect(Math.abs(after.at(-1)! - next), "and it stays there").toBeLessThanOrEqual(1);
      expect(seen.gapAbove, "the card is still far below: not brought into view after all").toBeGreaterThan(1000);
    } finally {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchCancel", touchPoints: [] });
    }
  });
});
