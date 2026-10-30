/**
 * A genuine letter Ordnung takes for a possible scam, on the real app (`ordnung serve` with the fake Claude): a made-up
 * bank letter whose reading carries a caution that names phishing, with one deadline (`e2e/fixtures/scam-check-letter.json`,
 * its dates filled in here: the deadline a weekday about two weeks ahead). While it is flagged, its deadline is on
 * neither Today nor the calendar file, but the letter's page still shows the date. Once the person presses "I checked
 * — it's genuine", Today, the letter's page and `/api/calendar.ics` have the deadline again. The letter's page, flagged
 * and checked, at 320 and 1280 px, light and dark, with axe and the layout sweep's probes. The fake Claude's answer is
 * set back and the letter deleted for good afterwards (the real-app specs run one at a time).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Page, TestInfo } from "@playwright/test";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { FAKE_CLAUDE_SCENARIO, WEB_DIR } from "./env";
import { apiGet, apiSend, expect, expectAccessible, open, READ, settle, test, type Letter, type LetterItem } from "./helpers";

const FIXTURE = join(WEB_DIR, "e2e", "fixtures", "scam-check-letter.json");
const WIDTHS = [320, 1280] as const;
const THEMES = ["light", "dark"] as const;
const CHECKED = "I checked — it's genuine";

test.describe.configure({ mode: "serial" });

interface Fixture {
  filename: string;
  letter: string[];
  reading: { items: { title: string }[] };
}

interface Detail {
  document: { id: string; status: string };
  items: LetterItem[];
  suggestions: { id: string; kind: string; status: string }[];
}

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const german = (d: Date) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
const daysFrom = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

/** The fixture with its dates: the letter of two days ago, its deadline a weekday about two weeks ahead. */
function fixture(): Fixture {
  const today = new Date();
  let due = daysFrom(today, 14);
  while (due.getDay() === 0 || due.getDay() === 6) due = daysFrom(due, 1);
  const letter = daysFrom(today, -2);
  const values: Record<string, string> = { LETTER: iso(letter), LETTER_DE: german(letter), DUE: iso(due), DUE_DE: german(due) };
  return JSON.parse(readFileSync(FIXTURE, "utf8").replace(/\{\{(\w+)\}\}/g, (all: string, key: string) => values[key] ?? all)) as Fixture;
}

/** The letter once the API lists it as read (it is read in the background). */
async function readLetter(page: Page, file: string): Promise<Letter> {
  let found: (Letter & { status: string }) | undefined;
  await expect
    .poll(
      async () => {
        found = (await apiGet<(Letter & { status: string })[]>(page, "/api/documents")).find((d) => d.filename === file);
        return found?.status;
      },
      { message: `${file} is read`, timeout: 30_000 },
    )
    .toMatch(/^(processed|needs_review)$/);
  return found!;
}

/** Whether Today lists the to-do (what needs you now, and what is coming up), as the API gives Today. */
async function onToday(page: Page, itemId: string): Promise<boolean> {
  const today = await apiGet<{ attention: { id: string }[]; upcoming: { id: string }[] }>(page, "/api/dashboard");
  return [...today.attention, ...today.upcoming].some((i) => i.id === itemId);
}

/** The calendar file's text, its long lines unfolded (RFC 5545 folds them at 75 octets). */
async function calendar(page: Page): Promise<string> {
  const res = await page.request.get("/api/calendar.ics", READ);
  expect(res.ok(), `GET /api/calendar.ics → ${res.status()}`).toBe(true);
  return (await res.text()).replace(/\r?\n[ \t]/g, "");
}

/** Why a layout finding fails (the layout sweep's rules, `e2e/layout-sweep.spec.ts`), or null when it doesn't. */
function fault(f: Finding): string | null {
  switch (f.probe) {
    case "page-overflow":
      return `the page scrolls sideways (${f.text})`;
    case "offscreen":
      return `past the edge of the screen by ${String(f.detail.by)} px`;
    case "target-size":
      return f.kind === "exempt" ? null : `target of ${String(f.detail.width)} × ${String(f.detail.height)} px (under 24 × 24)`;
    case "covered":
      return `its centre is covered by ${String(f.detail.by)} (${String(f.detail.at)})`;
    case "clipped-text":
      return `text cut off (${String(f.detail.how)})`;
    case "clipped-content":
      return `control cut off by ${String(f.detail.container)}`;
    case "truncated":
      return f.detail.fullValueAt ? null : `text cut short (${String(f.detail.how)}) with its whole value nowhere at hand`;
    case "empty-icon":
      return "icon drawn at zero size";
    default:
      return null;
  }
}

