/**
 * Layout guards for the screens of the high-stakes letters, the template letters and Ask's answer
 * check, on the real demo at 320, 390 and 1280 px (review round 1 of phase 2, wave 1 — the UI audit
 * catalog has the same states, `hs-*`, `composer-templates-*`, `ask-check*`):
 *
 * - Ask: the check's note and its placeholders fit a phone, and a citation chip never starts a line
 *   after a placeholder; a stream that ends without the checked answer says so (never a blank answer
 *   announced as ready).
 * - The composer: the template tiles are a named group, and a letter opened for a chosen recipient
 *   scrolls its body, never the dialog (its title and Close stay in view).
 * - A court order calls its one date "delivered" and its advice card fits; saving the arrival or delivery day
 *   (cleared on a re-filed letter) shows its toast and moves focus to the verdict; a day before the
 *   letter keeps a visible focus outline on every Tab stop of the field; "Open the letter's card" lands
 *   on the card; the kind picker's phone sheet names itself once; a landlord's notice card keeps its first steps and its
 *   actions in view; a dismissal's law deadlines carry their countdowns; nothing scrolls sideways.
 *
 * Runs last, in a project of its own: like the audit it re-files real demo letters (PATCH kind), which
 * adds the law's to-dos to the shared demo.
 */
import type { Page, Route } from "@playwright/test";
import { apiGet, apiPatch, expect, open, setTour, settle, test } from "./helpers";

const WIDTHS = [320, 390, 1280] as const;

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function expectNoSideways(page: Page, where: string): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${where}: the page scrolls sideways`).toBeLessThanOrEqual(0);
}

interface Doc {
  id: string;
  title: string | null;
  filename: string | null;
  kind: string | null;
}

/** File a demo letter under `kind` (what the kind picker saves) and return its id. */
async function refile(page: Page, filename: RegExp, kind: string): Promise<string> {
  const docs = await apiGet<Doc[]>(page, "/api/documents");
  const doc = docs.find((d) => d.filename && filename.test(d.filename));
  expect(doc, `a letter ${filename}`).toBeTruthy();
  if (doc!.kind !== kind) await apiPatch(page, `/api/documents/${doc!.id}`, { kind });
  return doc!.id;
}

// ------------------------------------------------------------------------------------------------
// Ask: the answer check
// ------------------------------------------------------------------------------------------------

/** Answer `POST /api/ask` with these server-sent events (the stream then closes). */
async function answerAsk(page: Page, events: object[]): Promise<void> {
  await page.route(
    (url) => url.pathname === "/api/ask",
    (route: Route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 200, contentType: "text/event-stream", body: events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("") })
        : route.fallback(),
  );
}

const TRACE = [
  { type: "tool_use", name: "list_items", input: { status: "open" }, text: "Listed your open to-dos" },
  { type: "tool_result", name: "list_items", text: "12 to-dos" },
];

/** Citation chips that start a line of their own (the word or placeholder before them is on the line above). */
function orphanChips(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const chip of document.querySelectorAll("article p [aria-label^='Source'], article li [aria-label^='Source']")) {
      const block = chip.closest("p, li")!;
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
      let before: Text | null = null;
      for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
        if (chip.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING || chip.contains(n)) break;
        if (n.textContent?.trim() && !n.parentElement?.closest("[aria-label^='Source']")) before = n;
      }
      if (!before) continue;
      const text = before.textContent ?? "";
      let i = text.length - 1;
      while (i > 0 && /\s/.test(text[i]!)) i--;
      const range = document.createRange();
      range.setStart(before, i);
      range.setEnd(before, i + 1);
      // the marker that is seen (its `::before`): the link or button round it is a 24 px target, 3.5 px taller each way
      const drawnTop = chip.getBoundingClientRect().top + (parseFloat(getComputedStyle(chip, "::before").top) || 0);
      if (range.getBoundingClientRect().bottom <= drawnTop + 1) found.push(`${chip.textContent} after “${text.slice(-30)}”`);
    }
    return found;
  });
}

for (const width of WIDTHS) {
  test(`Ask at ${width}px: the check's note and placeholders fit, no chip starts a line after a placeholder`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await open(page, "/");
    const docs = await apiGet<Doc[]>(page, "/api/documents");
    const bill = docs.find((d) => /^13_nebenkosten/.test(d.filename ?? "")) ?? docs[0]!;
    const other = docs.find((d) => d.id !== bill.id)!;
    await answerAsk(page, [
      ...TRACE,
      {
        type: "done",
        text:
          `The statement asks for a back-payment of [amount only in the letter] [doc:${bill.id}]. ` +
          `Your landlord also wrote that the new prepayment starts [date left out] [doc:${other.id}], and the meter reading is due [date only in the letter] [doc:${bill.id}].`,
        note: "1 date, time or amount is marked “left out”: it isn't among the dates and amounts Ordnung saved for the linked letter, to-do or contract.",
        note_label: "Checked by Ordnung:",
        citations: [
          { type: "document", id: bill.id, label: bill.title ?? "Letter" },
          { type: "document", id: other.id, label: other.title ?? "Letter" },
        ],
        message_id: "msg_e2e_check",
      },
    ]);
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("What do I have to pay for the operating costs?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
    await settle(page);
    await expect(page.getByRole("note").filter({ hasText: "Checked by Ordnung:" })).toBeVisible();
    await expectNoSideways(page, `Ask ${width}px`);
    expect(await orphanChips(page), `citation chips alone at the start of a line at ${width} px`).toEqual([]);
  });
}

