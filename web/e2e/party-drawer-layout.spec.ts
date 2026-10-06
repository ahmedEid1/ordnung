/**
 * The People & organisations drawer against the real demo, at a 320 px phone and a 1280 px laptop:
 * nothing sticks out of the drawer, no countdown pill covers the date or the amount, the footer
 * fits, targets are at least 24 px, the numbers are a valid definition list (axe), replaced and
 * past to-dos are set apart, closing it goes back in the history, and opened from "Why this date?" on a phone
 * the keyboard reaches its State picker.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { MyNumber } from "@/api/types";
import { numberTitle } from "@/features/numbers/title";
import { apiGet, expect, expectAccessible, letterId, letterItem, open, setTour, settle, shownAs, test } from "./helpers";

interface PartyRow {
  id: string;
  name: string;
}

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function openDrawer(page: Page, party: PartyRow) {
  await page.goto(`/?party=${party.id}`);
  const drawer = page.getByRole("dialog", { name: party.name });
  await expect(drawer.getByRole("heading", { level: 3 }).first()).toBeVisible();
  await settle(page);
  return drawer;
}

/** Layout faults inside the open drawer, over its whole scroll height. */
function drawerFaults(page: Page) {
  return page.evaluate(() => {
    const dlg = document.querySelector<HTMLElement>('[role="dialog"]')!;
    const box = dlg.getBoundingClientRect();
    const faults: string[] = [];
    const describe = (el: Element) => `${el.tagName.toLowerCase()} "${(el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 40)}"`;
    if (document.documentElement.scrollWidth > window.innerWidth) faults.push(`page scrolls sideways (${document.documentElement.scrollWidth}px)`);
    // what is on screen: not the content of a closed <details> ("Their own numbers"), which Chromium
    // lays out, unpainted, over what follows
    const shown = (el: Element) => el.checkVisibility();
    for (const el of Array.from(dlg.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || el.closest(".sr-only") || !shown(el)) continue;
      if (r.right > box.right + 1 || r.left < box.left - 1) faults.push(`sticks out: ${describe(el)} ${Math.round(r.left)}–${Math.round(r.right)}`);
      if (el.matches("a[href], button, summary") && r.height < 24 && r.width < 24) faults.push(`small target: ${describe(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
    }
    const pills = Array.from(dlg.querySelectorAll("time.rounded-full"));
    const texts = Array.from(dlg.querySelectorAll("span, time, p")).filter((e) => !e.children.length && (e.textContent ?? "").trim() && !pills.some((p) => p.contains(e)) && shown(e));
    for (const pill of pills) {
      const a = pill.getBoundingClientRect();
      for (const t of texts) {
        const b = t.getBoundingClientRect();
        const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (w > 1 && h > 1) faults.push(`pill "${pill.textContent}" covers "${t.textContent}"`);
      }
    }
    return faults;
  });
}

for (const width of [320, 1280]) {
  test(`every party drawer fits at ${width} px`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height: 800 });
    await open(page, "/");
    const parties = await apiGet<PartyRow[]>(page, "/api/parties");
    expect(parties.length).toBeGreaterThan(5);
    for (const party of parties) {
      const drawer = await openDrawer(page, party);
      // as it opens, then with every fold open ("Their own numbers", "Older or replaced")
      for (const folds of ["closed", "open"]) {
        if (folds === "open") await drawer.locator("details").evaluateAll((all) => all.forEach((d) => ((d as HTMLDetailsElement).open = true)));
        // unroll the drawer's scroll area so every row is laid out on screen
        const extra = await drawer.locator(".overflow-y-auto").evaluate((el) => el.scrollHeight - el.clientHeight);
        await page.setViewportSize({ width, height: 800 + extra });
        await settle(page);
        expect(await drawerFaults(page), `${party.name} (folds ${folds})`).toEqual([]);
        await page.setViewportSize({ width, height: 800 });
      }
    }
  });
}

test("the drawer passes axe in light and dark (numbers are a valid list)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.evaluate((t) => localStorage.setItem("ordnung.theme", t), scheme);
    for (const name of ["TechMarkt Online GmbH", "Wohnbau Musterstadt eG"]) {
      await openDrawer(page, parties.find((p) => p.name === name)!);
      const results = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(
        results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
        `${name} (${scheme})`,
      ).toEqual([]);
    }
  }
});

test("a payment the reminder took over is set apart, not listed as overdue", async ({ page }) => {
  await open(page, "/");
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  const drawer = await openDrawer(page, parties.find((p) => p.name === "TechMarkt Online GmbH")!);
  const todos = drawer.getByRole("region", { name: /To-dos & dates/ });
  const listed = todos.getByRole("list").first();
  // the reminder's payment and the invoice's it took over, by their letters' files: the to-dos' titles are the
  // model's, read from the API (prompt 11's invoice payment no longer names the invoice number)
  const reminder = await letterItem(page, await letterId(page, "15_mahnung_techmarkt.pdf"), "payment");
  const invoice = await letterItem(page, await letterId(page, "08_rechnung_techmarkt.pdf"), "payment");
  await expect(listed).toContainText(shownAs(reminder.title));
  await expect(listed).not.toContainText(shownAs(invoice.title));
  await expect(todos).not.toContainText("overdue");
  await todos.getByText(/Older or replaced · 1/).click();
  const replaced = todos.locator("details").getByRole("listitem");
  await expect(replaced).toHaveCount(1);
  await expect(replaced).toContainText(shownAs(invoice.title));
  await expect(replaced).toContainText("Replaced by the payment reminder of Thu 10 Sep — pay that one, not both.");
});

const CLIENT = { "X-Ordnung-Client": "web" };

test("the drawer's numbers are My numbers': English names, hidden until Show, their own set apart", async ({ page }) => {
  // UI audit R2-party-numbers-3: the drawer listed the raw labels in full, the creditor's own ID as "yours"
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  type Sheet = { party_id: string; numbers: MyNumber[]; their_numbers: MyNumber[] };
  const numbers = await apiGet<{ organisations: Sheet[] }>(page, "/api/numbers");
  const sheet = numbers.organisations.find((s) => /FunkNetz/.test(parties.find((p) => p.id === s.party_id)?.name ?? ""))!;
  const party = parties.find((p) => p.id === sheet.party_id)!;
  const drawer = await openDrawer(page, party);
  const region = drawer.getByRole("region", { name: "Your numbers with them" });
  // each by the title My numbers gives it (`numberTitle`): the English name, or the letter's own label where the
  // name is generic — prompt 11 reads FunkNetz's register entry as "Handelsregister", which says which register
  for (const n of sheet.numbers) {
    await expect(region.getByText(numberTitle(n), { exact: true })).toBeVisible();
    await expect(region.getByText(n.display, { exact: true })).toHaveCount(0); // hidden until Show
  }
  await region.getByRole("button", { name: `Show ${numberTitle(sheet.numbers[0]!)}` }).click();
  await expect(region.getByText(sheet.numbers[0]!.display, { exact: true })).toBeVisible();
  const theirs = sheet.their_numbers.filter((n) => n.kind !== "iban");
  expect(theirs.map((n) => n.kind), "FunkNetz's own numbers on its letters").toEqual(expect.arrayContaining(["vat_id", "register", "creditor_id"]));
  await region.getByText(/^Their own numbers/).click();
  for (const n of theirs) await expect(region.locator("details").getByText(numberTitle(n), { exact: true })).toBeVisible();
  expect(await drawerFaults(page)).toEqual([]);
});

test("a half-written call note is kept, and closing asks first: “Keep writing” goes back to it, “Discard” closes", async ({ page }) => {
  // UI audit R2-party-numbers-1: Escape, the backdrop or × threw the note away unasked
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  const party = parties.find((p) => p.name === "Wohnbau Musterstadt eG")!;
  const drawer = await openDrawer(page, party);
  const calls = drawer.getByRole("region", { name: /^Calls/ });
  await calls.getByRole("button", { name: "Note a call" }).click();
  const form = calls.getByRole("form", { name: "Note a call" });
  await form.getByLabel("What was said").fill("They will send someone to look at the heating on Monday.");
  await page.keyboard.press("Escape");
  const ask = form.getByRole("group", { name: /Discard this call note\?/ });
  await expect(ask).toBeVisible();
  await expect(ask.getByRole("button", { name: "Keep writing" })).toBeFocused();
  await expect(page).toHaveURL(/\?party=/);
  await settle(page);
  expect(await drawerFaults(page)).toEqual([]);
  await ask.getByRole("button", { name: "Keep writing" }).click();
  await expect(form.getByLabel("What was said")).toBeFocused();
  // a reload keeps it too
  await page.reload();
  await expect(drawer.getByRole("region", { name: /^Calls/ }).getByLabel("What was said")).toHaveValue("They will send someone to look at the heating on Monday.");
  // × asks as well; "Discard" closes, and the note is gone
  await drawer.getByRole("button", { name: "Close" }).first().click();
  await drawer.getByRole("group", { name: /Discard this call note\?/ }).getByRole("button", { name: "Discard" }).click();
  await expect(drawer).toBeHidden();
  await openDrawer(page, party);
  await expect(calls.getByRole("button", { name: "Note a call" })).toBeVisible();
  await expect(calls.getByRole("form")).toHaveCount(0);
});

test("call notes keep the keyboard in the drawer: the bin's question, “Keep it”, “They kept it”", async ({ page }) => {
  // UI audit R2-party-numbers-2: focus fell to <body> after "They kept it" and "Keep it"
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/");
  const parties = await apiGet<PartyRow[]>(page, "/api/parties");
  const party = parties.find((p) => p.name === "Wohnbau Musterstadt eG")!;
  const made = await page.request.post("/api/calls", {
    data: { party_id: party.id, called_on: "2026-09-24", summary: "Asked about the heating (UI check).", promise: "A technician's visit", promise_due: "2026-10-02" },
    headers: CLIENT,
  });
  expect(made.status(), "note the call").toBe(201);
  const noteId = ((await made.json()) as { id: string }).id;
  try {
    const drawer = await openDrawer(page, party);
    // the calls have a jump link of their own, after the to-dos
    await drawer.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /^\d+ calls?$/ }).click();
    const calls = drawer.getByRole("region", { name: /^Calls/ });
    await expect(calls.getByRole("heading", { name: /^Calls/ })).toBeFocused();
    const note = calls.getByRole("listitem").filter({ hasText: "Asked about the heating (UI check)." });
    await note.getByRole("button", { name: "They kept it" }).focus();
    await page.keyboard.press("Enter");
    await expect(note.getByRole("button", { name: "Not kept after all" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(note.getByRole("button", { name: "They kept it" })).toBeFocused();
    const bin = note.getByRole("button", { name: /^Delete the note/ });
    await bin.focus();
    await page.keyboard.press("Enter");
    const ask = note.getByRole("group", { name: "Delete this note?" });
    await expect(ask.getByRole("button", { name: "Delete" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(ask.getByRole("button", { name: "Keep it" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(ask).toHaveCount(0);
    await expect(bin).toBeFocused();
  } finally {
    await page.request.delete(`/api/calls/${noteId}`, { headers: CLIENT });
  }
});

test("closing a drawer opened from a chip goes back, so Back then leaves the page", async ({ page }) => {
  await open(page, "/inbox");
  await open(page, "/");
  await page.getByRole("button", { name: /TechMarkt Online GmbH — open details/ }).first().click();
  const drawer = page.getByRole("dialog", { name: "TechMarkt Online GmbH" });
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/\?party=/);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/\/$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/inbox$/);
});

/** The rules engine's warning for a Land authority's letter whose Land isn't known (`rules.delivery`). */
const THREE_DAYS =
  "Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this sender's, so we counted 3 days (the earlier date).";

// Final check of the fix wave: at 390 px "Why this date?" is a modal sheet, and its "Choose their state" opened the
// sender's drawer over it while the sheet kept the keyboard — Tab went round its three buttons, never to the
// drawer's State picker. No demo date waits for a sender's Land (the demo's person lives in a known one), so the
// letter's page is served with one that does: the immigration office's fee, counted without the office's Land.
test("at 390 px, “Choose their state” in “Why this date?” takes the keyboard to the drawer's State picker", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "/");
  const id = await letterId(page, "17_auslaenderbehoerde_termin.pdf");
  const fee = await letterItem(page, id, "payment");
  type Detail = { items: { id: string; computation: { warnings: string[] } | null }[]; party: { name: string; region: string | null } | null };
  const { party } = await apiGet<Detail>(page, `/api/documents/${id}`);
  expect(party, "the immigration office's letter has its sender").toBeTruthy();
  await page.route(
    (url) => url.pathname === `/api/documents/${id}`,
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const response = await route.fetch();
      const detail = (await response.json()) as Detail;
      const items = detail.items.map((item) =>
        item.id === fee.id && item.computation ? { ...item, computation: { ...item.computation, warnings: [...item.computation.warnings, THREE_DAYS] } } : item,
      );
      await route.fulfill({ response, json: { ...detail, items, party: { ...detail.party!, region: null } } });
    },
  );
  await open(page, `/documents/${id}`);
  await page
    .getByRole("region", { name: /To-dos & dates/ })
    .getByRole("button", { name: `Why this date? (${fee.title})` })
    .click();
  const sheet = page.getByRole("dialog", { name: `Why this date? ${fee.title}` });
  await expect(sheet).toHaveAttribute("aria-modal", "true");
  await sheet.getByRole("button", { name: "Choose their state" }).focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: party!.name });
  await expect(drawer).toBeVisible();
  await expect(sheet).toBeHidden();
  await settle(page);
  const picker = drawer.getByLabel("Which state is this sender in?");
  let presses = 0;
  while (presses < 40 && !(await picker.evaluate((el) => el === document.activeElement))) {
    await page.keyboard.press("Tab");
    presses++;
  }
  await expect(picker, `Tab reaches the State picker (${presses} presses)`).toBeFocused();
  await expectAccessible(page, testInfo, "drawer-from-why-this-date-390");
  // closed, the drawer gives the keyboard back to "Why this date?"
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("region", { name: /To-dos & dates/ }).getByRole("button", { name: `Why this date? (${fee.title})` })).toBeFocused();
});
