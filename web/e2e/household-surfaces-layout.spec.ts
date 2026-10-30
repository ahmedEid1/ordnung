/**
 * Whose letter it is, on Today, the Timeline and in the composer, where jsdom can't look (ADR 0023): the "For …" tag
 * of a Top 3 card, "For … · " at the start of a Coming-up row, of a recent letter and of a Timeline row (never a
 * contract's), no filter on Today or the Timeline, and the composer's From field for a letter filed for someone who
 * signs their own letters and for someone who doesn't — at 320, 375 and 1280 px, light and dark, with axe and the
 * layout sweep's probes.
 *
 * The demo has no household, and its letters are all addressed to its persona. This spec answers `GET /api/household`
 * itself (every letter filed for someone with a long name, so a tag is cut with the whole name at hand; the library's
 * reminder for a child who doesn't sign), so nothing of the shared demo changes and nothing is drafted.
 */
import type { Page, TestInfo } from "@playwright/test";
import type { Household } from "@/api/types";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { apiGet, expect, expectAccessible, letterId, open, settle, setTour, test, type Letter } from "./helpers";

/** Someone of the household who signs their own letters, with a long name. */
const LONG = { id: "hhm_e2elong00001", name: "Alexandra Maria Rivera-Hernández von Musterstadt", signs: true };
/** A child, who doesn't sign letters. */
const CHILD = { id: "hhm_e2echild0001", name: "Mia Rivera", signs: false };
/** A letter to answer, filed for {@link LONG}: the operating-cost statement. */
const REPLY = "13_nebenkostenabrechnung_2025.pdf";
/** A letter to answer, filed for {@link CHILD}: the library's reminder. */
const CHILDS = "20_stadtbibliothek_mahnung.pdf";
const WIDTHS = [320, 375, 1280] as const;
const THEMES = ["light", "dark"] as const;

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

/** `GET /api/household` answers: every letter filed for {@link LONG}, the library's reminder for {@link CHILD}. */
async function answerHousehold(page: Page): Promise<{ reply: string; childs: string }> {
  const letters = await apiGet<Letter[]>(page, "/api/documents");
  const reply = await letterId(page, REPLY);
  const childs = await letterId(page, CHILDS);
  const filed = Object.fromEntries(letters.map((d) => [d.id, d.id === childs ? CHILD.id : LONG.id]));
  const household: Household = {
    members: [
      { ...LONG, letters: letters.length - 1 },
      { ...CHILD, letters: 1 },
    ],
    filed,
    mine: [],
    suggested: {},
    version: "0123456789abcdef",
  };
  await page.route(
    (url) => url.pathname === "/api/household",
    (route) => (route.request().method() === "GET" ? route.fulfill({ json: household }) : route.fallback()),
  );
  return { reply, childs };
}

test("Today: whose letter it is on Top 3, Coming up and Recent letters, and no filter", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await answerHousehold(page);
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });
    await open(page, "/", /Sam/);
    const main = page.getByRole("main");

    // Top 3: the badge under the title, cut inside its card with the whole name in its title
    const tags = main.getByRole("region", { name: "Top 3 this week" }).locator("[data-person-tag]");
    await expect(tags.filter({ hasText: `For ${LONG.name}` }).first()).toBeVisible();
    for (const tag of await tags.all()) {
      const title = await tag.getAttribute("title");
      expect([`For ${LONG.name}`, `For ${CHILD.name}`]).toContain(title);
      await expect(tag).toHaveText(title!);
      const inCard = await tag.evaluate((el) => {
        const card = el.closest("article")!.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        return r.left >= card.left && r.right <= card.right;
      });
      expect(inCard, "the tag stays inside its card").toBe(true);
    }

    // Coming up: the row's second line starts with whose letter it is
    const coming = main.getByRole("region", { name: /Coming up/ });
    await expect(coming.locator("[data-part=meta]").filter({ hasText: `For ${LONG.name}` }).first()).toBeVisible();

    // no filter of whose letters on Today
    await expect(main.getByRole("combobox", { name: /Whose letters/ })).toHaveCount(0);
    await expect(main.locator('a[href*="for="]')).toHaveCount(0);
    await checkView(page, testInfo, `household-today-${width}`);

    // Recent letters, opened: the tag starts a letter's second line
    await main.getByRole("button", { name: /^Recent letters/ }).click();
    const recent = main.getByRole("region", { name: /^Recent letters/ });
    await expect(recent.getByText(new RegExp(`^For ${LONG.name}`)).first()).toBeVisible();
    await recent.scrollIntoViewIfNeeded();
    await checkView(page, testInfo, `household-today-recent-${width}`);
  }
});

