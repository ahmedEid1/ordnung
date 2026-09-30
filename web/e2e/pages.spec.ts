/**
 * The main pages against the real demo: what each one must show (SPEC §14), no raw enum values
 * anywhere (§14 copy table), axe-core in light and dark mode, and a phone-sized smoke test.
 */
import type { Page } from "@playwright/test";
import { apiGet, contractOf, expect, expectAccessible, expectNoRawEnums, letterDetail, letterId, open, openMail, setTour, shownAs, test } from "./helpers";

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
    for (const area of ["Residence permit", "Contracts", "Study", "Money", "Health", "Home", "Getting around"]) {
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
    // the phone contract by what it is: its name is the model's, and a re-recording may rename it
    const phone = await contractOf(page, "mobile");
    await open(page, "/contracts");
    const decide = page.getByRole("region", { name: /^Decide by/ });
    // (the heading names the organisation after the contract)
    const funknetz = decide.getByRole("listitem").filter({ has: page.getByRole("heading", { name: new RegExp(`^${shownAs(phone.name).source}`) }) });
    // "send", like the chart's "Send by" diamond and the card's "Send by" row
    await expect(funknetz).toContainText("send your Kündigung (cancellation / notice) by Thu 8 Oct");
    await expect(funknetz).toContainText("must arrive by Wed 14 Oct");
    await expect(funknetz.getByRole("link", { name: shownAs(`Draft cancellation for ${phone.name}`) })).toBeVisible();
    // the lanes chart marks the same send-by date (with the must-arrive-by date six days later, when
    // the two sit too close to tell apart they are one mark that names both)
    const mark = new RegExp(`^Send by · Thu 8 Oct, in 10 days(; Must arrive by · Wed 14 Oct, in 16 days)?\\. ${shownAs(phone.name).source}`);
    await expect(page.getByRole("button", { name: mark })).toBeVisible();
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
    // a date never breaks (no-break spaces), and this year's leaves its year out as on every other page
    await expect(turn).toContainText(/\b30\sNov(?!\s\d{4})|30\.11\.2026/);
    await expect(turn.getByRole("button", { name: /^Looked at \d+ things?/ })).toBeVisible();
    const toLetter = turn.locator('a[href^="/documents/"]');
    await expect(toLetter.first()).toBeVisible();
    await toLetter.first().click();
    await expect(page).toHaveURL(/\/documents\/doc_/);
    await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("Letters: a cancellation for the phone contract with PDF preview and checks", async ({ page }) => {
    // the phone contract by what it is; what the composer and the letter show of it, from its name as read
    const phone = await contractOf(page, "mobile");
    await open(page, "/letters");
    await page.getByRole("button", { name: "New letter" }).click();
    const composer = page.getByRole("dialog", { name: "New letter" });
    await composer.locator("label", { hasText: "Cancel a contract" }).click();
    await composer.locator("label", { hasText: shownAs(phone.name) }).click();
    await expect(composer.getByRole("radio", { name: new RegExp(`^${shownAs(phone.name).source}`) })).toBeChecked();
    // the recipient's whole name and address, the address on a line of its own (never cut off)
    await expect(composer).toContainText("ToFMFunkNetz Mobil GmbHWellenweg 7, 12351 Beispielhausen");

    // the print preview is an image of the printed letter (phones show no PDF inline); the PDF is a link away
    const png = page.waitForResponse((r) => /\/api\/drafts\/[^/]+\/preview\.png/.test(r.url()));
    await composer.getByRole("button", { name: "Write the letter" }).click();
    await page.waitForURL(/\/letters\/drf_/);

    const response = await png;
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toBe("image/png");
    const preview = page.getByRole("region", { name: "Print preview" });
    await expect(preview.getByRole("img", { name: "Preview of the printable letter" })).toBeVisible();
    const file = await page.request.get((await preview.getByRole("link", { name: /Open the PDF/ }).getAttribute("href"))!);
    expect(file.headers()["content-type"]).toBe("application/pdf");
    expect((await file.body()).subarray(0, 5).toString()).toBe("%PDF-");

    await expect(page.getByRole("textbox", { name: "Letter text (German)" })).toHaveValue(shownAs(`kündige ich den Vertrag „${phone.name}“`));
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

/** The FunkNetz phone contract, by its sample's file name (its title is the model's, new with each recording). */
const PHONE_CONTRACT = "01_mobilfunkvertrag.pdf";

interface MainPage {
  name: string;
  path: (page: Page) => Promise<string>;
  /** its `<h1>`; a letter's is its title as read, from the API */
  h1: string | RegExp | ((page: Page) => Promise<RegExp>);
}

const MAIN_PAGES: MainPage[] = [
  { name: "Today", path: async () => "/", h1: /Sam/ },
  { name: "Inbox", path: async () => "/inbox", h1: "Inbox" },
  {
    name: "Letter viewer",
    path: async (page) => `/documents/${await letterId(page, PHONE_CONTRACT)}`,
    h1: async (page) => shownAs((await letterDetail(page, await letterId(page, PHONE_CONTRACT))).title, { whole: true }),
  },
  { name: "Timeline", path: async () => "/timeline", h1: "Timeline" },
  { name: "Contracts", path: async () => "/contracts", h1: "Contracts" },
  { name: "Letters", path: async () => "/letters", h1: "Letters" },
  { name: "Ask", path: async () => "/ask", h1: "Ask about your letters" },
  { name: "Settings", path: async () => "/settings", h1: "Settings" },
  { name: "Privacy & AI usage", path: async () => "/settings?section=privacy", h1: "Settings" },
  { name: "How dates are computed", path: async () => "/settings?section=rules", h1: "Settings" },
];

const heading = (page: Page, p: MainPage): Promise<string | RegExp> => (typeof p.h1 === "function" ? p.h1(page) : Promise.resolve(p.h1));

test("no raw enum values in the visible text of any page", async ({ page }) => {
  for (const p of MAIN_PAGES) {
    await open(page, await p.path(page), await heading(page, p));
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
        await open(page, await p.path(page), await heading(page, p));
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

  test("Settings fit a 320 px phone: the privacy log, every rule's sources and the data folder", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });

    // Privacy: nothing (not even the screen-reader table behind the chart) widens the page
    await open(page, "/settings?section=privacy", "Settings");
    const usage = page.getByRole("region", { name: "AI usage" });
    await expect(usage.getByRole("term").first()).toBeVisible();
    await expectNoSideways(page);
    // a label that wraps keeps the values of its row on one line
    const valueTops = await usage.locator("dl > div").evaluateAll((tiles) => tiles.map((t) => Math.round(t.querySelector("dd")!.getBoundingClientRect().top)));
    expect(valueTops[0]).toBe(valueTops[1]);
    expect(valueTops[2]).toBe(valueTops[3]);

    // Rules: every citation chip stays inside its card (no source cut off at the edge)
    await open(page, "/settings?section=rules", "Settings");
    await expect(page.getByRole("navigation", { name: "Rule topics" })).toBeVisible();
    const cutOff = await page.locator("#main section[aria-labelledby='set-rules'] .card").evaluateAll((cards) =>
      cards.flatMap((card) => {
        const box = card.getBoundingClientRect();
        return [...card.querySelectorAll<HTMLElement>("h4 ~ span")].filter((chip) => chip.getBoundingClientRect().right > box.right - 1).map((chip) => chip.textContent);
      }),
    );
    expect(cutOff).toEqual([]);
    await expectNoSideways(page);

    // Data: the whole folder path is on screen (it wraps instead of scrolling or clipping)
    await open(page, "/settings?section=data", "Settings");
    const path = page.getByRole("region", { name: "Where your data lives" }).locator("code");
    expect(await path.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await expectNoSideways(page);
  });

  test("Ask answers fit a phone: no citation chip starts a line, nothing scrolls sideways", async ({ page }) => {
    // review round 2: a no-break space before a chip did not keep it on its line (an inline-grid
    // chip is a line-break opportunity of its own); the word before it now wraps with it
    for (const width of [320, 360, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await open(page, "/ask");
      for (const question of [
        "When does my phone contract end, and by when do I have to cancel it?",
        "What do I have to pay in the next four weeks?",
        "When does my residence permit expire, and what should I do before then?",
      ]) {
        await page.getByRole("textbox").first().fill(question);
        await page.getByRole("textbox").first().press("Enter");
        await expect(page.getByRole("main").getByRole("status")).toHaveText("Answer ready.");
      }
      await expectNoSideways(page);
      const orphans = await page.evaluate(() => {
        const found: string[] = [];
        for (const chip of document.querySelectorAll("article p [aria-label^='Source'], article li [aria-label^='Source']")) {
          const block = chip.closest("p, li")!;
          const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
          let before: Text | null = null;
          for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
            if (chip.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING || chip.contains(n)) break;
            if (n.textContent?.trim() && !n.parentElement?.closest("[aria-label^='Source']")) before = n;
          }
          if (!before) continue;
          const text = before.textContent ?? "";
          let i = text.length - 1;
          while (i > 0 && /\s/.test(text[i]!)) i--;
          const range = document.createRange();
          range.setStart(before, i);
          range.setEnd(before, i + 1);
          if (range.getBoundingClientRect().bottom <= chip.getBoundingClientRect().top + 1) found.push(`${chip.textContent} after “${text.slice(-30)}”`);
        }
        return found;
      });
      expect(orphans, `citation chips alone at the start of a line at ${width} px`).toEqual([]);
    }
  });

  test("the letter viewer stacks the page images below the verdict card", async ({ page }, testInfo) => {
    await open(page, `/documents/${await letterId(page, PHONE_CONTRACT)}`);
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
