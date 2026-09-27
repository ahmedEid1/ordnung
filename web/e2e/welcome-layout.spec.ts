/**
 * The setup wizard on the real demo, where jsdom can't look (UI audit round 1, onboarding). The
 * demo's Sam is set up already, so `/welcome` is the "Change your setup" variant. Checked: the
 * phone footer (main button full width on top, Back under it), focus on each new step's heading,
 * one column of states on the smallest phones, the install command shown whole, the welcome cards'
 * descriptions starting level, a tall window centring the card, and the finish screen (its POST is
 * answered here, so the demo stays as it is).
 */
import type { Locator, Page } from "@playwright/test";
import { apiGet, expect, settle, setTour, test } from "./helpers";

const box = async (l: Locator) => (await l.boundingBox())!;
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const h1 = (page: Page) => page.getByRole("heading", { level: 1 });

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function openWizard(page: Page) {
  await page.goto("/welcome");
  await expect(h1(page)).toHaveText("Change your setup");
  await settle(page);
}

/** The health answer with Claude "not installed" (nothing is sent to Claude). */
async function claudeMissing(page: Page) {
  await page.route(/\/api\/health$/, async (route) => {
    const res = await route.fetch();
    const json = await res.json();
    await route.fulfill({ response: res, json: { ...json, claude: { installed: false, version: null, path: null, ok: null, detail: null } } });
  });
}

/** Answer the finishing POST here (the demo's profile stays as it is). */
async function answerOnboarding(page: Page) {
  const profile = await apiGet<Record<string, unknown>>(page, "/api/profile");
  await page.route(/\/api\/onboarding$/, (route) => route.fulfill({ json: { ...profile, ...(route.request().postDataJSON()?.profile ?? {}), onboarded: true } }));
}

async function toStep(page: Page, step: 2 | 3 | 4) {
  await page.getByRole("button", { name: "Get started" }).click();
  await expect(h1(page)).toHaveText("Where do you live?");
  if (step >= 3) {
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(h1(page)).toHaveText("Your name and address");
  }
  if (step >= 4) {
    await page.getByRole("button", { name: /^(Continue|Skip for now)$/ }).click();
    await expect(h1(page)).toHaveText("Is Claude ready?");
  }
  await settle(page);
}

for (const [width, height] of [
  [320, 640],
  [390, 844],
]) {
  test.describe(`phone ${width}×${height}`, () => {
    test.use({ viewport: { width, height } });

    test("the main button spans the card above Back, and each step's heading gets the focus", async ({ page }) => {
      await openWizard(page);
      const form = page.locator("form");
      const start = page.getByRole("button", { name: "Get started" });
      const back = page.getByRole("main").getByRole("link", { name: "Back to Ordnung" });
      // the form's content width (inside its border and padding)
      const inner = await form.evaluate((el) => el.clientWidth - parseFloat(getComputedStyle(el).paddingLeft) - parseFloat(getComputedStyle(el).paddingRight));
      expect((await box(start)).width).toBeGreaterThan(inner - 2);
      expect((await box(back)).y).toBeGreaterThan((await box(start)).y);
      expect(await noSideScroll(page)).toBe(true);

      await start.click();
      await expect(h1(page)).toBeFocused();
      const cont = page.getByRole("button", { name: "Continue" });
      await cont.scrollIntoViewIfNeeded();
      expect((await box(cont)).width).toBeGreaterThan(inner - 2);
      expect((await box(page.getByRole("button", { name: "Back" }))).y).toBeGreaterThan((await box(cont)).y);

      // the states: one column below 360 px, two above — never a name over four lines
      const cards = page.getByRole("group", { name: "Your state (Bundesland)" }).locator("label");
      const xs = new Set(await cards.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().x))));
      expect(xs.size).toBe(width < 360 ? 1 : 2);
      expect(await noSideScroll(page)).toBe(true);

      await cont.click();
      await expect(h1(page)).toHaveText("Your name and address");
      await expect(h1(page)).toBeFocused();
    });

    test("the install command shows whole, the Copy button beside it", async ({ page }) => {
      await claudeMissing(page);
      await openWizard(page);
      await toStep(page, 4);
      await expect(page.getByRole("status").filter({ hasText: "Claude isn't installed yet" })).toBeVisible();
      const command = page.locator("code").filter({ hasText: "npm install -g @anthropic-ai/claude-code" });
      expect(await command.evaluate((el) => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight)).toBe(true);
      const copy = page.getByRole("button", { name: /^Copy command to install Claude Code/ });
      const c = await box(command);
      const b = await box(copy);
      expect(b.x).toBeGreaterThanOrEqual(c.x + c.width);
      expect(Math.abs(b.y - c.y)).toBeLessThan(2); // top-aligned with the first line
      expect(await noSideScroll(page)).toBe(true);
    });

    test("the finish screen: “Go to Today” is a button and the lock stays with its words", async ({ page }) => {
      await answerOnboarding(page);
      await openWizard(page);
      await toStep(page, 4);
      await page.getByRole("button", { name: /^(Finish setup|Continue without AI)$/ }).click();
      await expect(h1(page)).toHaveText(/^You're all set/);
      await expect(h1(page)).toBeFocused();
      await expect(page.getByText("Setup complete", { exact: true })).toBeVisible();
      await expect(page.getByText("Done", { exact: true })).toBeVisible();
      const today = page.getByRole("link", { name: "Go to Today" });
      expect((await box(today)).height).toBeGreaterThanOrEqual(36);
      const note = page.getByText("Your files stay on this computer.");
      const lock = note.locator("svg");
      const n = await box(note);
      const l = await box(lock);
      expect(l.y - n.y).toBeLessThan(8); // on the first line of the note, not floating beside a wrapped block
      expect(await noSideScroll(page)).toBe(true);
      await today.click();
      await expect(page).toHaveURL(/\/$/);
      await page.goBack();
      await expect(page).not.toHaveURL(/\/welcome/);
    });
  });
}

test.describe("touch screens", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("the finish screen asks for photos or PDFs, not a drop", async ({ page }) => {
    await answerOnboarding(page);
    await openWizard(page);
    await toStep(page, 4);
    await page.getByRole("button", { name: /^(Finish setup|Continue without AI)$/ }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Add your letters" })).toBeVisible();
    await expect(page.getByText("Drop your letters here")).toBeHidden();
  });
});

test.describe("wide screens", () => {
  test("the welcome cards' descriptions start level", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openWizard(page);
    const tops = await page.locator("form ul > li > p:last-child").evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)));
    expect(tops).toHaveLength(3);
    expect(new Set(tops).size).toBe(1);
  });

  test("a tall window centres the card instead of leaving the bottom empty", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await openWizard(page);
    const header = await box(page.locator("header"));
    const form = await box(page.locator("form"));
    const above = form.y - (header.y + header.height);
    const below = 1080 - (form.y + form.height);
    expect(above).toBeGreaterThan(40);
    expect(Math.abs(below - above)).toBeLessThan(160); // the footnote and bottom padding sit below
  });
});
