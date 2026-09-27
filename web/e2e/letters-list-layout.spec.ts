/**
 * The Letters list and the New-letter composer on the real demo, where jsdom can't measure (UI audit
 * round 1, letters-b): beside "How letters work" (1024–1280 px) the rows kept only their icon and
 * status — the title squeezed out by a fixed status column; phones lost the date and the row's focus
 * ring was clipped to a line; the composer's lists scrolled inside the scrolling dialog, a contract
 * chosen by a link out of view; picking a kind on a small phone changed nothing visible.
 */
import type { Page } from "@playwright/test";
import { apiGet, expect, open, settle, setTour, test } from "./helpers";

interface DraftSummary {
  id: string;
  kind: string;
  status: string;
}

/** At least one letter in the list (the phone contract's cancellation, drafted here if the demo has none). */
async function ensureDraft(page: Page): Promise<void> {
  const drafts = await apiGet<DraftSummary[]>(page, "/api/drafts");
  if (drafts.length) return;
  const contracts = await apiGet<{ id: string; name: string }[]>(page, "/api/contracts");
  const phone = contracts.find((c) => /FunkNetz/.test(c.name))!;
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

for (const width of [320, 390]) {
  test(`Letters at ${width}px: each row says its status and date; the focus ring is drawn whole inside the row`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/letters", "Letters");
    expect(await noSideScroll(page)).toBe(true);
    const row = page.locator("[data-draft-row]").first();
    const meta = row.locator("[data-draft-meta]");
    await expect(meta).toBeVisible();
    await expect(meta).toContainText(/send by|Started|by /);
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
  await expect(chosen).toContainText(plain!.title!);
  await expect(dialog.getByRole("radiogroup", { name: "Or choose a decision you can object to" })).toBeVisible();
  const write = dialog.getByRole("button", { name: "Write the letter" });
  await expect(write).toBeDisabled();
  await expect(write).toHaveAccessibleDescription(/You can't object to this letter/);
});