test("Timeline: whose letter a date comes from, at 320, 375 and 1280 px, light and dark", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  // only two letters filed: the operating-cost statement for LONG, the library's reminder for CHILD
  const reply = await letterId(page, REPLY);
  const childs = await letterId(page, CHILDS);
  const household: Household = {
    members: [
      { ...LONG, letters: 1 },
      { ...CHILD, letters: 1 },
    ],
    filed: { [reply]: LONG.id, [childs]: CHILD.id },
    mine: [],
    suggested: {},
    version: "0123456789abcdef",
  };
  await page.route(
    (url) => url.pathname === "/api/household",
    (route) => (route.request().method() === "GET" ? route.fulfill({ json: household }) : route.fallback()),
  );
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });
    await open(page, "/timeline", "Timeline");
    const list = page.getByRole("region", { name: "Every date" });
    const rows = list.locator("li[data-entry-id]");
    // a to-do from each filed letter starts its second line with whose letter it is, the whole line in its title
    for (const name of [LONG.name, CHILD.name]) {
      const line = rows.locator(`[title^="For ${name} · "]`).first();
      await expect(line).toBeVisible();
      await expect(line).toHaveText(new RegExp(`^For ${name} · `));
    }
    // a contract's dates name no one, and there is no filter of whose letters
    const contracts = rows.filter({ has: page.locator('a[href^="/contracts"]') });
    expect(await contracts.count(), "the demo's contracts are on the Timeline").toBeGreaterThan(0);
    await expect(contracts.filter({ hasText: /For (Alexandra|Mia) / })).toHaveCount(0);
    await expect(page.getByRole("main").getByRole("combobox", { name: /Whose letters/ })).toHaveCount(0);
    await rows.locator(`[title^="For ${LONG.name} · "]`).first().scrollIntoViewIfNeeded();
    await checkView(page, testInfo, `household-timeline-${width}`);
  }
});

test("the composer's From field: filed for someone who signs, and for a child who doesn't", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const drafts = (await apiGet<unknown[]>(page, "/api/drafts")).length;
  const { reply, childs } = await answerHousehold(page);
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });

    // someone who signs: the person's own name first, theirs (as typed in Settings) one press away
    await open(page, `/letters?kind=general_reply&doc=${reply}`);
    let dialog = page.getByRole("dialog", { name: "New letter" });
    let from = dialog.getByRole("textbox", { name: "From" });
    await expect(from).toHaveValue("Sam Rivera");
    await expect(from).toHaveAccessibleDescription(`This letter is filed for ${LONG.name}.`);
    const theirs = dialog.getByRole("button", { name: `Reply in ${LONG.name}'s name` });
    await expect(theirs).toBeVisible();
    await from.scrollIntoViewIfNeeded();
    await checkView(page, testInfo, `household-composer-signs-${width}`);
    await theirs.click();
    await expect(from).toHaveValue(LONG.name);
    await expect(from).toHaveAccessibleDescription(`This letter is filed for ${LONG.name}. It goes out in the name of ${LONG.name}, who signs it.`);
    await expect(dialog.getByRole("button", { name: "Use my name" })).toBeFocused();
    await checkView(page, testInfo, `household-composer-theirs-${width}`);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();

    // a child: the letter goes out in the person's name, with no offer of the child's
    await open(page, `/letters?kind=general_reply&doc=${childs}`);
    dialog = page.getByRole("dialog", { name: "New letter" });
    from = dialog.getByRole("textbox", { name: "From" });
    await expect(from).toHaveValue("Sam Rivera");
    await expect(from).toHaveAccessibleDescription(`This letter is filed for ${CHILD.name}, who doesn't sign letters, so it goes out in your name.`);
    await expect(dialog.getByRole("button", { name: /^Reply in / })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Use my name" })).toHaveCount(0);
    await from.scrollIntoViewIfNeeded();
    await checkView(page, testInfo, `household-composer-child-${width}`);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  }
  expect(await apiGet<unknown[]>(page, "/api/drafts"), "nothing was drafted").toHaveLength(drafts);
});
