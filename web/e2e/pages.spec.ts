/**
 * The main pages against the real demo: what each one must show (SPEC §14), no raw enum values
 * anywhere (§14 copy table), axe-core in light and dark mode, and a phone-sized smoke test.
 */
import type { Page } from "@playwright/test";
import { apiGet, documentId, expect, expectAccessible, expectNoRawEnums, open, openMail, setTour, test } from "./helpers";

// The tour card floats over every page; these tests are about the pages themselves.
test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

test.describe("pages", () => {
  test("a scam letter shows the scam and hidden-text warnings and offers no way to pay", async ({ page }) => {
    await openMail(page, "Rundfunk-Beitragsservice");
    const warnings = page.getByRole("region", { name: "Warnings and things to check" });
    await expect(warnings.getByRole("alert").getByRole("heading", { name: "This looks like a scam — don't pay" })).toBeVisible();
    await expect(warnings.getByText("This document contains hidden text aimed at software — we ignored it")).toBeVisible();
    await expect(warnings).toContainText("No warning does not mean it is safe.");
    // nothing on the page invites paying it
    const main = page.getByRole("main");
    await expect(main.getByRole("button", { name: /^Pay\b/ })).toHaveCount(0);
    await expect(main.getByRole("link", { name: /^Pay\b/ })).toHaveCount(0);
    await expect(page.getByRole("article").getByRole("heading", { name: "What you need to do" })).toBeVisible();
    await expect(page.getByRole("article")).toContainText("Don't pay.");

    // …and Today doesn't put the demanded 254,35 € on the to-pay list either
    await open(page, "/");
    await expect(main.getByRole("article").filter({ hasText: "254,35" }).getByRole("button", { name: /^Pay\b/ })).toHaveCount(0);
    await expect(main.getByRole("link", { name: /^To pay/ })).not.toContainText("254,35");
  });

  test("Timeline shows the life lanes with the Today marker", async ({ page }) => {
    await open(page, "/timeline");
    const year = page.getByRole("region", { name: "Your year ahead" });
    const lanes = year.getByRole("list", { name: "Lanes" }).getByRole("listitem");
    await expect(lanes.first()).toBeVisible();
    for (const area of ["Residence", "Contracts", "Study", "Money", "Health"]) {
      await expect(year.getByRole("listitem", { name: area, exact: true })).toBeVisible();
    }
    await expect(year.getByTestId("lanes-today")).toHaveText("Today");
    await expect(year.getByTestId("lanes-today-line")).toBeAttached();
    // the today line sits at the Today label, inside the chart
    const label = await year.getByTestId("lanes-today").boundingBox();
    const line = await year.getByTestId("lanes-today-line").boundingBox();
    expect(label && line && Math.abs(label.x + label.width / 2 - (line.x + line.width / 2))).toBeLessThan(2);
  });

  test("Contracts shows when to send the FunkNetz cancellation", async ({ page }) => {
    await open(page, "/contracts");
    const decide = page.getByRole("region", { name: /^Decide by/ });
    const funknetz = decide.getByRole("listitem").filter({ has: page.getByRole("heading", { name: /FunkNetz Smart M/ }) });
    // "send", like the chart's "Send by" diamond and the card's "Send by" row
    await expect(funknetz).toContainText("send your Kündigung (cancellation / notice) by Thu 8 Oct");
    await expect(funknetz).toContainText("must arrive by Wed 14 Oct");
    await expect(funknetz.getByRole("link", { name: "Draft cancellation for FunkNetz Smart M" })).toBeVisible();
    // the lanes chart marks the same send-by date
    await expect(page.getByRole("button", { name: /^Send by · Thu 8 Oct, in 10 days\. FunkNetz Smart M/ })).toBeVisible();
  });

  test("Ask: a suggested question streams an answer whose citation opens the letter", async ({ page }) => {
    await open(page, "/ask");
    const question = "When does my residence permit expire, and what should I do before then?";
    const stream = page.waitForResponse((r) => r.url().endsWith("/api/ask") && r.request().method() === "POST");
    await page.getByRole("list", { name: "Suggested questions" }).getByRole("button", { name: question }).click();
    // the recorded answer is replayed as a stream (Server-Sent Events), like a live one
    expect((await stream).headers()["content-type"]).toContain("text/event-stream");
    const turn = page.getByRole("article", { name: `Question: ${question}` });
    await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
    // the permit's expiry (checked against the records; the recording depends on which letters are read)
    await expect(turn).toContainText(/30 Nov 2026|30\.11\.2026/);
    await expect(turn.getByRole("button", { name: /^Looked at \d+ things?/ })).toBeVisible();
    const toLetter = turn.locator('a[href^="/documents/"]');
    await expect(toLetter.first()).toBeVisible();
    await toLetter.first().click();
    await expect(page).toHaveURL(/\/documents\/doc_/);
    await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("Letters: a cancellation for the phone contract with PDF preview and checks", async ({ page }) => {
    await open(page, "/letters");
    await page.getByRole("button", { name: "New letter" }).click();
    const composer = page.getByRole("dialog", { name: "New letter" });
    await composer.locator("label", { hasText: "Cancel a contract" }).click();
    await composer.locator("label", { hasText: "FunkNetz Smart M" }).click();
    await expect(composer.getByRole("radio", { name: /^FunkNetz Smart M/ })).toBeChecked();
    await expect(composer).toContainText("FunkNetz Mobil GmbH · Wellenweg 7");

    const pdf = page.waitForResponse((r) => /\/api\/drafts\/[^/]+\/pdf/.test(r.url()));
    await composer.getByRole("button", { name: "Write the letter" }).click();
    await page.waitForURL(/\/letters\/drf_/);

    const response = await pdf;
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toBe("application/pdf");
    const preview = page.getByRole("region", { name: "Print preview" });
    const frame = preview.locator("iframe");
    await expect(frame).toHaveAttribute("title", "Preview of the printable letter (PDF)");
    await expect(frame).toBeVisible();
    const file = await page.request.get((await frame.getAttribute("src"))!.split("#")[0]!);
    expect(file.headers()["content-type"]).toBe("application/pdf");
    expect((await file.body()).subarray(0, 5).toString()).toBe("%PDF-");

    await expect(page.getByRole("textbox", { name: "Letter text (German)" })).toHaveValue(/kündige ich den Vertrag „FunkNetz Smart M“/);
    const checks = page.getByRole("region", { name: "Checks" });
    await expect(checks).toContainText(/checks passed/);
    await expect(checks.getByRole("listitem").first()).toBeVisible();
    expect(await checks.getByRole("listitem").count()).toBeGreaterThanOrEqual(5);
    await expect(page.getByRole("region", { name: "How to send it" })).toContainText("Thu 8 Oct");
  });

  test("Settings → Privacy & AI usage shows the usage numbers", async ({ page }) => {
    await open(page, "/settings");
    await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Privacy & AI usage" }).click();
    await expect(page).toHaveURL(/section=privacy/);
    const usage = page.getByRole("region", { name: "AI usage" });
    for (const [label, value] of [
      ["Calls to Claude", /^\d+$/],
      ["Tokens", /^\d[\d.,]*k?$/],
      ["API-equivalent cost", /^\$\d+\.\d\d$/],
    ] as const) {
      const figure = usage.getByRole("term").filter({ hasText: label }).locator("..");
      await expect(figure.getByRole("definition").first()).toHaveText(value);
    }
    const byPurpose = usage.getByRole("table", { name: "API-equivalent cost by purpose" });
    await expect(byPurpose.getByRole("rowheader", { name: "Understanding letters" })).toBeVisible();
    await expect(page.getByRole("region", { name: "What was sent, call by call" })).toBeVisible();
  });
});

// ------------------------------------------------------------------------------------------------
// Every main page: copy and accessibility
// ------------------------------------------------------------------------------------------------

const MAIN_PAGES: { name: string; path: (page: Page) => Promise<string>; h1: string | RegExp }[] = [
  { name: "Today", path: async () => "/", h1: /Sam/ },
  { name: "Inbox", path: async () => "/inbox", h1: "Inbox" },
  { name: "Letter viewer", path: async (page) => `/documents/${await documentId(page, /FunkNetz/)}`, h1: /FunkNetz/ },
  { name: "Timeline", path: async () => "/timeline", h1: "Timeline" },
  { name: "Contracts", path: async () => "/contracts", h1: "Contracts" },
  { name: "Letters", path: async () => "/letters", h1: "Letters" },
  { name: "Ask", path: async () => "/ask", h1: "Ask about your letters" },
  { name: "Settings", path: async () => "/settings", h1: "Settings" },
  { name: "Privacy & AI usage", path: async () => "/settings?section=privacy", h1: "Settings" },
  { name: "How dates are computed", path: async () => "/settings?section=rules", h1: "Settings" },
];

test("no raw enum values in the visible text of any page", async ({ page }) => {
  for (const p of MAIN_PAGES) {
    await open(page, await p.path(page), p.h1);
    await expectNoRawEnums(page, p.name);
  }
  // a drafted letter and an answered question too
  const drafts = await apiGet<{ id: string }[]>(page, "/api/drafts");
  if (drafts[0]) {
    await open(page, `/letters/${drafts[0].id}`);
    await expectNoRawEnums(page, "Letter");
  }
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibility (${scheme})`, () => {
    test.use({ colorScheme: scheme });

    for (const p of MAIN_PAGES) {
      test(`${p.name} has no serious or critical axe violations`, async ({ page }, testInfo) => {
        await open(page, await p.path(page), p.h1);
        await expect(page.locator("html")).toHaveClass(scheme === "dark" ? /\bdark\b/ : /^(?!.*\bdark\b)/);
        await expectAccessible(page, testInfo, `${p.name}-${scheme}`);
      });
    }

    test("a drafted letter has no serious or critical axe violations", async ({ page }, testInfo) => {
      const drafts = await apiGet<{ id: string }[]>(page, "/api/drafts");
      test.skip(!drafts.length, "needs the letter drafted by the Letters test");
      await open(page, `/letters/${drafts[0]!.id}`);
      await expect(page.getByRole("region", { name: "Checks" })).toBeVisible();
      await expectAccessible(page, testInfo, `letter-${scheme}`);
    });

    test("an answered question has no serious or critical axe violations", async ({ page }, testInfo) => {
      await open(page, "/ask");
      await page.getByRole("button", { name: "When does my phone contract end, and by when do I have to cancel it?" }).click();
      await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
      await expectAccessible(page, testInfo, `ask-answer-${scheme}`);
    });
  });
}

// ------------------------------------------------------------------------------------------------
// Phone (390 × 844)
// ------------------------------------------------------------------------------------------------

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  async function expectNoSideways(page: Page) {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);
  }

  test("Today fits a phone", async ({ page }, testInfo) => {
    await open(page, "/");
    await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeInViewport();
    await expect(page.getByRole("navigation", { name: "Primary" }).last()).toBeVisible();
    await expectNoSideways(page);
    await expectAccessible(page, testInfo, "today-phone");
  });

  test("the letter viewer stacks the page images below the verdict card", async ({ page }, testInfo) => {
    await open(page, `/documents/${await documentId(page, /FunkNetz/)}`);
    const verdict = page.getByRole("article").first();
    const pages = page.getByRole("region", { name: "Letter pages" });
    await expect(verdict).toBeVisible();
    await pages.scrollIntoViewIfNeeded();
    await expect(pages.getByRole("img", { name: /^Page 1 of/ })).toBeVisible();
    const card = (await verdict.boundingBox())!;
    const images = (await pages.boundingBox())!;
    expect(images.y).toBeGreaterThanOrEqual(card.y + card.height - 1);
    expect(images.width).toBeLessThanOrEqual(390);
    await expectNoSideways(page);
    await expectAccessible(page, testInfo, "viewer-phone");
  });
});
