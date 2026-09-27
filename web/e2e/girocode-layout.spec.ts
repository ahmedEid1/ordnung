/**
 * The GiroCode (EPC-QR) in the Pay panels on the real demo, where jsdom can't look: the code is a
 * square of black modules on white with its quiet zone in both themes, big enough to scan and
 * wholly on screen from 320 px up, the panel's actions stay in view, phones fold it behind
 * "Show code", and a photographed letter asks to compare with the paper first.
 */
import type { Locator, Page } from "@playwright/test";
import { documentId, expect, expectAccessible, open, setTour, settle, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

const VIEWPORTS = [
  [320, 640],
  [390, 844],
  [768, 1024],
  [1280, 800],
] as const;

/** The utility statement's Pay panel, with the code unfolded (phones fold it). */
async function openStatementCode(page: Page): Promise<{ panel: Locator; code: Locator }> {
  const id = await documentId(page, /Operating and Heating Cost Statement|Betriebs/);
  await open(page, `/documents/${id}`);
  await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €184\.30/ }).click();
  const panel = page.getByRole("dialog").filter({ has: page.getByRole("region", { name: "GiroCode (EPC-QR)" }) });
  const show = panel.getByRole("button", { name: "Show code" });
  if (await show.isVisible()) await show.click();
  const code = panel.getByRole("img", { name: /^GiroCode: transfer €184\.30 to Wohnbau Musterstadt eG, reference MV-2025-0412 NK 2025$/ });
  await expect(code).toBeVisible();
  await settle(page);
  return { panel, code };
}

/** Is the whole element on screen and the top-most thing at its centre? */
async function reachable(l: Locator): Promise<boolean> {
  return l.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth && Boolean(hit && el.contains(hit));
  });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} mode`, () => {
    test.use({ colorScheme: scheme });

    for (const [width, height] of VIEWPORTS) {
      test(`${width}×${height}: the code is black on white, square, scannable and on screen`, async ({ page }) => {
        await page.setViewportSize({ width, height });
        const { panel, code } = await openStatementCode(page);
        await code.scrollIntoViewIfNeeded();
        const b = (await code.boundingBox())!;
        expect(Math.abs(b.width - b.height)).toBeLessThanOrEqual(1);
        expect(b.width, "at least 2 px per module for a phone camera").toBeGreaterThanOrEqual(140);
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width).toBeLessThanOrEqual(width);
        const colours = await code.evaluate((svg) => ({
          background: getComputedStyle(svg).backgroundColor,
          light: svg.querySelector("rect")!.getAttribute("fill"),
          dark: svg.querySelector("path")!.getAttribute("fill"),
          modules: Number(svg.getAttribute("data-qr-modules")),
          quiet: svg.querySelector("path")!.getAttribute("d")!.split("M").slice(1).every((run) => {
            const [x, y] = run.split(/[ h]/).map(Number);
            const size = Number(svg.getAttribute("data-qr-modules"));
            return x! >= 4 && y! >= 4 && x! < size - 4 && y! < size - 4;
          }),
        }));
        expect(colours).toMatchObject({ background: "rgb(255, 255, 255)", light: "#ffffff", dark: "#000000", quiet: true });
        expect(colours.modules).toBeGreaterThanOrEqual(21 + 8);
        // the actions stay in view below the code, and nothing scrolls sideways
        expect(await reachable(panel.getByRole("button", { name: "I've paid it" }))).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      });
    }

    test("the photographed fine asks for the paper letter, and its panel passes axe", async ({ page }, testInfo) => {
      const id = await documentId(page, /Verwarnung|traffic fine/i);
      await open(page, `/documents/${id}`);
      await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €30\.00/ }).click();
      const section = page.getByRole("dialog").getByRole("region", { name: "GiroCode (EPC-QR)" });
      await expect(section).toContainText("read by AI from a photo");
      await expect(section.getByRole("button", { name: "These match the letter" })).toBeVisible();
      await expect(section.getByRole("img")).toHaveCount(0);
      await expectAccessible(page, testInfo, `girocode-check-${scheme}`);
    });
  });
}

test.describe("phone 390×844", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("a phone can't scan its own screen: the code waits behind “Show code”", async ({ page }) => {
    const id = await documentId(page, /Operating and Heating Cost Statement|Betriebs/);
    await open(page, `/documents/${id}`);
    await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €184\.30/ }).click();
    const sheet = page.getByRole("dialog");
    const show = sheet.getByRole("button", { name: "Show code" });
    await expect(show).toHaveAttribute("aria-expanded", "false");
    await expect(sheet.getByRole("img", { name: /^GiroCode:/ })).toHaveCount(0);
    await show.click();
    await expect(sheet.getByRole("img", { name: /^GiroCode:/ })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Hide code" })).toHaveAttribute("aria-expanded", "true");
  });

  test("Today's Pay sheet unfolds the code and scrolls it into view", async ({ page }) => {
    await open(page, "/", /Sam/);
    await page.getByRole("region", { name: "Top 3 this week" }).getByRole("button", { name: /^Pay: / }).first().click();
    const sheet = page.getByRole("dialog");
    await sheet.getByRole("button", { name: "Show code" }).click();
    const code = sheet.getByRole("img", { name: /^GiroCode: transfer/ });
    await expect(code).toBeVisible();
    await settle(page);
    const b = (await code.boundingBox())!;
    expect(b.y + b.height).toBeLessThanOrEqual(844);
    expect(await reachable(sheet.getByRole("button", { name: "Mark as paid" }))).toBe(true);
  });
});
