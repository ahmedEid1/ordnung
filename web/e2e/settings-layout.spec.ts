/**
 * Settings on the real demo, where jsdom can't look (UI audit round 1, settings-b): an edit keeps
 * the save bar in view (above the phone tab bar), the section list moves beside the pane only when
 * the page column has room for both (not at 1024 px next to the app's sidebar), a pill that gets
 * keyboard focus on a phone scrolls fully into view, and the forms (Reminders chips, a profile
 * mistake with the bar pinned) pass axe in both themes.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { expect, expectAccessible, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Is the whole element on screen and the top-most thing at its centre (not scrolled away or covered)? */
async function reachable(l: Locator): Promise<boolean> {
  return l.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return r.top >= 0 && r.bottom <= innerHeight && Boolean(hit && el.contains(hit));
  });
}

async function editReminders(page: Page) {
  await open(page, "/settings?section=reminders", "Settings");
  await page.getByRole("list", { name: "Reminders for deadlines" }).getByRole("button", { name: "Remove reminder 1 day before for deadlines" }).click();
  await settle(page);
}

for (const [width, height] of [
  [390, 844],
  [1280, 800],
]) {
  test(`Reminders at ${width}×${height}: an edit keeps Save in view, wherever you are in the form`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await editReminders(page);
    const main = page.getByRole("main");
    const save = main.getByRole("button", { name: "Save changes" });
    await page.evaluate(() => window.scrollTo(0, 0));
    await settle(page);
    expect(await reachable(save)).toBe(true);
    // above the phone's tab bar
    const tabBar = page.getByRole("navigation", { name: "Primary" }).last();
    if (width < 768) expect((await save.boundingBox())!.y + (await save.boundingBox())!.height).toBeLessThanOrEqual((await tabBar.boundingBox())!.y);
    // a control further down that gets focus scrolls clear of the bar, not just onto the screen behind it
    const later = main.getByRole("button", { name: "Add a reminder for milestones" });
    await later.focus();
    await settle(page);
    expect(await reachable(later)).toBe(true);
    // discarded: the bar goes back to the end of its card
    await main.getByRole("button", { name: "Discard" }).click();
    await expect(main.locator("[data-pinned]")).toHaveCount(0);
    // (the desktop-notification card below has a save bar of its own)
    const card = main.locator("section.card").filter({ has: page.getByRole("list", { name: "Reminders for deadlines" }) });
    await expect(card.getByText("All changes saved")).toBeAttached();
  });
}

for (const [width, height] of [
  [390, 844],
  [1280, 800],
]) {
  test(`Profile at ${width}×${height}: Save and Discard by keyboard leave focus in the card, on the bar's status`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/settings?section=profile", "Settings");
    const main = page.getByRole("main");
    const phone = main.getByLabel(/^Phone/);
    const iban = main.getByLabel(/^IBAN for refunds/);
    const original = await phone.inputValue();
    const status = main.locator("section.card").filter({ has: page.getByLabel(/^Phone/) }).getByRole("status");
    const edit = async () => {
      await phone.focus();
      await page.keyboard.press("End");
      await page.keyboard.type("9");
    };

    // Discard: the buttons go at once — focus stays on what the bar says, visibly and on screen
    await edit();
    await main.getByRole("button", { name: "Discard" }).focus();
    await page.keyboard.press("Enter");
    await expect(phone).toHaveValue(original);
    await expect(status).toBeFocused();
    expect(await status.evaluate((el) => el.matches(":focus-visible"))).toBe(true);
    await settle(page);
    expect(await reachable(status)).toBe(true);
    // Tab goes on from the card (round 2: focus fell to <body>, the next Tab to "Skip to content")
    await page.keyboard.press("Shift+Tab");
    await expect(iban).toBeFocused();

    // Save: "Saved. …" holds the focus
    await edit();
    await main.getByRole("button", { name: "Save changes" }).focus();
    await page.keyboard.press("Enter");
    await expect(status).toContainText("Saved.");
    await expect(status).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(iban).toBeFocused();

    // back as it was, for the other tests
    await phone.fill(original);
    await main.getByRole("button", { name: "Save changes" }).click();
    await expect(status).toContainText("Saved.");
  });
}

test("at 1024 px next to the open app sidebar the sections are pills above the pane; at 1280 a list beside it", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await open(page, "/settings?section=ai", "Settings");
  const nav = page.getByRole("navigation", { name: "Settings sections" });
  const heading = page.getByRole("heading", { level: 2, name: "AI & models" });
  expect((await nav.boundingBox())!.y + (await nav.boundingBox())!.height).toBeLessThan((await heading.boundingBox())!.y);
  // the pane gets the column's width: the model pickers sit beside their jobs
  const row = page.getByRole("radiogroup", { name: "Model for understanding letters" });
  const label = page.getByText("Understanding letters", { exact: true });
  expect(Math.abs((await row.boundingBox())!.y - (await label.boundingBox())!.y)).toBeLessThan(24);
  // …and every pill is on screen (they wrap, no sideways scrolling)
  for (const pill of await nav.getByRole("link").all()) expect(await reachable(pill)).toBe(true);

  await page.setViewportSize({ width: 1280, height: 800 });
  await settle(page);
  expect((await nav.boundingBox())!.x + (await nav.boundingBox())!.width).toBeLessThan((await heading.boundingBox())!.x);
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`forms without axe violations (${scheme})`, () => {
    test.use({ colorScheme: scheme });

    for (const section of ["region", "reminders", "calendar", "ai", "claude"]) {
      test(`Settings → ${section}`, async ({ page }, testInfo) => {
        await open(page, `/settings?section=${section}`, "Settings");
        await expectAccessible(page, testInfo, `settings-${section}-${scheme}`);
      });
    }

    test("Settings → profile with a mistake and the save bar pinned", async ({ page }, testInfo) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await open(page, "/settings?section=profile", "Settings");
      const email = page.getByRole("textbox", { name: /Email/ });
      await email.fill("sam.rivera@");
      await page.getByRole("main").getByRole("button", { name: "Save changes" }).click();
      await expect(email).toBeFocused();
      await expect(page.getByText("Fix the highlighted field to save")).toBeVisible();
      await expectAccessible(page, testInfo, `settings-profile-invalid-${scheme}`);
      await page.getByRole("main").getByRole("button", { name: "Discard" }).click();
    });
  });
}

test.describe("phone 390×844", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the section pills scroll sideways with a faded edge, and a focused pill comes fully into view", async ({ page }) => {
    await open(page, "/settings?section=profile", "Settings");
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    const list = nav.getByRole("list");
    await expect.poll(() => list.evaluate((el) => getComputedStyle(el).maskImage)).toMatch(/linear-gradient/);
    const data = nav.getByRole("link", { name: "Data" });
    await data.focus();
    await settle(page);
    const box = (await data.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  });

  test("Reminders: the chips are proper lists with 24 px remove buttons (axe)", async ({ page }) => {
    await open(page, "/settings?section=reminders", "Settings");
    const results = await new AxeBuilder({ page }).include("main").withRules(["list", "listitem", "aria-required-children", "target-size"]).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    const remove = page.getByRole("button", { name: "Remove reminder 1 day before for deadlines" });
    const box = (await remove.boundingBox())!;
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
  });
});
