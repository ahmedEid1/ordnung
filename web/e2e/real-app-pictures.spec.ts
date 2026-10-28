/**
 * The words in a private photo, read by Ordnung itself with the Tesseract installed on this computer (ADR 0024), on
 * the real app (`ordnung serve`): a photo kept private (*Keep private — no AI*) is read in the background, the search
 * box and the Inbox's search find it by its words with the line "Found in text Ordnung read from the picture — not
 * checked", and its page says what those words are kept for — and never shows them. At 320, 375 and 1280 px, light and
 * dark, with axe and the layout sweep's probes. The photo is deleted for good at the end, and its words with it.
 *
 * The photo is a committed, fictional printed letter (`e2e/fixtures/private-photo.jpg`, drawn by
 * `scripts/make_photo_fixture.py`); "Kellerabteil" is a word only it has among the real app's letters.
 *
 * It runs only when the real app reads pictures: `ORDNUNG_E2E_OCR=on` (e2e/env.ts), with Tesseract and its German or
 * English data installed. Otherwise it is skipped — except with `ORDNUNG_REQUIRE_TESSERACT=1` (CI's end-to-end job),
 * where a skip is a failure.
 */
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, TestInfo } from "@playwright/test";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { E2E_OCR } from "./env";
import { apiGet, apiSend, expect, expectAccessible, open, READ, settle, test, type Letter } from "./helpers";

/** The fictional photo, and the word only it has. */
const PHOTO = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "private-photo.jpg");
const FILE = "private-photo.jpg";
const WORD = "Kellerabteil";
const PICTURE_TEXT_MATCH = "Found in text Ordnung read from the picture — not checked";
const PHOTO_NOTE =
  "Ordnung read the words in this photo itself, only so search can find the letter: they aren't checked, aren't shown as the letter's words and are never sent to Claude.";
const WIDTHS = [320, 375, 1280] as const;
const THEMES = ["light", "dark"] as const;
/** CI's end-to-end job: this spec must run, never be skipped. */
const REQUIRED = process.env.ORDNUNG_REQUIRE_TESSERACT === "1";

interface FoundLetter extends Letter {
  found_in: string | null;
}

interface PhotoPage {
  document: { ai_private: boolean; mime: string };
  scan_text_pages: number[];
  picture_text_pages: number[];
}

/** A Tesseract here that can read German or English: the real app looks for it the same way (ingest/ocr.py). */
function tesseractHere(): boolean {
  const langs = spawnSync("tesseract", ["--list-langs"], { encoding: "utf8", timeout: 10_000 });
  return langs.status === 0 && /^(deu|eng)$/m.test(`${langs.stdout}\n${langs.stderr}`);
}

/** Why this spec can't run here, or null when it can. */
const cantRun = !E2E_OCR ? "the real app reads pictures only with ORDNUNG_E2E_OCR=on" : !tesseractHere() ? "no Tesseract with German or English data here" : null;
test.skip(cantRun !== null && !REQUIRED, cantRun ?? "");

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

/** The view in light and dark: no layout fault, axe finds nothing serious, and the photo's words are nowhere. */
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

/** The letter search of the top bar, or of its sheet on a phone. */
async function searchField(page: Page) {
  const sheet = page.getByRole("button", { name: "Search letters" });
  if (await sheet.isVisible()) {
    await sheet.click();
    return page.getByRole("dialog", { name: "Search letters" }).getByRole("combobox", { name: "Search your letters" });
  }
  return page.getByRole("combobox", { name: "Search your letters" }).first();
}