test("Ask: a stream that ends without the checked answer says so, never 'Answer ready.'", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await answerAsk(page, TRACE);
  await open(page, "/ask");
  await page.getByRole("textbox").first().fill("When is the operating-cost payment due?");
  await page.getByRole("textbox").first().press("Enter");
  await expect(page.getByRole("main").getByText("The answer stopped before Ordnung could check it", { exact: false })).toBeVisible();
  await expect(page.getByRole("main").getByRole("status").filter({ hasText: "Answer ready." })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("button", { name: "Try again" })).toBeVisible();
});

// ------------------------------------------------------------------------------------------------
// The composer's template letters
// ------------------------------------------------------------------------------------------------

for (const width of WIDTHS) {
  test(`Composer at ${width}px: a letter for a chosen recipient keeps the dialog's title and Close in view`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 800 });
    await open(page, "/");
    const parties = await apiGet<{ id: string; kind: string }[]>(page, "/api/parties");
    const landlord = parties.find((p) => p.kind === "landlord");
    expect(landlord, "the demo's landlord").toBeTruthy();
    await page.goto(`/letters?kind=deposit_return&to=${landlord!.id}`);
    const dialog = page.getByRole("dialog", { name: "New letter" });
    await expect(dialog.getByRole("heading", { name: /Who was your landlord/ })).toBeVisible();
    await page.waitForTimeout(200); // the composer scrolls to its second step after 60 ms
    await settle(page);
    // the body scrolled to the chosen recipient; the dialog itself never scrolls
    expect(await dialog.evaluate((el) => el.scrollTop)).toBe(0);
    await expect(dialog.getByRole("heading", { name: "New letter", level: 2 })).toBeInViewport();
    await expect(dialog.getByRole("button", { name: "Close" })).toBeInViewport();
    // the template tiles are one named group
    await expect(dialog.getByRole("group", { name: "More letters from templates" })).toHaveCount(1);
    await expectNoSideways(page, `composer ${width}px`);
  });
}

// ------------------------------------------------------------------------------------------------
// High-stakes letters (re-filed demo letters)
// ------------------------------------------------------------------------------------------------

