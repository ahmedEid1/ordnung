/**
 * The moving checklist against the real demo, on a 375 px phone-sized window: the move is told in Settings →
 * Profile ("I moved" appears next to the changed address, with the day moved in), Today then shows the "Moving
 * checklist" card, a row is ticked off and brought back with Undo by keyboard alone (focus moving on to the next
 * row and back), axe passes on the Settings block and the card, nothing scrolls sideways, and "Stop the checklist"
 * ends it. The demo is shared state: `finally` puts the address back and leaves every row of this move expired,
 * so later specs (and the demo's recorded note) see the ledger as it was.
 */
import type { Page } from "@playwright/test";
import { apiGet, apiPatch, apiSend, expect, expectAccessible, open, settle, setTour, test } from "./helpers";

interface Profile {
  address: string;
  moved_on: string | null;
  old_address: string;
}

interface Idea {
  id: string;
  title: string;
  status: string;
  rule_id: string | null;
}

/** The demo's day is Mon 28 Sep 2026: a week before it. */
const MOVED_ON = "2026-09-21";
const NEW_ADDRESS = "Neue Allee 7\n54321 Beispielstadt";
const REGISTER = "Register your new address by Mon 5 Oct";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const movingRows = async (page: Page) => (await apiGet<Idea[]>(page, "/api/suggestions?limit=1000")).filter((s) => s.rule_id === "moved_house");

/** Nothing on the page is wider than the window. */
async function expectNoSidewaysScroll(page: Page, where: string) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide, `${where}: the page scrolls sideways`).toBeLessThanOrEqual(0);
}

/** Every row of this move expired (none ticked, hidden or open), the move cleared and the address put back. */
async function putBack(page: Page, before: Profile) {
  // a ticked or hidden row goes back to open, so the refresh below expires it like every open row
  for (const row of await movingRows(page)) {
    if (row.status !== "new" && row.status !== "expired") await apiPatch(page, `/api/suggestions/${row.id}`, { status: "new" });
  }
  const now = await apiGet<Profile>(page, "/api/profile");
  // the Ideas refresh only when the move changes: tell it once more, then clear it
  if (!now.moved_on) await apiSend(page, "PUT", "/api/profile", { moved_on: MOVED_ON });
  await apiSend(page, "PUT", "/api/profile", { address: before.address, moved_on: "", old_address: before.old_address });
  await expect.poll(async () => (await movingRows(page)).filter((r) => r.status !== "expired").length, { timeout: 20_000 }).toBe(0);
  const after = await apiGet<Profile>(page, "/api/profile");
  expect([after.address, after.moved_on, after.old_address]).toEqual([before.address, before.moved_on, before.old_address]);
}

test("a move told in Settings lists who needs the new address on Today; a row is ticked off and brought back by keyboard", async ({ page }, testInfo) => {
  const before = await apiGet<Profile>(page, "/api/profile");
  expect(before.moved_on, "the demo knows of no move").toBeNull();
  expect(await movingRows(page), "the demo shows no moving rows").toEqual([]);
  await page.setViewportSize({ width: 375, height: 800 });
  try {
    // ---- Settings: "I moved" next to the changed address
    await open(page, "/settings?section=profile", "Settings");
    const address = page.getByLabel("Postal address");
    const moved = page.getByRole("checkbox", { name: /I moved — list who needs my new address/ });
    await expect(moved).toHaveCount(0);
    await address.fill(NEW_ADDRESS);
    await moved.check();
    await page.getByLabel("Moved in on").fill(MOVED_ON);
    await settle(page);
    await expectAccessible(page, testInfo, "settings-i-moved");
    await expectNoSidewaysScroll(page, "Settings with I moved");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Today lists who needs your new address.")).toBeVisible();

    // ---- Today: the card, above the Ideas
    await open(page, "/");
    const card = page.getByRole("region", { name: "Moving checklist" });
    await expect(card).toBeVisible();
    await expect(card.getByRole("heading", { level: 2, name: "Moving checklist" })).toBeVisible();
    const first = card.getByRole("checkbox", { name: REGISTER });
    await expect(first).toBeVisible();
    await settle(page);
    await expectAccessible(page, testInfo, "moving-checklist");
    await expectNoSidewaysScroll(page, "Today with the moving checklist");

    // ---- keyboard only: Space ticks the row off, focus moves on to the next row
    const next = card.getByRole("checkbox").nth(1);
    const nextName = (await next.getAttribute("id"))!;
    await first.focus();
    await page.keyboard.press("Space");
    await expect(card.getByRole("checkbox", { name: REGISTER })).toHaveCount(0);
    await expect(page.locator(`[id="${nextName}"]`)).toBeFocused();
    await expect(page.getByText("Ticked off")).toBeVisible();

    // Alt+N goes to the toast, Tab to its Undo, Enter brings the row back, focused
    await page.keyboard.press("Alt+KeyN");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Undo" })).toBeFocused();
    await page.keyboard.press("Enter");
    const back = card.getByRole("checkbox", { name: REGISTER });
    await expect(back).toBeVisible();
    await expect(back).not.toBeChecked();
    await expect(back).toBeFocused();
    expect((await movingRows(page)).find((r) => r.title === REGISTER)?.status).toBe("new");

    // ---- Settings: the move stands, and "Stop the checklist" ends it
    await open(page, "/settings?section=profile", "Settings");
    await expect(page.getByText(/You moved in on Mon 21 Sep\./)).toBeVisible();
    await expect(page.getByRole("link", { name: "Open your moving checklist" })).toHaveAttribute("href", "/#moving-checklist");
    await expectAccessible(page, testInfo, "settings-move-stands");
    await expectNoSidewaysScroll(page, "Settings with a move told");
    await page.getByRole("button", { name: "Stop the checklist" }).click();
    await expect(page.getByText("Moving checklist stopped")).toBeVisible();
    await expect.poll(async () => (await movingRows(page)).filter((r) => r.status === "new").length, { timeout: 20_000 }).toBe(0);
    await open(page, "/");
    await expect(page.getByRole("region", { name: "Moving checklist" })).toHaveCount(0);
  } finally {
    await putBack(page, before);
  }
});
