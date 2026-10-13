/**
 * The letter list (`GET /api/documents`) leaves out each letter's reading: its explanation, key facts,
 * references, bank details and file hash (`LEFT_OUT_OF_LIST` in the API); the letter's own page has them. Every
 * screen fed by the list still shows its letters, with no error screen: Today, the Inbox, the weekly review,
 * Letters for taxes, Export letters, the letter search, the composer's list of letters and Ask. "Download a copy
 * of your records" takes every letter whole from `GET /api/documents.json`, so each letter Claude read keeps its
 * explanation there. Runs against the demo in the "layout" project. It sends, files and deletes nothing: the
 * composer closes unsent, the export dialog downloads nothing, and Ask replays a recorded answer.
 */
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { apiGet, expect, open, setTour, settle, test } from "./helpers";

/** What the list leaves out of each letter, as the API names it (`ordnung.api.routes.documents.LEFT_OUT_OF_LIST`). */
const LEFT_OUT_OF_LIST = ["key_facts", "explanation", "references", "payment", "sha256"] as const;

type Row = Record<string, unknown> & { id: string; filename: string };

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** No crash screen (a page's or the whole app's), and no value the page couldn't fill in. */
async function expectShown(page: Page, where: string): Promise<void> {
  await expect(page.getByRole("heading", { name: /^(Something went wrong on this page|Ordnung hit a snag)$/ }), `${where}: an error screen`).toHaveCount(0);
  expect(await page.getByRole("main").innerText(), `${where}: a value left unfilled`).not.toMatch(/\bundefined\b|\bNaN\b|\[object Object\]/);
}

test("the letter list leaves out each letter's reading, and the letter's own page has it", async ({ page }) => {
  const rows = await apiGet<Row[]>(page, "/api/documents");
  expect(rows.length).toBeGreaterThan(10);
  expect(rows.filter((row) => LEFT_OUT_OF_LIST.some((field) => field in row)).map((row) => row.filename)).toEqual([]);
  const searched = await apiGet<Row[]>(page, "/api/documents?q=Muster");
  expect(searched.length).toBeGreaterThan(0);
  expect(searched.filter((row) => LEFT_OUT_OF_LIST.some((field) => field in row)).map((row) => row.filename)).toEqual([]);
  const { document } = await apiGet<{ document: Row }>(page, `/api/documents/${rows[0]!.id}`);
  for (const field of LEFT_OUT_OF_LIST) expect(document, `the letter's page has its ${field}`).toHaveProperty(field);
});

test("Today, the Inbox and the weekly review show their letters", async ({ page }) => {
  await open(page, "/", /Sam/);
  await expectShown(page, "Today");

  await open(page, "/inbox", "Inbox");
  const letters = page.getByRole("main").locator('a[href^="/documents/doc_"]');
  expect(await letters.count(), "the Inbox lists letters").toBeGreaterThan(10);
  await expect(letters.first()).toBeVisible();
  await expectShown(page, "Inbox");

  await open(page, "/week", "Weekly review");
  await expectShown(page, "Weekly review");
});

test("Letters for taxes and the Export letters dialog count their letters", async ({ page }) => {
  // the demo's letters for taxes are dated 2026
  await open(page, "/inbox/taxes?year=2026", "Tax year 2026");
  expect(await page.locator("[data-letter-note]").count(), "each letter for taxes with its note").toBeGreaterThan(0);
  await expectShown(page, "Letters for taxes");
  await page.getByRole("button", { name: "Export these letters…" }).click();
  const dialog = page.getByRole("dialog", { name: "Export letters" });
  await expect(dialog.getByRole("status")).toHaveText(/^[1-9]\d* letters? will be in the ZIP\.$/);
  await expectShown(page, "Export letters");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});

test("the letter search finds letters by name", async ({ page }) => {
  await open(page, "/", /Sam/);
  await page.keyboard.press("/");
  const field = page.getByRole("combobox", { name: "Search your letters" });
  await expect(field).toBeFocused();
  await field.fill("Muster");
  const options = page.getByRole("listbox", { name: "Matching letters" }).getByRole("option");
  await expect(options.first()).toBeVisible();
  expect(await options.count()).toBeGreaterThan(0);
  for (const text of await options.allInnerTexts()) expect(text, "a search result").not.toMatch(/\bundefined\b|\bnull\b/);
  await expectShown(page, "Letter search");
  await page.keyboard.press("Escape");
});

test("the composer lists the letters to answer, and closes unsent", async ({ page }) => {
  await open(page, "/letters", "Letters");
  const drafts = (await apiGet<unknown[]>(page, "/api/drafts")).length;
  await page.getByRole("button", { name: "New letter" }).click();
  const composer = page.getByRole("dialog", { name: "New letter" });
  await composer.locator("label", { hasText: "Reply to a letter" }).click();
  await expect(composer.getByText("Which letter are you answering?")).toBeVisible();
  const choices = composer.locator('input[name="letter-reply"]');
  await expect(choices.first()).toBeAttached();
  expect(await choices.count(), "the letters to answer").toBeGreaterThan(3);
  await settle(page);
  await expectShown(page, "Composer");
  await page.keyboard.press("Escape");
  await expect(composer).toBeHidden();
  expect((await apiGet<unknown[]>(page, "/api/drafts")).length, "no letter was drafted").toBe(drafts);
});

test("Ask names the letters its answer looked at", async ({ page }) => {
  await open(page, "/ask");
  await expectShown(page, "Ask");
  // a recorded question whose answer cites a letter (e2e/pages.spec.ts asks it too)
  const question = "When does my residence permit expire, and what should I do before then?";
  await page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: question }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
  const turn = page.getByRole("article", { name: `Question: ${question}` });
  const letters = turn.locator('a[href^="/documents/doc_"]');
  await expect(letters.first()).toBeVisible();
  for (const name of await letters.evaluateAll((links) => links.map((a) => a.getAttribute("aria-label") ?? a.textContent ?? ""))) {
    expect(name.trim(), "a source named by its letter").not.toMatch(/^$|\bundefined\b|\bnull\b/);
  }
  await expectShown(page, "Ask");
});

test("Download a copy of your records: every letter whole, each letter Claude read with its explanation", async ({ page }) => {
  await open(page, "/settings?section=data", "Settings");
  const card = page.getByRole("region", { name: "Download a copy of your records" });
  const [download] = await Promise.all([page.waitForEvent("download"), card.getByRole("button", { name: "Download JSON" }).click()]);
  await expect(page.getByText("Your records are downloading").first()).toBeVisible();
  expect(download.suggestedFilename()).toMatch(/^ordnung-export-\d{4}-\d{2}-\d{2}\.json$/);
  const records = JSON.parse(readFileSync((await download.path())!, "utf8")) as { documents: Row[] };

  // the same letters as the list, in its order, each whole
  const rows = await apiGet<Row[]>(page, "/api/documents");
  expect(records.documents.map((d) => d.id)).toEqual(rows.map((row) => row.id));
  for (const d of records.documents) for (const field of LEFT_OUT_OF_LIST) expect(d, `${d.filename} keeps its ${field}`).toHaveProperty(field);
  const read = records.documents.filter((d) => d.ai_processed_at && !d.ai_private && (d.status === "processed" || d.status === "needs_review"));
  expect(read.length, "letters Claude read").toBeGreaterThan(5);
  expect(read.filter((d) => typeof d.explanation !== "string" || !d.explanation).map((d) => d.filename), "read letters without their explanation").toEqual([]);
});
