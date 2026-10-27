/**
 * Your household on the demo, where jsdom can't look (ADR 0023): the Settings card (empty, with people, an edit with
 * its refusal, the question before removing someone with letters), a letter's question *Is this letter for …?*, its
 * *Who is this letter for?* choices (a sheet on phones) and *Add … to your household* with its visible *Also file*
 * box — at 320, 375 and 1280 px, light and dark, with axe and the layout sweep's probes.
 *
 * Every demo letter is addressed to the demo persona, Sam Rivera. Renamed Alex Rivera for this spec (`PUT
 * /api/profile`), the person is no longer the addressee, so Sam Rivera can be someone of the household. Everything
 * is filed by a press here; `finally` empties the household and gives the person their name back, so Ask's recorded
 * answers and the specs after this one find the demo as it was.
 */
import type { Page, TestInfo } from "@playwright/test";
import type { Household } from "@/api/types";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { apiGet, apiSend, expect, expectAccessible, letterId, open, settle, setTour, test } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";
const RENAMED = "Alex Rivera";
const ADDRESSEE = "Sam Rivera";
const CHILD = "Mia Rivera";
const WIDTHS = [320, 375, 1280] as const;
const THEMES = ["light", "dark"] as const;
const OWN_NAME = "That's your own name. Your household is the other people your letters come for.";

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

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

/** No one in the household and nothing filed: no row, as the demo starts. */
async function emptyHousehold(page: Page): Promise<void> {
  const h = await apiGet<Household>(page, "/api/household");
  const answered = [...Object.keys(h.filed), ...h.mine];
  if (answered.length) await apiSend(page, "PATCH", "/api/household", { letters: Object.fromEntries(answered.map((id) => [id, null])) });
  // twice: the people removed by the first change keep their letters' links one change longer (for Undo)
  for (let n = 0; n < 2; n++) {
    const now = await apiGet<Household>(page, "/api/household");
    await apiSend(page, "PUT", "/api/household", { base: now.version, members: [] });
  }
}

const header = (page: Page) => page.getByRole("main").getByRole("article").first().locator("header");
const card = (page: Page) => page.getByRole("region", { name: "Your household" });
const addForm = (page: Page) => page.getByRole("form", { name: "Add someone to your household" });

async function addPerson(page: Page, name: string, signs = true): Promise<void> {
  const form = addForm(page);
  await form.getByRole("textbox", { name: "Name" }).fill(name);
  const box = form.getByRole("checkbox", { name: /Signs their own letters/ });
  if ((await box.isChecked()) !== signs) await box.click();
  await form.getByRole("button", { name: "Add to household" }).click();
  await expect(card(page).getByRole("listitem").filter({ hasText: name })).toBeVisible();
}

test("your household: the Settings card, a letter's question, its choices and “Add … to your household”", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const before = await apiGet<{ name: string }>(page, "/api/profile");
  expect(before.name, "the demo's person").toBe(ADDRESSEE);
  const id = await letterId(page, FILE);
  try {
    await emptyHousehold(page);
    await apiSend(page, "PUT", "/api/profile", { name: RENAMED });
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });

      // a letter for one person no one of the (empty) household could be: offered, never added by itself
      await open(page, `/documents/${id}`);
      await expect(header(page).getByText(`Addressed to ${ADDRESSEE}`)).toBeVisible();
      const offer = header(page).getByRole("button", { name: `Add ${ADDRESSEE} to your household` });
      await expect(offer).toBeVisible();
      await checkView(page, testInfo, `household-letter-offer-${width}`);
      await offer.click();
      const form = page.getByRole("dialog", { name: "Add to your household" });
      await expect(form.getByRole("textbox", { name: "Name" })).toHaveValue(ADDRESSEE);
      await expect(form.getByRole("checkbox", { name: `Also file this letter for ${ADDRESSEE}` })).toBeChecked();
      await checkView(page, testInfo, `household-add-form-${width}`);
      await form.getByRole("button", { name: "Cancel" }).click();
      await expect(form).toBeHidden();
      expect((await apiGet<Household>(page, "/api/household")).members, "Cancel adds no one").toEqual([]);

      // Settings: the card, empty; two people; an edit's refusal under its field
      await open(page, "/settings?section=profile#set-household", "Settings");
      await expect(card(page).getByText("No one yet.")).toBeVisible();
      await expect(page.locator("#set-household")).toBeFocused();
      await checkView(page, testInfo, `household-settings-empty-${width}`);
      await addPerson(page, ADDRESSEE);
      await addPerson(page, CHILD, false);
      await checkView(page, testInfo, `household-settings-people-${width}`);
      await card(page).getByRole("button", { name: `Edit ${CHILD}` }).click();
      const editing = page.getByRole("form", { name: `Edit ${CHILD}` });
      await editing.getByRole("textbox", { name: "Name" }).fill(RENAMED);
      await editing.getByRole("button", { name: "Save" }).click();
      await expect(editing.getByText(OWN_NAME)).toBeVisible();
      await checkView(page, testInfo, `household-settings-refusal-${width}`);
      await editing.getByRole("button", { name: "Cancel" }).click();

      // the letter asks; Someone else… shows every choice (a sheet on phones); Yes files it with one press
      await open(page, `/documents/${id}`);
      const question = page.getByRole("group", { name: `Is this letter for ${ADDRESSEE}?` });
      await expect(question).toBeVisible();
      await checkView(page, testInfo, `household-letter-question-${width}`);
      await question.getByRole("button", { name: "Someone else…" }).click();
      const choices = page.getByRole("dialog", { name: "Who is this letter for?" });
      await expect(choices.getByRole("button", { name: CHILD })).toBeVisible();
      await checkView(page, testInfo, `household-letter-choices-${width}`);
      await page.keyboard.press("Escape");
      await expect(choices).toBeHidden();
      await question.getByRole("button", { name: "Yes" }).click();
      await expect(header(page).getByText(`For ${ADDRESSEE}`, { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Change who this letter is for" })).toBeFocused();
      await checkView(page, testInfo, `household-letter-filed-${width}`);

      // removing someone with letters asks first
      await open(page, "/settings?section=profile#set-household", "Settings");
      await card(page).getByRole("button", { name: `Remove ${ADDRESSEE}` }).click();
      const removing = page.getByRole("dialog", { name: `Remove ${ADDRESSEE}?` });
      await expect(removing).toContainText("Their 1 letter counts as yours again. Nothing is deleted.");
      await checkView(page, testInfo, `household-settings-remove-${width}`);
      await removing.getByRole("button", { name: "Cancel" }).click();
      await emptyHousehold(page);
    }
  } finally {
    await emptyHousehold(page);
    await apiSend(page, "PUT", "/api/profile", { name: before.name });
  }
  expect((await apiGet<{ name: string }>(page, "/api/profile")).name).toBe(ADDRESSEE);
  expect(await apiGet<Household>(page, "/api/household")).toEqual({ members: [], filed: {}, mine: [], suggested: {}, version: "4f53cda18c2baa0c" });
});