test.describe.serial("high-stakes letters", () => {
  for (const width of WIDTHS) {
    test(`a court order at ${width}px: one date, "delivered"; the advice card fits`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 800 });
      await open(page, "/");
      const id = await refile(page, /^15_mahnung_techmarkt/, "court_payment_order");
      await open(page, `/documents/${id}`);
      const verdict = page.getByRole("article").first();
      await expect(verdict.locator("header")).toContainText(/Letter of .+, delivered /);
      await expect(verdict.locator("header")).not.toContainText("arrived");
      const card = page.locator(`#advice-card-${id}`);
      await expect(card).toBeVisible();
      const box = (await card.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
      await expectNoSideways(page, `court order ${width}px`);
    });
  }

  test("the kind picker's phone sheet names itself once", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, "/");
    const id = await refile(page, /^15_mahnung_techmarkt/, "court_payment_order");
    await open(page, `/documents/${id}`);
    await page.getByRole("main").getByRole("button", { name: "Change what kind of letter this is" }).click();
    const sheet = page.getByRole("dialog", { name: "What kind of letter is this?" });
    await expect(sheet).toBeVisible();
    await settle(page);
    await expect(sheet.getByText("What kind of letter is this?", { exact: true }).locator("visible=true")).toHaveCount(1);
    await expectNoSideways(page, "kind picker sheet");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
  });

  test("a landlord's notice card on a 320 px phone keeps its first steps and its actions in view", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await open(page, "/");
    const id = await refile(page, /^03_mietvertrag/, "landlord_notice");
    await open(page, `/documents/${id}`);
    const card = page.locator(`#advice-card-${id}`);
    await expect(card).toBeVisible();
    const steps = card.locator(`#advice-steps-${id} > li`);
    const more = card.getByRole("button", { name: /^Show all \d+ steps$/ });
    await expect(more).toBeVisible();
    await expect(steps).toHaveCount(3);
    const all = Number((await more.textContent())!.match(/\d+/)![0]);
    expect(all).toBeGreaterThan(3);
    await more.click();
    await expect(steps).toHaveCount(all);
    await expect(card.getByRole("button", { name: "Show fewer steps" })).toHaveAttribute("aria-expanded", "true");
    await expectNoSideways(page, "landlord's notice 320px");
  });

  // Review round 3 of phase 2: after saving the day, the question unmounted before its toast and focus ran —
  // no feedback, focus on <body>, and the page left where the form had been.
  for (const [file, kind, width] of [
    [/^07_arbeitsvertrag/, "dismissal", 390],
    [/^15_mahnung_techmarkt/, "court_payment_order", 1280],
  ] as const) {
    test(`saving the arrival day of a ${kind} at ${width}px says so and moves focus to the verdict`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 800 });
      await open(page, "/");
      const id = await refile(page, file, kind);
      const doc = await apiPatch<{ doc_date: string | null }>(page, `/api/documents/${id}`, { received_date: null });
      await open(page, `/documents/${id}`);
      const question = page.locator("#arrival-question");
      await expect(question).toBeVisible();
      await question.locator("#arrival-date").fill(doc.doc_date!);
      await question.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Thanks — dates updated")).toBeVisible({ timeout: 5_000 });
      await expect(question).toHaveCount(0);
      await expect(page.locator("#verdict-title")).toBeFocused();
      await expect(page.locator("#verdict-title")).toBeInViewport();
    });
  }

  test("an arrival day before the letter keeps a visible focus outline at each of the field's Tab stops", async ({ page }) => {
    // review round 3 of phase 2: the invalid field's red border looked the same focused or not, and while the
    // date field's own calendar button had focus the field matched neither :focus nor :focus-visible
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, "/");
    const id = await refile(page, /^07_arbeitsvertrag/, "dismissal");
    const doc = await apiPatch<{ doc_date: string | null }>(page, `/api/documents/${id}`, { received_date: null });
    await open(page, `/documents/${id}`);
    const input = page.locator("#arrival-date");
    const early = new Date(`${doc.doc_date!}T12:00:00Z`);
    early.setUTCDate(early.getUTCDate() - 3);
    await input.fill(early.toISOString().slice(0, 10));
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await input.focus();
    let stops = 0;
    while (stops < 6 && (await input.evaluate((el) => el === document.activeElement))) {
      stops += 1;
      const outline = await input.evaluate((el) => {
        const s = getComputedStyle(el);
        return `${s.outlineStyle} ${s.outlineWidth}`;
      });
      expect(outline, `Tab stop ${stops} of the date field`).toBe("solid 2px");
      await page.keyboard.press("Tab");
    }
    expect(stops, "the date field's Tab stops").toBeGreaterThanOrEqual(3);
  });

  test("'Open the letter's card' from a refused request lands on the card, its title focused", async ({ page }) => {
    // review round 3 of phase 2: it opened the letter at its top, focus on <main>, the card 1250 px below
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, "/");
    const id = await refile(page, /^07_arbeitsvertrag/, "dismissal");
    await page.goto(`/letters?kind=extension_request&doc=${id}`);
    const dialog = page.getByRole("dialog", { name: "New letter" });
    await dialog.getByRole("link", { name: "Open the letter's card" }).click();
    await expect(page).toHaveURL(new RegExp(`/documents/${id}$`));
    const title = page.locator(`#advice-${id}`);
    await expect(title).toBeFocused();
    await expect(title).toBeInViewport();
  });

  for (const width of WIDTHS) {
    // UI audit round 2: the demo's dismissal (a March letter) has law deadlines that were long past when it was
    // added — they were listed twice, as "Also: … 171 days overdue" in red and as "Still open? … probably dealt
    // with". Said once now, quietly, each row whole inside the card (the countdown of a current one: unit tests)
    test(`a dismissal at ${width}px: a law deadline past when it was added is said once, as probably dealt with`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 800 });
      await open(page, "/");
      const id = await refile(page, /^07_arbeitsvertrag/, "dismissal");
      await open(page, `/documents/${id}`);
      const verdict = page.getByRole("article").first();
      await expect(verdict.getByRole("list", { name: "Also due by law" })).toHaveCount(0);
      const rows = verdict.getByRole("list", { name: "Probably dealt with" }).getByRole("listitem");
      await expect(rows.filter({ hasText: /Kündigungsschutzklage/ })).toHaveCount(1);
      await expect(rows.filter({ hasText: /job-seeking/ })).toHaveCount(1);
      await expect(verdict.getByText(/overdue/)).toHaveCount(0);
      const vbox = (await verdict.boundingBox())!;
      for (const row of await rows.all()) {
        await expect(row.getByRole("button", { name: /^Mark .* done$/ })).toBeVisible();
        const r = (await row.boundingBox())!;
        expect(r.x + r.width, "a law deadline row sticks out of the verdict card").toBeLessThanOrEqual(vbox.x + vbox.width + 0.5);
      }
      await expectNoSideways(page, `dismissal ${width}px`);
    });
  }
});
