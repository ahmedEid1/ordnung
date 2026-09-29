/**
 * The GiroCode (EPC-QR) in the Pay panels on the real demo, where jsdom can't look: the code is a
 * square of black modules on white with its quiet zone in both themes, big enough to scan and
 * wholly on screen from 320 px up, the panel's actions stay in view, phones fold it behind
 * "Show code" and say what to do instead, a photographed letter asks to compare with the paper
 * first — and once compared, the code and its confirmation line scroll clear of the panel's sticky
 * footer, on the letter and on Today, even where they don't fit. A refused comparison and a failed
 * "Read the letter again" say why in the panel, clear of its footer, with focus kept.
 */
import type { Locator, Page } from "@playwright/test";
import { apiPatch, expect, expectAccessible, letterId, letterItem, open, setTour, settle, shownAs, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** The demo letters, by their samples' file names (their titles are the model's, new with each recording). */
const STATEMENT = "13_nebenkostenabrechnung_2025.pdf"; // the operating-cost statement, a PDF
const FINE = "21_verwarnungsgeld_parken.jpg"; // the parking fine, a photo

const VIEWPORTS = [
  [320, 640],
  [390, 844],
  [768, 1024],
  [1280, 800],
] as const;

/** The utility statement's Pay panel, with the code unfolded (phones fold it). */
async function openStatementCode(page: Page): Promise<{ panel: Locator; code: Locator }> {
  const id = await letterId(page, STATEMENT);
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
        expect(await reachable(panel.getByRole("button", { name: "Mark as paid" }))).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      });
    }

    test("the photographed fine asks for the paper letter, and its panel passes axe", async ({ page }, testInfo) => {
      const id = await letterId(page, FINE);
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
    const id = await letterId(page, STATEMENT);
    await open(page, `/documents/${id}`);
    await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €184\.30/ }).click();
    const sheet = page.getByRole("dialog");
    const show = sheet.getByRole("button", { name: "Show code" });
    await expect(show).toHaveAttribute("aria-expanded", "false");
    await expect(sheet.getByRole("img", { name: /^GiroCode:/ })).toHaveCount(0);
    // and says what to do instead of scanning this screen
    await expect(sheet.getByText(/^A phone or tablet can't scan its own screen: open this letter on a computer/)).toBeVisible();
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

test.describe("phone turned sideways 844×390", () => {
  test.use({ viewport: { width: 844, height: 390 }, hasTouch: true, isMobile: true });

  test("the code still waits behind “Show code”, and the actions don't pin themselves over the little room", async ({ page }) => {
    const id = await letterId(page, STATEMENT);
    await open(page, `/documents/${id}`);
    await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €184\.30/ }).click();
    const panel = page.getByRole("dialog");
    await expect(panel.getByRole("button", { name: "Show code" })).toHaveAttribute("aria-expanded", "false");
    await expect(panel.getByRole("img", { name: /^GiroCode:/ })).toHaveCount(0);
    expect(await panel.locator("[data-sticky-footer]").evaluate((el) => getComputedStyle(el).position)).toBe("static");
  });
});

// ------------------------------------------------------------------------------------------------
// "These match the letter" where the code doesn't fit: it scrolls clear of the sticky footer
// ------------------------------------------------------------------------------------------------

/** The photographed fine's payment to-do, asking for the paper letter again (a new amount re-arms it). */
async function rearmedFine(page: Page, amount: number): Promise<{ docId: string; itemId: string }> {
  const docId = await letterId(page, FINE);
  const item = await letterItem(page, docId, "payment");
  await apiPatch(page, `/api/items/${item.id}`, { amount });
  return { docId, itemId: item.id };
}

/**
 * Today's Top-3 “Pay: …” button of the fine's payment, named after its to-do (the model's title, read from
 * the API): the verb isn't said twice ("Pay: parking fee", not "Pay: Pay parking fee").
 */
async function finePayButton(page: Page): Promise<Locator> {
  const { title } = await letterItem(page, await letterId(page, FINE), "payment");
  const name = new RegExp(`^Pay: ${shownAs(title.replace(/^pay\s+/i, "")).source}`);
  return page.getByRole("region", { name: "Top 3 this week" }).getByRole("button", { name }).first();
}

