/**
 * The real app (`ordnung serve`) while Claude is missing: a letter you add waits for it, and a page loaded
 * afterwards still says so — the "Waiting for Claude" banner, the letter's waiting card with "Add a date" and
 * no placeholders, and neither Today nor the weekly review saying "All clear" (final check F-M1, F-M2: the
 * pause was said once, live, and a reload lost it). Claude goes missing by taking away the link the real app
 * runs as `claude` (e2e/env.ts); it comes back at the end. Runs after real-app-letters.spec.ts.
 */
import { rmSync, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Page } from "@playwright/test";
import { FAKE_CLAUDE, REAL_CLAUDE, REAL_LETTER } from "./env";
import { apiGet, expect, open, test, type Letter } from "./helpers";

/** A letter of its own (not the one real-app-letters.spec.ts reads): it is never read, and deleted at the end. */
const FILE = "20_stadtbibliothek_mahnung.pdf";
const NOT_INSTALLED = "Claude Code isn't installed on this computer yet.";

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

test("a letter added while Claude is missing waits, and every page loaded later says so", async ({ page }) => {
  let letter: Letter | undefined;
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

  await test.step("the letter goes (never read), and Claude comes back", async () => {
    const res = await page.request.delete(`/api/documents/${id}?purge=true`, { headers: { "X-Ordnung-Client": "web" } });
    expect(res.ok(), `DELETE /api/documents/${id} → ${res.status()}`).toBe(true);
    installClaude();
    // the health check finds Claude now, so the specs after this one don't wait out the worker's own check
    const health = await page.request.get("/api/health", { headers: { "X-Ordnung-Client": "web" } });
    expect(health.ok(), `GET /api/health → ${health.status()}`).toBe(true);
  });
});