test("a photo kept private is found by the words Ordnung read from it, marked not checked, and never shown", async ({ page }, testInfo) => {
  expect(cantRun, "ORDNUNG_REQUIRE_TESSERACT=1: the pictures spec must run").toBeNull();
  // the worker reads pictures 30 s after the real app starts (and after each reading), then 18 views are checked
  test.setTimeout(300_000);
  let photo: Letter | undefined;
  try {
    await test.step("keep a photo private: Ordnung reads its words on this computer, in the background", async () => {
      await open(page, "/inbox", "Inbox");
      await page.locator("input[type=file][multiple]").first().setInputFiles(PHOTO);
      const dialog = page.getByRole("dialog", { name: "Add this letter?" });
      await dialog.getByRole("switch", { name: /Keep private/ }).click();
      await dialog.getByRole("button", { name: "Store privately" }).click();
      await expect(dialog).toBeHidden();
      await expect
        .poll(
          async () => {
            photo = (await apiGet<Letter[]>(page, "/api/documents")).find((d) => d.filename === FILE);
            if (!photo) return null;
            const found = await apiGet<FoundLetter[]>(page, `/api/documents?q=${WORD}`);
            return found.find((d) => d.id === photo!.id)?.found_in ?? null;
          },
          { message: `${FILE} is found by the words Ordnung read from it`, timeout: 90_000, intervals: [1_000] },
        )
        .toBe("picture_text");
      // its page names the page Ordnung read, never the words
      const detail = await apiGet<PhotoPage>(page, `/api/documents/${photo!.id}`);
      expect([detail.document.ai_private, detail.document.mime, detail.scan_text_pages, detail.picture_text_pages]).toEqual([true, "image/jpeg", [], [1]]);
      expect(JSON.stringify(detail)).not.toContain(WORD);
    });
    const id = photo!.id;

    for (const width of WIDTHS) {
      await test.step(`${width} px: the search box, the Inbox's search and the photo's page`, async () => {
        await page.setViewportSize({ width, height: width === 1280 ? 800 : 640 });

        // the search box: the photo's option says where its words were found, as part of its name
        await open(page, "/");
        const field = await searchField(page);
        await field.fill(WORD);
        const option = page.getByRole("listbox", { name: "Matching letters" }).getByRole("option");
        await expect(option).toHaveCount(1);
        await expect(option).toContainText(PICTURE_TEXT_MATCH);
        await expect(option).toHaveAccessibleName(new RegExp(`${FILE.replace(".", "\\.")}.*${PICTURE_TEXT_MATCH}`));
        await expect(option).not.toContainText(WORD);
        await page.waitForLoadState("networkidle");
        await checkView(page, testInfo, `search-${width}`);
        await expect(option).toBeVisible();

        // the Inbox while searching: the photo's row, with the same line of its own
        await open(page, `/inbox?q=${WORD}`, "Inbox");
        const row = page.getByRole("tabpanel").locator("li").filter({ has: page.locator(`a[href="/documents/${id}"]`) });
        await expect(row).toHaveCount(1);
        await expect(row.getByText(PICTURE_TEXT_MATCH)).toBeVisible();
        await expect(row.getByText(/scanner's text/)).toHaveCount(0);
        await expect(row).not.toContainText(WORD);
        await checkView(page, testInfo, `inbox-search-${width}`);

        // the photo's page: which page Ordnung read and what for; the words themselves nowhere
        await open(page, `/documents/${id}`);
        const main = page.getByRole("main");
        const note = main.getByText(PHOTO_NOTE);
        await note.scrollIntoViewIfNeeded();
        await expect(note).toBeVisible();
        await expect(main.getByText("This letter never left your computer.")).toBeVisible();
        await expect(main.getByText(WORD)).toHaveCount(0);
        await checkView(page, testInfo, `photo-${width}`);
      });
    }

    await test.step("deleted for good, the photo goes with the words Ordnung read from it", async () => {
      await page.setViewportSize({ width: 1280, height: 800 });
      await open(page, `/documents/${id}`);
      await page.getByRole("main").getByRole("button", { name: /^Delete$/ }).click();
      const confirm = page.getByRole("dialog", { name: "Delete this letter?" });
      await confirm.getByRole("button", { name: "Delete letter" }).click();
      await expect(page).toHaveURL(/\/inbox$/);
      const gone = await page.request.get(`/api/documents/${id}`, READ);
      expect(gone.status(), `GET /api/documents/${id}`).toBe(404);
      expect(await apiGet<FoundLetter[]>(page, `/api/documents?q=${WORD}`)).toEqual([]);
    });
  } finally {
    // as the other real-app specs expect it: no such letter
    for (const added of (await apiGet<Letter[]>(page, "/api/documents")).filter((d) => d.filename === FILE)) {
      await apiSend(page, "DELETE", `/api/documents/${added.id}?purge=true`);
    }
  }
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(FILE);
});
