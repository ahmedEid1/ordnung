/**
 * The Letters list and the New-letter composer on the real demo, where jsdom can't measure (UI audit
 * round 1, letters-b): beside "How letters work" (1024–1280 px) the rows kept only their icon and
 * status — the title squeezed out by a fixed status column; phones lost the date and the row's focus
 * ring was clipped to a line; the composer's lists scrolled inside the scrolling dialog, a contract
 * chosen by a link out of view; picking a kind on a small phone changed nothing visible. Round 2: on a
 * 320×640 phone the pinned description and a tall footer left under half the sheet for the choices, and
 * contracts that can be cancelled any month counted down in red to their "send by".
 */
import type { Page } from "@playwright/test";
import { protectRefs } from "@/lib/glue";
import { apiGet, contractOf, expect, open, settle, setTour, test } from "./helpers";

interface DraftSummary {
  id: string;
  kind: string;
  status: string;
}

/** At least one letter in the list (the phone contract's cancellation, drafted here if the demo has none). */
async function ensureDraft(page: Page): Promise<void> {
  const drafts = await apiGet<DraftSummary[]>(page, "/api/drafts");
  if (drafts.length) return;
  const phone = await contractOf(page, "mobile");
  const res = await page.request.post("/api/drafts", { data: { kind: "cancellation", contract_id: phone.id, language: "de" }, headers: { "X-Ordnung-Client": "web" } });
  expect(res.ok()).toBe(true);
}

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
  await ensureDraft(page);
});

for (const width of [1024, 1280, 1440]) {
  test(`Letters at ${width}px: every row keeps its title, whole`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/letters", "Letters");
    expect(await noSideScroll(page)).toBe(true);
    const rows = page.locator("[data-draft-row]");
    await expect(rows.first()).toBeVisible();
    for (const row of await rows.all()) {
      const title = row.locator("span[title]").first();
      // before: 0 px at 1024 and ~220 px (cut) at 1280
      expect((await title.boundingBox())!.width).toBeGreaterThanOrEqual(220);
      expect(await title.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
      // the date sits beside the status or under the subject — never outside the row
      const meta = (await row.locator("[data-draft-meta]").boundingBox())!;
      const box = (await row.boundingBox())!;
      expect(meta.x + meta.width).toBeLessThanOrEqual(box.x + box.width + 0.5);
    }
  });
}

/** "Waiting for" entries as the Letters page counts them (the demo has sent nothing yet, so nothing waits). */
async function waitingEntries(page: Page, counts: Record<"overdue" | "answered" | "waiting", number>): Promise<void> {
  const json = Object.entries(counts).flatMap(([status, n]) =>
    Array.from({ length: n }, (_, i) => ({ id: `w_${status}_${i}`, status, source: "letter", title: `${status} ${i}`, about: "", note: "", since: null, expected_by: null })),
  );
  await page.route("**/api/waiting", (route) => route.fulfill({ json }));
}

// the words take room: shown where the buttons have a row of their own (400–639 px) and beside the title from
// 1024 px — what may be answered beside what is overdue only from 1280 px, so the description keeps its room
for (const [width, overdueWords, answeredWords] of [
  [320, false, false],
  [400, true, true],
  [639, true, true],
  [768, false, false],
  [1024, true, false],
  [1280, true, true],
] as const) {
  test(`Letters at ${width}px: "Waiting for" says what is overdue and what may be answered, inside the screen`, async ({ page }) => {
    await waitingEntries(page, { overdue: 12, answered: 10, waiting: 8 });
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/letters", "Letters");
    const link = page.getByRole("link", { name: /^Waiting for/ });
    await expect(link).toHaveAccessibleName(/^Waiting for\s*30\s*,\s*12 overdue\s*,\s*10 may be answered$/);
    expect(await noSideScroll(page)).toBe(true);
    const box = (await link.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width - 16 + 0.5);
    expect(box.height).toBeLessThanOrEqual(44); // one line
    const shown = async (selector: string) => ((await link.locator(selector).boundingBox())?.width ?? 0) > 8;
    expect(await shown("[data-overdue]")).toBe(overdueWords);
    expect(await shown("[data-answered]")).toBe(answeredWords);
    // the dot is red while something is overdue: chase first
    await expect(link.locator("[data-overdue-dot]")).toHaveCount(1);
    if (width >= 1024) {
      const description = page.getByRole("main").locator("header p").first();
      expect((await description.boundingBox())!.width).toBeGreaterThanOrEqual(260);
    }
  });
}

