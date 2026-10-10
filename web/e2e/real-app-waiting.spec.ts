/**
 * The real app (`ordnung serve`) while Claude is missing: a letter you add waits for it, and a page loaded
 * afterwards still says so — the "Waiting for Claude" banner, the letter's waiting card with "Add a date" and
 * no placeholders, and neither Today nor the weekly review saying "All clear" (final check F-M1, F-M2: the
 * pause was said once, live, and a reload lost it). Claude goes missing by taking away the link the real app
 * runs as `claude` (e2e/env.ts); it comes back at the end. Runs after real-app-letters.spec.ts.
 *
 * A scan added meanwhile waits too, yet the letter search finds it by the text its scanner added, marked "not
 * checked", and its page says what that text is kept for (ADR 0020). The scan is a committed, fictional
 * searchable PDF (`e2e/fixtures/searchable-scan.pdf`: a picture of the page with the same lines drawn over it
 * as invisible text, like `tests/helpers_docs.scanned_pdf(ocr=True)`).
 */
import { rmSync, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { FAKE_CLAUDE, REAL_CLAUDE, REAL_LETTER } from "./env";
import { apiGet, expect, expectAccessible, open, test, type Letter } from "./helpers";

/** A letter of its own (not the one real-app-letters.spec.ts reads): it is never read, and deleted at the end. */
const FILE = "20_stadtbibliothek_mahnung.pdf";
const NOT_INSTALLED = "Claude Code isn't installed on this computer yet.";
/** The fictional searchable scan, and a word only its scanner's text has (no other letter of the real app). */
const SCAN = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "searchable-scan.pdf");
const SCAN_FILE = "searchable-scan.pdf";
const SCAN_WORD = "Zählerablesung";
const SCANNER_TEXT_MATCH = "Found in your scanner's text — not checked";

interface QueueJob {
  doc_id: string | null;
  status: string;
  waiting_reason: string | null;
}

/** Claude installed again: the link back in place. */
function installClaude(): void {
  rmSync(REAL_CLAUDE, { force: true });
  symlinkSync(FAKE_CLAUDE, REAL_CLAUDE);
}

test.beforeAll(() => rmSync(REAL_CLAUDE, { force: true }));
test.afterAll(installClaude);

/** The banner every page shows while letters wait for Claude. */
const banner = (page: Page) => page.getByRole("status").filter({ hasText: "Waiting for Claude" });

