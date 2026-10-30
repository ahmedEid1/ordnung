/**
 * My numbers per person, where jsdom can't look (ADR 0023): the *People* tab, an *About …* group of someone the person
 * filed letters for, the line that says a number is on another person's letters too, and the *For …* tags on a call
 * sheet's number and an open case — at 320, 375 and 1280 px, light and dark, with axe and the layout sweep's probes.
 *
 * The demo has no household. This spec answers `GET /api/numbers` itself from the demo's own page: its health
 * insurance number and its passport moved to someone with a long name (so a tag is cut with the whole name at hand),
 * the tax ID said to be on their letters too, the health insurer's call-sheet number and the first open case theirs.
 * Nothing of the shared demo changes.
 */
import type { Page, TestInfo } from "@playwright/test";
import type { NumbersPage } from "@/api/types";
import { layoutFindings, type Finding } from "../scripts/ui-audit/probes.mjs";
import { expect, expectAccessible, open, settle, setTour, test } from "./helpers";

/** Someone of the household with a long name. */
const LONG = { id: "hhm_e2elong00001", name: "Alexandra Maria Rivera-Hernández von Musterstadt" };
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

/** `GET /api/numbers` answers the demo's page with {@link LONG}'s numbers taken out of it (module comment). */
async function answerNumbers(page: Page): Promise<void> {
  let answered = false;
  await page.route(
    (url) => url.pathname === "/api/numbers",
    async (route) => {
      const real = (await (await route.fetch()).json()) as NumbersPage;
      const health = real.about_you.find((n) => n.kind === "health_insurance")!;
      const tax = real.about_you.find((n) => n.kind === "tax_id")!;
      const passport = real.documents.find((d) => d.kind === "passport")!;
      const [found] = real.open_cases;
      const theirs = { ...health, key: `${health.key}-long` };
      const answer: NumbersPage = {
        ...real,
        about_you: real.about_you.filter((n) => n !== health),
        documents: real.documents.filter((d) => d !== passport),
        household: [{ ...LONG, about: [theirs], documents: [{ ...passport, key: `${passport.key}-long`, number: passport.number ? { ...passport.number, key: `${passport.number.key}-long` } : null }] }],
        filed_for: { [health.key]: LONG.id, [found!.key]: LONG.id },
        also_for: { [tax.key]: [LONG.id] },
      };
      answered = true;
      await route.fulfill({ json: answer });
    },
  );
  await open(page, "/numbers", "My numbers");
  expect(answered, "the page was answered").toBe(true);
}

test("My numbers: the People tab, an About group, the also-line and the For tags", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await answerNumbers(page);
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 700 });
    await open(page, "/numbers", "My numbers");
    const main = page.getByRole("main");

    // the first tab is People, one word on every screen; the person's own sections, then the About group
    const people = main.getByRole("tab", { name: /^People/ });
    await expect(people).toHaveAttribute("aria-selected", "true");
    await expect(main.getByRole("tab", { name: /About you/ })).toHaveCount(0);
    const about = main.getByRole("region", { name: new RegExp(`About ${LONG.name}`) });
    await expect(about.getByText(`From letters you filed for ${LONG.name}.`)).toBeVisible();
    const list = about.getByRole("list", { name: `Numbers for ${LONG.name}` });
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(about.getByRole("list", { name: `Documents for ${LONG.name}` }).getByRole("heading", { name: "Passport" })).toBeVisible();
    // their number hidden until Show, like the person's
    const show = list.getByRole("button", { name: /^Show / });
    await show.click();
    await expect(list.getByRole("button", { name: /^Hide / })).toBeVisible();
    // the tax ID: on the other person's letters too
    const yours = main.getByRole("region", { name: /Your numbers/ });
    await expect(yours.getByText(`Also on letters for ${LONG.name} — check whose it is`)).toBeVisible();
    await checkView(page, testInfo, `numbers-people-${width}`);

    // Organisations: the health insurer's number and the case are theirs, each tag inside its card with the whole name
    // at hand
    await open(page, "/numbers?tab=organisations", "My numbers");
    const tags = main.locator("article [data-person-tag]");
    await expect(tags.first()).toBeVisible();
    expect(await tags.count(), "the insurer's number and the case on its organisation's card").toBe(2);
    for (const tag of await tags.all()) {
      await expect(tag).toHaveAttribute("title", `For ${LONG.name}`);
      const inCard = await tag.evaluate((el) => {
        const box = el.closest("article")!.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        return r.left >= box.left - 0.5 && r.right <= box.right + 0.5;
      });
      expect(inCard, "the tag stays inside its card").toBe(true);
    }
    await checkView(page, testInfo, `numbers-people-organisations-${width}`);

    // Open cases: the case's tag under its title
    await open(page, "/numbers?tab=cases", "My numbers");
    const caseTag = main.locator("article [data-person-tag]");
    await expect(caseTag).toHaveCount(1);
    await expect(caseTag).toHaveAttribute("title", `For ${LONG.name}`);
    await checkView(page, testInfo, `numbers-people-cases-${width}`);
  }
});