test("Letters at 1024px: with nothing overdue, what may be answered is said in green words and a green dot", async ({ page }) => {
  await waitingEntries(page, { overdue: 0, answered: 1, waiting: 2 });
  await page.setViewportSize({ width: 1024, height: 800 });
  await open(page, "/letters", "Letters");
  const link = page.getByRole("link", { name: /^Waiting for/ });
  await expect(link).toHaveAccessibleName(/^Waiting for\s*3\s*,\s*1 may be answered$/);
  expect(((await link.locator("[data-answered]").boundingBox())?.width ?? 0) > 8).toBe(true);
  await expect(link.locator("[data-answered-dot]")).toHaveCount(1);
  await expect(link.locator("[data-overdue], [data-overdue-dot]")).toHaveCount(0);
  expect(await noSideScroll(page)).toBe(true);
});

for (const width of [320, 390]) {
  test(`Letters at ${width}px: each row says its status and date; the focus ring is drawn whole inside the row`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/letters", "Letters");
    expect(await noSideScroll(page)).toBe(true);
    const row = page.locator("[data-draft-row]").first();
    const meta = row.locator("[data-draft-meta]");
    await expect(meta).toBeVisible();
    await expect(meta).toContainText(/Send by|Started|by /);
    // keyboard focus: the outline sits inside the row, so the card (which clips its corners) can't cut it
    await row.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(row).toBeFocused();
    const outline = await row.evaluate((el) => {
      const s = getComputedStyle(el);
      return { style: s.outlineStyle, width: s.outlineWidth, offset: s.outlineOffset };
    });
    expect(outline).toEqual({ style: "solid", width: "2px", offset: "-2px" });
  });
}