/** The confirmation line and the code end above the panel's sticky footer (once scrolling stopped). */
async function clearOfFooter(panel: Locator): Promise<void> {
  const line = panel.getByText("You compared these details with the letter.", { exact: true });
  await expect(line).toBeVisible();
  const code = panel.getByRole("img", { name: /^GiroCode: transfer/ });
  const footer = panel.locator("[data-sticky-footer]");
  const gap = async (l: Locator) => {
    const [a, f] = [(await l.boundingBox())!, (await footer.boundingBox())!];
    return f.y - (a.y + a.height);
  };
  await expect.poll(() => gap(line), { message: "the confirmation line ends above the sticky footer" }).toBeGreaterThanOrEqual(0);
  expect(await gap(code), "the code ends above the sticky footer").toBeGreaterThanOrEqual(0);
  await expect(panel.getByRole("heading", { name: "GiroCode (EPC-QR)" })).toBeFocused();
}

test.describe("confirming where the code doesn't fit", () => {
  // back to the letter's amount afterwards: the fine asks for the paper letter again, as it started
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await rearmedFine(page, 30);
    await page.close();
  });

  const cases = [
    [320, 640, "letter", "reduce"],
    [360, 740, "letter", "reduce"],
    [360, 740, "letter", "no-preference"],
    [320, 640, "today", "reduce"],
    [360, 740, "today", "reduce"],
  ] as const;
  cases.forEach(([width, height, where, motion], i) => {
    test(`${width}×${height} on ${where === "letter" ? "the letter" : "Today"}${motion === "no-preference" ? ", smooth scrolling" : ""}`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: motion });
      await page.setViewportSize({ width, height });
      const { docId } = await rearmedFine(page, 31 + i);
      if (where === "letter") {
        await open(page, `/documents/${docId}`);
        await page.getByRole("main").getByRole("article").first().getByRole("button", { name: /^Pay €/ }).click();
      } else {
        await open(page, "/", /Sam/);
        await (await finePayButton(page)).click();
      }
      const panel = page.getByRole("dialog");
      await panel.getByRole("button", { name: "These match the letter" }).click();
      await clearOfFooter(panel);
    });
  });
});

// ------------------------------------------------------------------------------------------------
// A refused comparison, a failed reading: the reason shows in the panel, clear of its footer
// ------------------------------------------------------------------------------------------------

/** The element ends above the panel's sticky footer and is the top-most thing where it is. */
async function clearAndOnTop(panel: Locator, l: Locator): Promise<void> {
  await expect(l).toBeVisible();
  const footer = panel.locator("[data-sticky-footer]");
  await expect
    .poll(async () => (await footer.boundingBox())!.y - ((await l.boundingBox())!.y + (await l.boundingBox())!.height), { message: "it ends above the sticky footer" })
    .toBeGreaterThanOrEqual(0);
  expect(await reachable(l), "nothing covers it").toBe(true);
}

/** Today's Pay panel of the photographed fine (a popover from 768 px, a sheet below). */
async function todayFinePanel(page: Page): Promise<Locator> {
  await open(page, "/", /Sam/);
  await (await finePayButton(page)).click();
  return page.getByRole("dialog");
}

test.describe("refusals in the panel", () => {
  for (const [width, height] of [
    [1280, 800],
    [320, 640],
    [390, 844],
  ] as const) {
    test(`${width}×${height}: a refused “These match the letter” says why above Today's footer`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.route("**/api/items/*/girocode/confirm", (route) =>
        route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "The payment details changed since you looked at them. Please compare them again." }) }),
      );
      const panel = await todayFinePanel(page);
      const button = panel.getByRole("button", { name: "These match the letter" });
      await button.click();
      const alert = panel.getByRole("alert").filter({ hasText: "Not confirmed: The payment details changed" });
      await clearAndOnTop(panel, alert);
      await expect(button).toBeFocused();
    });
  }

  test("390×844: a failed “Read the letter again” says why in the sheet, and keeps focus", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    let asked = 0;
    await page.route("**/api/documents/*/reprocess", (route) => {
      asked += 1;
      return route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "Claude needs a short break. Try again at 15:30." }) });
    });
    const panel = await todayFinePanel(page);
    await panel.getByRole("button", { name: "They don't match" }).click();
    const button = panel.getByRole("button", { name: "Read the letter again" });
    await button.click();
    const alert = panel.getByRole("alert").filter({ hasText: "Couldn't read the letter again: Claude needs a short break." });
    await clearAndOnTop(panel, alert);
    await expect(button).toBeFocused();
    // no toast behind the sheet
    await expect(page.getByText("Claude needs a short break", { exact: true })).toHaveCount(0);
    expect(asked).toBe(1);
  });
});
