/**
 * The real app (`ordnung serve`) with a fake Claude: a letter you add is read, its date reaches the
 * calendar file, and a letter deleted for good is gone — what the demo can't show (it reads only its
 * recorded letters). The fake answers with the demo's recorded reading of the bank's fee increase
 * (e2e/global-setup.ts); the tests share one letter, so they run in order.
 */
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { REAL_DATA_DIR, REAL_LETTER } from "./env";
import { apiGet, expect, letterDetail, open, shownAs, test, type Letter } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";

test.describe.configure({ mode: "serial" });

/** The uploaded letter, once the API lists it as read (it is read in the background). */
async function readLetter(page: Page): Promise<Letter & { status: string }> {
  let found: (Letter & { status: string }) | undefined;
  await expect
    .poll(
      async () => {
        found = (await apiGet<(Letter & { status: string })[]>(page, "/api/documents")).find((d) => d.filename === FILE);
        return found?.status;
      },
      { message: `${FILE} is read`, timeout: 30_000 },
    )
    .toBe("processed");
  return found!;
}

test("a letter you add is read by Claude", async ({ page }) => {
  await open(page, "/inbox", "Inbox");
  await page.locator("input[type=file][multiple]").first().setInputFiles(REAL_LETTER);
  const dialog = page.getByRole("dialog", { name: "Add this letter?" });
  await dialog.getByRole("button", { name: "Add letter" }).click();
  await expect(dialog).toBeHidden();

  const letter = await readLetter(page);
  const calls = readFileSync(`${REAL_DATA_DIR}-claude-calls.jsonl`, "utf8").trim().split("\n");
  expect(calls.length, "the letter went to the claude CLI").toBeGreaterThan(0);

  const { title, items } = await letterDetail(page, letter.id);
  await open(page, `/documents/${letter.id}`, shownAs(title));
  const consent = items.find((item) => item.due_date === "2026-11-30");
  expect(consent, `a to-do due 30 Nov 2026 (the letter has ${items.map((i) => `“${i.title}” ${i.due_date}`).join(", ")})`).toBeTruthy();
  await expect(page.getByRole("main").getByText(shownAs(consent!.title)).first()).toBeVisible();
});

test("its date is in the calendar file", async ({ page }) => {
  await open(page, "/timeline", "Timeline");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Add your dates to your calendar" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("ordnung.ics");
  const ics = readFileSync(await download.path(), "utf8");
  expect(ics).toMatch(/^BEGIN:VCALENDAR/);
  const event = ics.split("BEGIN:VEVENT").find((part) => /DTSTART[^:\r\n]*:20261130/.test(part));
  expect(event, "an event on 30 Nov 2026").toBeTruthy();
  await expect(page.getByRole("dialog", { name: "Add your dates to your calendar" })).toBeVisible();
});

test("a letter deleted for good is gone", async ({ page }) => {
  const letter = await readLetter(page);
  await open(page, `/documents/${letter.id}`);
  await page.getByRole("main").getByRole("button", { name: /^Delete$/ }).click();
  const confirm = page.getByRole("dialog", { name: "Delete this letter?" });
  await expect(confirm.getByText("This also removes")).toBeVisible();
  await confirm.getByRole("button", { name: "Delete letter" }).click();

  await page.waitForURL(/\/inbox$/);
  await expect(page.getByText("Letter deleted").first()).toBeVisible();
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(FILE);
  for (const path of [`/api/documents/${letter.id}`, `/api/documents/${letter.id}/file`, `/api/documents/${letter.id}/thumbnail.jpg`]) {
    expect((await page.request.get(path)).status(), path).toBe(404);
  }
});