test("a letter added while Claude is missing waits, and every page loaded later says so", async ({ page }, testInfo) => {
  let letter: Letter | undefined;
  let scan: Letter | undefined;
  await test.step("add a letter: it waits for Claude", async () => {
    await open(page, "/inbox", "Inbox");
    await page.locator("input[type=file][multiple]").first().setInputFiles(join(dirname(REAL_LETTER), FILE));
    const dialog = page.getByRole("dialog", { name: "Add this letter?" });
    // "Store now, read later" once the app knows Claude is missing; "Add letter" while a check of a minute ago says ready
    await dialog.getByRole("button", { name: /^(Add letter|Store now, read later)$/ }).click();
    await expect(dialog).toBeHidden();
    await expect
      .poll(
        async () => {
          letter = (await apiGet<Letter[]>(page, "/api/documents")).find((d) => d.filename === FILE);
          const jobs = await apiGet<QueueJob[]>(page, "/api/jobs?active_only=true");
          return jobs.find((j) => letter && j.doc_id === letter.id)?.waiting_reason ?? null;
        },
        { message: `${FILE} waits for Claude`, timeout: 30_000 },
      )
      .toContain(`Waiting for Claude: ${NOT_INSTALLED}`);
  });
  const id = letter!.id;

  await test.step("its page, loaded again: why it waits, and the dates you can add", async () => {
    await page.goto(`/documents/${id}`);
    await page.reload();
    await expect(banner(page)).toContainText(NOT_INSTALLED);
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: "This letter waits for Claude" })).toBeVisible();
    await expect(main.getByRole("link", { name: "Claude connection" })).toHaveAttribute("href", "/settings?section=claude");
    const todos = main.getByRole("region", { name: "To-dos & dates" });
    await expect(todos.getByRole("button", { name: "Add a date" })).toBeVisible();
    // no stepper stuck on its first step, no placeholders that never fill
    await expect(main.getByText(/step \d of \d/i)).toHaveCount(0);
    await expect(page.locator("#doc-view-panel-letter-more .animate-pulse")).toHaveCount(0);
  });

  await test.step("Today never says “All clear”", async () => {
    await open(page, "/");
    await expect(banner(page)).toBeVisible();
    const top = page.getByRole("region", { name: "Top 3 this week" });
    await expect(top.getByRole("heading", { name: "Nothing due from the letters that were read" })).toBeVisible();
    await expect(top).toContainText("1 letter isn't read yet");
    await expect(page.getByText(/All clear/)).toHaveCount(0);
  });

  await test.step("nor does the weekly review's ending", async () => {
    await open(page, "/week?step=file", "Weekly review");
    await page.getByRole("button", { name: /^Finish/ }).click();
    await expect(page.getByRole("heading", { name: "Nothing due from the letters that were read" })).toBeVisible();
    await expect(page.getByText(/^1 letter isn't read yet/)).toBeVisible();
    await expect(page.getByText(/All clear/)).toHaveCount(0);
  });

  await test.step("a scan added meanwhile waits too, and search finds it by its scanner's text, not checked", async () => {
    await open(page, "/inbox", "Inbox");
    await page.locator("input[type=file][multiple]").first().setInputFiles(SCAN);
    const dialog = page.getByRole("dialog", { name: "Add this letter?" });
    await dialog.getByRole("button", { name: /^(Add letter|Store now, read later)$/ }).click();
    await expect(dialog).toBeHidden();
    // its text is read on this computer while it waits: the search finds it, by the scanner's text alone
    await expect
      .poll(
        async () => {
          scan = (await apiGet<Letter[]>(page, "/api/documents")).find((d) => d.filename === SCAN_FILE);
          const found = await apiGet<(Letter & { found_in: string | null })[]>(page, `/api/documents?q=${encodeURIComponent(SCAN_WORD)}`);
          return found.find((d) => scan && d.id === scan.id)?.found_in ?? null;
        },
        { message: `${SCAN_FILE} is found by its scanner's text`, timeout: 30_000 },
      )
      .toBe("scanner_text");
    await expect(page.getByText(SCANNER_TEXT_MATCH)).toHaveCount(0); // the Inbox says it only while searching
    const field = page.getByRole("combobox", { name: "Search your letters" }).first();
    await field.click();
    await field.fill(SCAN_WORD);
    const option = page.getByRole("option", { name: new RegExp(SCAN_FILE.replace(".", "\\.")) });
    await expect(option).toContainText(SCANNER_TEXT_MATCH);
    await expectAccessible(page, testInfo, "search: a match in a scanner's text");
    await option.click();
    await expect(page).toHaveURL(new RegExp(`/documents/${scan!.id}$`));
  });

  await test.step("the scan's page: it still waits, and says what its scanner's text is kept for", async () => {
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: "This letter waits for Claude" })).toBeVisible();
    const note = main.getByText(/^Your scanner added its own text to this file\./);
    await expect(note).toHaveText(
      "Your scanner added its own text to this file. Ordnung keeps it only so search can find the letter: it isn't checked, isn't shown as the letter's words and is never sent to Claude.",
    );
    await expect(main.getByText("Not sent to Claude. The letter hasn't left your computer.")).toBeVisible();
    // the scanner's text is never shown
    await expect(main.getByText(SCAN_WORD)).toHaveCount(0);
    const detail = await apiGet<{ document: { status: string }; scan_text_pages: number[] }>(page, `/api/documents/${scan!.id}`);
    expect([detail.document.status, detail.scan_text_pages]).toEqual(["queued", [1]]);
    await expectAccessible(page, testInfo, "a waiting scan's page");
  });

  await test.step("the letters go (never read), and Claude comes back", async () => {
    for (const doc of [id, scan!.id]) {
      const res = await page.request.delete(`/api/documents/${doc}?purge=true`, { headers: { "X-Ordnung-Client": "web" } });
      expect(res.ok(), `DELETE /api/documents/${doc} → ${res.status()}`).toBe(true);
    }
    installClaude();
    // the health check finds Claude now, so the specs after this one don't wait out the worker's own check
    const health = await page.request.get("/api/health", { headers: { "X-Ordnung-Client": "web" } });
    expect(health.ok(), `GET /api/health → ${health.status()}`).toBe(true);
  });
});
