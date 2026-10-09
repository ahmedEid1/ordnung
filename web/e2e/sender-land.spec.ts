/**
 * A sender's state, suggested from the postcode on their letter (ADR 0019), against the real demo. The letters of
 * FunkNetz and TechMarkt show Berlin postcodes, so their details ask "Is … in Berlin? (… on their letter)": above an
 * unchosen State picker, with Yes never focused by itself, fitting a 320 px phone and passing axe in light and dark.
 * No demo date waits for a state (the person's own town is kept quiet), so the letter's "Please check" card and the
 * Idea on Today are served with `page.route`. Yes on the demo itself is set back in `finally`: later specs see the
 * dates as they were.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { apiGet, apiPatch, expect, expectAccessible, open, settle, setTour, test } from "./helpers";

interface PartyRow {
  id: string;
  name: string;
  region: string | null;
}

interface RegionSuggestion {
  region: string;
  postcode: string;
  doc_id: string;
  waiting: number;
  may_be_late: boolean;
  idea_id: string | null;
  declined: boolean;
}

interface PartyDetail {
  party: PartyRow;
  region_suggestion: RegionSuggestion | null;
}

/** The demo senders whose details ask (the postcode on their letters is in Berlin, not the person's own town). */
const ASKED = ["FunkNetz Mobil GmbH", "TechMarkt Online GmbH"] as const;
type Asked = (typeof ASKED)[number];

const question = (name: Asked, postcode: string) => `Is ${name} in Berlin? (${postcode} on their letter)`;

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** A sender the demo asks about: their details as the API gives them, the question and the state still unset. */
async function asked(page: Page, name: Asked): Promise<{ party: PartyRow; suggestion: RegionSuggestion }> {
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  const row = parties.find((p) => p.name === name);
  expect(row, `${name} is a demo sender`).toBeTruthy();
  const detail = await apiGet<PartyDetail>(page, `/api/parties/${row!.id}`);
  expect(detail.party.region, `${name}'s state is not set in the demo`).toBeNull();
  expect(detail.region_suggestion, `the postcode on ${name}'s letter suggests Berlin, and no demo date waits for it`).toMatchObject({
    region: "BE",
    waiting: 0,
    idea_id: null,
  });
  return { party: detail.party, suggestion: detail.region_suggestion! };
}

