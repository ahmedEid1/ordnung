/**
 * A letter addressed to someone else, on the real app (`ordnung serve` with the fake Claude). The fake answers with
 * the demo's recorded reading of the bank's fee increase, addressed to the demo persona, Sam Rivera. Renamed Alex
 * Rivera for this spec (`PUT /api/profile`, set back in `finally`; the real-app specs run one at a time), the person
 * is no longer the addressee: the letter says "Addressed to Sam Rivera", and the composer's From field starts with
 * Alex Rivera, says who the letter was addressed to and offers "Reply in Sam Rivera's name" — never filled in by
 * itself. Both at 320 and 1280 px, light and dark, with axe and the layout sweep's probes. Nothing is drafted, and
 * the letter it adds is deleted for good afterwards (the other real-app specs add the same file).
 */
import { readFileSync } from "node:fs";
import type { Page, TestInfo } from "@playwright/test";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { REAL_LETTER } from "./env";
import { apiGet, apiSend, expect, expectAccessible, open, settle, test, type Letter } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";
const RENAMED = "Alex Rivera";
const ADDRESSEE = "Sam Rivera";
const WIDTHS = [320, 1280] as const;
const THEMES = ["light", "dark"] as const;

test.describe.configure({ mode: "serial" });

/** The letter once the API lists it as read (it is read in the background). */
async function readLetter(page: Page): Promise<Letter> {
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

test("a letter addressed to someone else says so, and a reply offers their name without choosing it", async ({ page }, testInfo) => {
  const upload = await page.request.post("/api/documents", {
    headers: { "X-Ordnung-Client": "web" },
    multipart: { files: { name: FILE, mimeType: "application/pdf", buffer: readFileSync(REAL_LETTER) }, combine: "false" },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const letter = await readLetter(page);
  const before = await apiGet<{ name: string }>(page, "/api/profile");
  const drafts = (await apiGet<unknown[]>(page, "/api/drafts")).length;
  expect(before.name, "the real app's person is the demo persona").toBe(ADDRESSEE);
  try {
    await apiSend(page, "PUT", "/api/profile", { name: RENAMED });
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 320 ? 640 : 800 });

      // the letter's page: who it is addressed to, under the title
      await open(page, `/documents/${letter.id}`);
      const header = page.getByRole("main").getByRole("article").first().locator("header");
      await expect(header.getByText(`Addressed to ${ADDRESSEE}`)).toBeVisible();
      await checkView(page, testInfo, `letter-${width}`);

      // a reply: From starts with the person's own name; the addressee's is one press away
      await open(page, `/letters?kind=general_reply&doc=${letter.id}`);
      const dialog = page.getByRole("dialog", { name: "New letter" });
      const from = dialog.getByRole("textbox", { name: "From" });
      await expect(from).toHaveValue(RENAMED);
      await expect(from).toHaveAccessibleDescription(`This letter was addressed to ${ADDRESSEE}.`);
      await expect(dialog.getByRole("button", { name: "Use my name" })).toHaveCount(0);
      await from.scrollIntoViewIfNeeded();
      await checkView(page, testInfo, `composer-${width}`);

      await dialog.getByRole("button", { name: `Reply in ${ADDRESSEE}'s name` }).click();
      await expect(from).toHaveValue(ADDRESSEE);
      await expect(from).toHaveAccessibleDescription(new RegExp(`goes out in the name of ${ADDRESSEE}, who signs it`));
      await expect(dialog.getByRole("button", { name: `Reply in ${ADDRESSEE}'s name` })).toHaveCount(0);
      await checkView(page, testInfo, `composer-theirs-${width}`);

      await dialog.getByRole("button", { name: "Use my name" }).click();
      await expect(from).toHaveValue(RENAMED);
      // closed without drafting anything
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
    }
    expect(await apiGet<unknown[]>(page, "/api/drafts"), "nothing was drafted").toHaveLength(drafts);
  } finally {
    await apiSend(page, "PUT", "/api/profile", { name: before.name });
    await apiSend(page, "DELETE", `/api/documents/${letter.id}?purge=true`);
  }
  expect((await apiGet<{ name: string }>(page, "/api/profile")).name).toBe(ADDRESSEE);
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(FILE);
});