/** The view in light and dark: no layout fault, and axe finds nothing serious. */
async function checkView(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /^(?![\s\S]*\bdark\b)/);
    await settle(page);
    const { findings } = await layoutFindings(page);
    const faults = findings.flatMap((f) => {
      const why = fault(f);
      return why ? [`${f.selector} “${f.text}”: ${why}`] : [];
    });
    expect(faults, `${name} (${theme}): layout`).toEqual([]);
    await expectAccessible(page, testInfo, `${name}-${theme}`);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

test("a genuine letter taken for a scam keeps its date in view, and gets its reminders back once the person checked it", async ({ page }, testInfo) => {
  const letter = fixture();
  const title = letter.reading.items[0]!.title;
  const scenario = readFileSync(FAKE_CLAUDE_SCENARIO, "utf8");
  const { log } = JSON.parse(scenario) as { log: string };
  // the fake Claude's answer for this letter, as the `result` event of Claude Code's stream-json
  const result = { type: "result", subtype: "success", is_error: false, result: "", num_turns: 1, structured_output: letter.reading };
  writeFileSync(FAKE_CLAUDE_SCENARIO, JSON.stringify({ log, calls: [{ lines: [JSON.stringify(result)] }] }));
  try {
    const upload = await page.request.post("/api/documents", {
      headers: { "X-Ordnung-Client": "web" },
      multipart: { files: { name: letter.filename, mimeType: "text/plain", buffer: Buffer.from(letter.letter.join("\n"), "utf8") }, combine: "false" },
    });
    expect(upload.status(), await upload.text()).toBe(201);
    const doc = await readLetter(page, letter.filename);
    const detail = await apiGet<Detail>(page, `/api/documents/${doc.id}`);
    const item = detail.items.find((i) => i.title === title);
    expect(item?.due_date, "the deadline was read").toBeTruthy();
    const due = item!.due_date!;
    expect(detail.suggestions.filter((s) => s.kind === "scam" && s.status === "new"), "the caution flags the letter").toHaveLength(1);

    // flagged: no reminder anywhere — but the letter's page shows the date
    expect(await onToday(page, item!.id), "Today, flagged").toBe(false);
    expect(await calendar(page), "the calendar file, flagged").not.toContain(title);
    await open(page, "/");
    await expect(page.locator("#top3-title, #coming-up-title").locator("xpath=ancestor::section[1]").filter({ hasText: title })).toHaveCount(0);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 320 ? 640 : 800 });
      await open(page, `/documents/${doc.id}`);
      const verdict = page.getByRole("main").getByRole("article").first();
      await expect(verdict.getByText("Possible scam")).toBeVisible();
      const row = page.getByRole("region", { name: /^To-dos & dates/ }).getByRole("listitem").filter({ hasText: title });
      await expect(row.locator(`time[datetime="${due}"]`)).toBeVisible();
      await expect(row).not.toContainText("was due");
      await checkView(page, testInfo, `flagged-${width}`);
    }

    // "I checked — it's genuine"
    await page.getByRole("button", { name: CHECKED }).click();
    await expect(page.getByText("Warning removed")).toBeVisible();
    await expect.poll(() => onToday(page, item!.id), { message: "Today lists the deadline once the letter is checked", timeout: 15_000 }).toBe(true);
    expect(await calendar(page), "the calendar file, checked").toContain(title);

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 320 ? 640 : 800 });
      await open(page, `/documents/${doc.id}`);
      const verdict = page.getByRole("main").getByRole("article").first();
      await expect(verdict.getByText("Possible scam")).toHaveCount(0);
      await expect(verdict.getByText(/Nothing right now/)).toHaveCount(0);
      await expect(verdict.locator(`time[datetime="${due}"]`)).toBeVisible();
      await checkView(page, testInfo, `checked-${width}`);
    }
    await open(page, "/");
    await expect(page.getByRole("main").getByText(title).first()).toBeVisible();
  } finally {
    // as the other real-app specs expect it: the recorded reading of their letter, and no such letter
    writeFileSync(FAKE_CLAUDE_SCENARIO, scenario);
    for (const added of (await apiGet<Letter[]>(page, "/api/documents")).filter((d) => d.filename === letter.filename)) {
      await apiSend(page, "DELETE", `/api/documents/${added.id}?purge=true`);
    }
  }
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(letter.filename);
});