/** Layout faults inside the open drawer (as `party-drawer-layout.spec.ts` checks every drawer). */
function drawerFaults(page: Page) {
  return page.evaluate(() => {
    const dlg = document.querySelector<HTMLElement>('[role="dialog"]')!;
    const box = dlg.getBoundingClientRect();
    const faults: string[] = [];
    const describe = (el: Element) => `${el.tagName.toLowerCase()} "${(el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 40)}"`;
    if (document.documentElement.scrollWidth > window.innerWidth) faults.push(`page scrolls sideways (${document.documentElement.scrollWidth}px)`);
    for (const el of Array.from(dlg.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || el.closest(".sr-only") || !el.checkVisibility()) continue;
      if (r.right > box.right + 1 || r.left < box.left - 1) faults.push(`sticks out: ${describe(el)} ${Math.round(r.left)}–${Math.round(r.right)}`);
      if (el.matches("a[href], button, summary") && r.height < 24 && r.width < 24) faults.push(`small target: ${describe(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
    }
    return faults;
  });
}

for (const width of [320, 390]) {
  test(`at ${width} px FunkNetz's and TechMarkt's details ask with the postcode, the picker unchosen and Yes not focused`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/");
    for (const name of ASKED) {
      const { party, suggestion } = await asked(page, name);
      await page.goto(`/?party=${party.id}`);
      const drawer = page.getByRole("dialog", { name });
      const group = drawer.getByRole("group", { name: question(name, suggestion.postcode) });
      await expect(group).toBeVisible();
      await expect(group).toContainText("Their state's public holidays can move the dates in their letters.");
      await expect(group.getByRole("button")).toHaveText(["Yes", "Other state…"]);
      await settle(page);
      await expect(group.getByRole("button", { name: "Yes" })).not.toBeFocused();
      await expect(drawer.getByLabel("Which state is this sender in?")).toHaveValue("");
      expect(await drawerFaults(page), `${name} at ${width} px`).toEqual([]);
    }
  });
}

test("the asking drawers pass axe in light and dark", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.evaluate((t) => localStorage.setItem("ordnung.theme", t), scheme);
    for (const name of ASKED) {
      const { party, suggestion } = await asked(page, name);
      await page.goto(`/?party=${party.id}`);
      await expect(page.getByRole("dialog", { name }).getByRole("group", { name: question(name, suggestion.postcode) })).toBeVisible();
      await settle(page);
      const results = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(
        results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
        `${name} (${scheme})`,
      ).toEqual([]);
    }
  }
});

test("opened to answer, the State heading has the keyboard; Tab goes to Yes, Other state… and the picker; Other state… focuses it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const { party, suggestion } = await asked(page, "TechMarkt Online GmbH");
  await page.goto(`/?party=${party.id}&state=ask`);
  const drawer = page.getByRole("dialog", { name: party.name });
  const group = drawer.getByRole("group", { name: question("TechMarkt Online GmbH", suggestion.postcode) });
  await expect(drawer.getByRole("heading", { name: "State" })).toBeFocused();
  // read once: the address bar no longer asks
  await expect(page).toHaveURL(new RegExp(`\\?party=${party.id}$`));
  await page.keyboard.press("Tab");
  await expect(group.getByRole("button", { name: "Yes" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(group.getByRole("button", { name: "Other state…" })).toBeFocused();
  await page.keyboard.press("Tab");
  const picker = drawer.getByLabel("Which state is this sender in?");
  await expect(picker).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Enter");
  await expect(picker).toBeFocused();
  await expect(group).toHaveCount(0);
  await expect(picker).toHaveValue("");
});

test("Yes saves Berlin on the demo and the State heading takes the keyboard; the toast's Undo, once the drawer is closed, sets it back", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const { party, suggestion } = await asked(page, "FunkNetz Mobil GmbH");
  const region = async () => (await apiGet<PartyDetail>(page, `/api/parties/${party.id}`)).party.region;
  try {
    await page.goto(`/?party=${party.id}`);
    const drawer = page.getByRole("dialog", { name: party.name });
    const group = drawer.getByRole("group", { name: question("FunkNetz Mobil GmbH", suggestion.postcode) });
    const picker = drawer.getByLabel("Which state is this sender in?");
    await group.getByRole("button", { name: "Yes" }).click();
    await expect(group).toHaveCount(0);
    await expect(picker).toHaveValue("BE");
    // not the picker, which saves on change: an arrow key there would save a state nobody chose
    await expect(drawer.getByRole("heading", { name: "State" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(picker).toHaveValue("BE");
    await expect.poll(region).toBe("BE");
    // a toast waits behind a drawer (it never covers its buttons): closed, its Undo is there
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    const saved = page.locator("li[data-toast]").filter({ hasText: `Saved: ${party.name} is in Berlin` });
    await expect(saved).toContainText("Their dates now skip the public holidays of Berlin.");
    await saved.getByRole("button", { name: "Undo" }).click();
    await expect.poll(region).toBeNull();
    // not known again: asked again
    await page.goto(`/?party=${party.id}`);
    await expect(group).toBeVisible();
    await expect(picker).toHaveValue("");
  } finally {
    await apiPatch(page, `/api/parties/${party.id}`, { region: null });
  }
});

test("a letter one of whose dates may change asks on a “Please check” card: Yes takes the keyboard to the verdict, Other state… to their picker", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await open(page, "/");
  const { party, suggestion } = await asked(page, "TechMarkt Online GmbH");
  const id = suggestion.doc_id;
  // the letter as the API serves one of its dates waiting for the state; Yes is answered here, so the demo keeps its state
  let confirmed = false;
  await page.route(
    (url) => url.pathname === `/api/documents/${id}`,
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const response = await route.fetch();
      const detail = (await response.json()) as { party: PartyRow };
      const region_suggestion = confirmed ? null : { ...suggestion, waiting: 1 };
      await route.fulfill({ response, json: { ...detail, party: { ...detail.party, region: confirmed ? "BE" : null }, region_suggestion } });
    },
  );
  await page.route(
    (url) => url.pathname === `/api/parties/${party.id}`,
    async (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      const { region } = route.request().postDataJSON() as { region: string | null };
      confirmed = region === "BE";
      await route.fulfill({ json: { ...party, region } });
    },
  );
  await open(page, `/documents/${id}`);
  const group = page.getByRole("group", { name: question("TechMarkt Online GmbH", suggestion.postcode) });
  await expect(group).toBeVisible();
  await expect(group).toContainText("Their state's public holidays may move this letter's dates.");
  await expect(page.locator("#letter-warnings #check-land")).toHaveText("Please check");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "no sideways scroll at 320 px").toBe(true);
  const box = (await group.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(320);
  for (const button of await group.getByRole("button").all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(24);
  await expectAccessible(page, testInfo, "sender-land-card-320");

  // Other state…: their details at the picker; closed, the keyboard is back on the button
  await group.getByRole("button", { name: "Other state…" }).click();
  const drawer = page.getByRole("dialog", { name: party.name });
  await expect(drawer.getByLabel("Which state is this sender in?")).toBeFocused();
  await expect(page).not.toHaveURL(/state=/);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(group.getByRole("button", { name: "Other state…" })).toBeFocused();

  await group.getByRole("button", { name: "Yes" }).click();
  await expect(page.locator("#verdict-title")).toBeFocused();
  await expect(page.getByText(`Saved: ${party.name} is in Berlin`)).toBeVisible();
  await expect(group).toHaveCount(0);
  expect((await apiGet<PartyDetail>(page, `/api/parties/${party.id}`)).party.region, "the demo keeps its state").toBeNull();
});

test("“Answer” on the Idea opens their details at the State heading, never on Yes", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, "/");
  const { party, suggestion } = await asked(page, "TechMarkt Online GmbH");
  const title = "Is TechMarkt Online GmbH in Berlin?";
  // the Idea as the API words it (`secretary.sender_land`) when one of their dates waits for the state
  await page.route(
    (url) => url.pathname === "/api/dashboard",
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const response = await route.fetch();
      const dash = (await response.json()) as { suggestions: Record<string, unknown>[] };
      const idea = {
        ...dash.suggestions[0],
        id: "sug_e2e_sender_land",
        kind: "deadline",
        title,
        body: `${suggestion.postcode} is on their letter. Their state's public holidays may change 1 of your dates with them; until you answer, Ordnung counts only nationwide holidays, so it may be a day or two early.`,
        rationale: null,
        priority: "high",
        status: "new",
        source: "rule",
        rule_id: "sender_land",
        savings_estimate: null,
        due_date: null,
        snoozed_until: null,
        refs: [
          { type: "party", id: party.id },
          { type: "document", id: suggestion.doc_id },
        ],
        action: { type: "open", draft_kind: null, target_type: "party", target_id: party.id, label: "Answer" },
      };
      await route.fulfill({ response, json: { ...dash, suggestions: [idea, ...dash.suggestions] } });
    },
  );
  await open(page, "/");
  const ideas = page.getByRole("region", { name: "Ideas from your secretary" });
  const heading = ideas.getByRole("heading", { level: 3, name: title });
  await expect(ideas.getByRole("article").first()).toBeVisible();
  const more = ideas.getByRole("button", { name: /^Show \d+ more Ideas?$/ });
  if (!(await heading.isVisible()) && (await more.isVisible())) await more.click();
  await ideas
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { level: 3, name: title }) })
    .getByRole("button", { name: "Answer" })
    .click();
  const drawer = page.getByRole("dialog", { name: party.name });
  await expect(drawer.getByRole("heading", { name: "State" })).toBeFocused();
  await expect(drawer.getByRole("group", { name: question("TechMarkt Online GmbH", suggestion.postcode) })).toBeVisible();
  await expect(page).not.toHaveURL(/state=/);
  await page.keyboard.press("Tab");
  await expect(drawer.getByRole("button", { name: "Yes" })).toBeFocused();
});
