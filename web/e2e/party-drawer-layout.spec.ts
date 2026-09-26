/**
 * The People & organisations drawer against the real demo, at a 320 px phone and a 1280 px laptop:
 * nothing sticks out of the drawer, no countdown pill covers the date or the amount, the footer
 * fits, targets are at least 24 px, the numbers are a valid definition list (axe), replaced and
 * past to-dos are set apart, and closing it goes back in the history.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { apiGet, expect, open, setTour, settle, test } from "./helpers";

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
    for (const el of Array.from(dlg.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || el.closest(".sr-only")) continue;
      if (r.right > box.right + 1 || r.left < box.left - 1) faults.push(`sticks out: ${describe(el)} ${Math.round(r.left)}–${Math.round(r.right)}`);
      if (el.matches("a[href], button, summary") && r.height < 24 && r.width < 24) faults.push(`small target: ${describe(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
    }
    const pills = Array.from(dlg.querySelectorAll("time.rounded-full"));
    const texts = Array.from(dlg.querySelectorAll("span, time, p")).filter((e) => !e.children.length && (e.textContent ?? "").trim() && !pills.some((p) => p.contains(e)));
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
      // unroll the drawer's scroll area so every row is laid out on screen
      const extra = await drawer.locator(".overflow-y-auto").evaluate((el) => el.scrollHeight - el.clientHeight);
      await page.setViewportSize({ width, height: 800 + extra });
      await settle(page);
      expect(await drawerFaults(page), party.name).toEqual([]);
      await page.setViewportSize({ width, height: 800 });
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
  await expect(listed).toContainText("Pay outstanding invoice plus reminder fee");
  await expect(listed).not.toContainText("TM-2026-0048213");
  await expect(todos).not.toContainText("overdue");
  await todos.getByText(/Older or replaced · 1/).click();
  await expect(todos.locator("details")).toContainText("Replaced by the payment reminder of Thu 10 Sep — pay that one, not both.");
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