/** The demo's employment contract (the fifth by send-by date: below the fold of the old inner list). */
async function jobContract(page: Page): Promise<string> {
  const contracts = await apiGet<{ id: string; category: string }[]>(page, "/api/contracts");
  const job = contracts.find((c) => c.category === "employment");
  expect(job, "the demo's job contract").toBeTruthy();
  return job!.id;
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
  [1280, 800],
] as const) {
  test(`composer at ${width}px: a contract chosen by a link is first and in view; the dialog's body is the only scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/", undefined);
    const id = await jobContract(page);
    await page.goto(`/letters?kind=cancellation&contract=${id}`);
    const dialog = page.getByRole("dialog", { name: "New letter" });
    await expect(dialog.getByRole("heading", { name: "Step 2: Which contract?" })).toBeVisible();
    await page.waitForTimeout(200); // the composer scrolls to its second step after 60 ms
    await settle(page);
    const chosen = dialog.locator("label", { has: page.locator(`input[value="${id}"]`) });
    await expect(chosen.getByRole("radio")).toBeChecked();
    await expect(chosen).toBeInViewport();
    // no scrolling box inside the scrolling dialog
    const scrollers = await dialog.evaluate(
      (root) =>
        [root, ...root.querySelectorAll("*")].filter((el) => {
          const y = getComputedStyle(el).overflowY;
          return (y === "auto" || y === "scroll") && el.scrollHeight > el.clientHeight + 1;
        }).length,
    );
    expect(scrollers).toBe(1);
    // every send-by date is shown (on phones as a line under the name)
    const group = dialog.getByRole("radiogroup", { name: /Which contract/ });
    const dates = group.locator("time[data-urgency]");
    for (const t of await dates.all()) {
      if (!(await t.isVisible())) continue;
      const r = (await t.boundingBox())!;
      const g = (await group.boundingBox())!;
      expect(r.x + r.width).toBeLessThanOrEqual(g.x + g.width + 0.5);
    }
    expect(await group.locator("time[data-urgency]:visible").count()).toBeGreaterThan(0);
    expect(await noSideScroll(page)).toBe(true);
  });
}

test("composer at 320px: picking a kind brings its second step into view", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await open(page, "/", undefined);
  await page.goto("/letters?new=1");
  const dialog = page.getByRole("dialog", { name: "New letter" });
  await expect(dialog.getByRole("heading", { name: "Step 1: What do you want to do?" })).toBeVisible();
  await dialog.locator("label", { hasText: "Cancel a contract" }).click();
  await expect(dialog.getByRole("heading", { name: "Step 2: Which contract?" })).toBeInViewport();
});

test("composer: an objection that isn't possible names the letter, apart from the decisions that are", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/", undefined);
  const docs = await apiGet<{ id: string; title: string | null; kind: string | null; status: string; direction: string; remedy: { type: string } | null }[]>(page, "/api/documents");
  // an invoice or a reminder: no instructions on how to object (never a court order or a landlord's notice,
  // which the law gives an objection)
  const plain = docs.find(
    (d) => ["invoice", "dunning", "appointment"].includes(d.kind ?? "") && d.status === "processed" && d.direction === "incoming" && (!d.remedy || d.remedy.type === "none"),
  );
  expect(plain, "a letter without instructions on how to object").toBeTruthy();
  await page.goto(`/letters?kind=objection&doc=${plain!.id}`);
  const dialog = page.getByRole("dialog", { name: "New letter" });
  const chosen = dialog.locator("[data-chosen-letter]");
  // (a reference in the name is kept whole: its hyphens are non-breaking)
  await expect(chosen).toContainText(protectRefs(plain!.title!));
  await expect(dialog.getByRole("radiogroup", { name: "Or choose a decision you can object to" })).toBeVisible();
  const write = dialog.getByRole("button", { name: "Write the letter" });
  await expect(write).toBeDisabled();
  await expect(write).toHaveAccessibleDescription(/You can't object to this letter/);
});

test("composer at 320×640: the choices keep most of the sheet; Cancel and 'Write the letter' side by side, 44 px tall", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await open(page, "/", undefined);
  const docs = await apiGet<{ id: string; kind: string | null; status: string }[]>(page, "/api/documents");
  const dunning = docs.find((d) => d.kind === "dunning" && d.status === "processed");
  expect(dunning, "a payment reminder").toBeTruthy();
  await page.goto(`/letters?kind=payment_plan&doc=${dunning!.id}`);
  const dialog = page.getByRole("dialog", { name: "New letter" });
  await expect(dialog.getByRole("heading", { name: /Step 2:/ })).toBeVisible();
  await settle(page);
  const m = await dialog.evaluate((d) => {
    const body = [...d.children].find((k) => getComputedStyle(k).overflowY === "auto")!;
    return { sheet: d.getBoundingClientRect().height, body: body.getBoundingClientRect().height };
  });
  // before: 302 of 589 px (51 %)
  expect(m.body / m.sheet).toBeGreaterThanOrEqual(0.6);
  const cancel = (await dialog.getByRole("button", { name: "Cancel" }).boundingBox())!;
  const write = (await dialog.getByRole("button", { name: /Write the letter/ }).boundingBox())!;
  expect(Math.abs(cancel.y - write.y)).toBeLessThan(1);
  expect(cancel.x + cancel.width).toBeLessThanOrEqual(write.x);
  for (const b of [cancel, write]) expect(b.height).toBeGreaterThanOrEqual(44);
  // the reason is said above them, and travels with the disabled button
  await expect(dialog.getByRole("button", { name: /Write the letter/ })).toHaveAccessibleDescription(/^Still needed: /);
  // the dialog keeps its description (in the form on a phone, and for screen readers)
  await expect(dialog).toHaveAccessibleDescription(/fixed templates/);
  await expect(dialog.locator("[data-composer-about]")).toBeAttached();
  expect(await noSideScroll(page)).toBe(true);
});

test("composer: a contract you can cancel any month never counts down; one with a term says 'Send by'", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/", undefined);
  interface C {
    id: string;
    status: string;
    computed: { cancel_by: string | null; next_renewal: string | null; current_term_end: string | null } | null;
  }
  const contracts = await apiGet<C[]>(page, "/api/contracts");
  // isRollingContract (features/contracts/model.ts): the demo's rent and statutory health insurance
  const rolling = contracts.filter((c) => c.status === "active" && c.computed?.cancel_by && !c.computed.next_renewal && !c.computed.current_term_end);
  expect(rolling.length, "a contract you can cancel any month").toBeGreaterThan(0);
  await page.goto("/letters?kind=cancellation");
  const dialog = page.getByRole("dialog", { name: "New letter" });
  const group = dialog.getByRole("radiogroup", { name: /Which contract/ });
  await expect(group).toBeVisible();
  const all = dialog.getByRole("button", { name: /^Show all \d+ contracts$/ });
  if (await all.isVisible()) await all.click();
  let seen = 0;
  for (const c of rolling) {
    const row = group.locator("label", { has: page.locator(`input[value="${c.id}"]`) });
    if (!(await row.count())) continue; // not a contract a letter can end
    seen++;
    await expect(row.locator("time")).toHaveCount(0);
    await expect(row.getByText("Cancel any month").locator("visible=true")).toHaveCount(1);
  }
  expect(seen, "a listed contract you can cancel any month").toBeGreaterThan(0);
  const dated = group.locator("time[data-urgency]:visible");
  expect(await dated.count()).toBeGreaterThan(0);
  for (const t of await dated.all()) await expect(t).toHaveText(/^Send by /);
});
