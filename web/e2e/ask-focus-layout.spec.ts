/**
 * Ask's sticky question box on real pages (review round 2 of phase 2; WCAG 2.4.11): keyboard focus on the
 * citation markers and source chips of real answers never ends up under it, and the live steps and the
 * "Writing the answer" line grow above it. Runs in the "layout" project (its name ends in `layout.spec.ts`).
 *
 * Why its own file, run first: the demo replays a recorded Ask answer only for a question it recorded
 * (`demo/asks.json`) on a ledger it recorded it on — every combination of opened New-mail letters on the
 * untouched demo (`demo/loader.py`, `_exercise_asks`; the key is the question, today and a hash of the
 * ledger: every letter, to-do, contract and party). The layout project runs its files in name order, and a
 * later one changes the ledger for good: `contracts-layout.spec.ts` saves a contract's notice terms through
 * the API, and a PATCH can't always put a contract back as its letter left it — saving notice terms clears
 * the contract's day of the month unless it is sent too, and records terms that give dates as the person's
 * (the Deutschlandticket's "by the 10th" lost its day that way). From then on every question gets "No
 * recorded answer for this question". These tests were in `layout.spec.ts`, which runs after it; here they
 * run before it, on the ledger the tour, the pages and the sweep left (the tax assessment read from New mail).
 */
import type { Page } from "@playwright/test";
import { obscuredFocus } from "./focus";
import { expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Ask a question on /ask (the demo replays its recorded answers) and wait for the checked answer. */
async function ask(page: Page, question: string): Promise<void> {
  const turns = page.getByRole("main").getByRole("article");
  const before = await turns.count();
  await page.getByRole("textbox").first().fill(question);
  await page.getByRole("textbox").first().press("Enter");
  await expect(turns).toHaveCount(before + 1);
  const status = page.getByRole("main").getByRole("status");
  await expect(status).toHaveText(/^(Answer ready|No recorded answer for this question)\.$/);
  expect(
    await status.textContent(),
    `“${question}” is one of the demo's recorded questions: no recording on this ledger means a test run before this one changed a letter, to-do or contract and didn't put it back`,
  ).toBe("Answer ready.");
}

const ASKED = ["What do I have to pay in the next four weeks?", "When does my phone contract end, and by when do I have to cancel it?"];

/**
 * Answer `POST /api/ask` in the page with a slow stream that never ends: four steps, 150 ms apart,
 * then the "writing" event (the checked answer never comes).
 */
async function slowAnswer(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const real = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, location.href).pathname !== "/api/ask" || (init?.method ?? "GET").toUpperCase() !== "POST") return real(input, init);
      const events: object[] = [];
      for (let i = 1; i <= 4; i++) {
        events.push({ type: "tool_use", name: "search", input: { query: `Frist ${i}` }, text: `Searched your letters for “Frist ${i}”` });
        events.push({ type: "tool_result", name: "search", text: `Found ${i} letters` });
      }
      events.push({ type: "text" });
      const enc = new TextEncoder();
      const body = new ReadableStream({
        start(ctrl) {
          events.forEach((e, i) => setTimeout(() => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`)), 150 * (i + 1)));
        },
      });
      return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    };
  });
}

/** How the "Writing the answer" line and its question sit against the sticky question box. */
function writingLine(page: Page) {
  return page.evaluate(() => {
    const line = [...document.querySelectorAll("main [data-turn] p:not(.sr-only)")].find((el) => el.textContent?.startsWith("Writing the answer"));
    const composer = document.querySelector("[data-ask-composer]")!.getBoundingClientRect();
    const turn = line?.closest("[data-turn]")?.getBoundingClientRect();
    if (!line || !turn) return null;
    const box = line.getBoundingClientRect();
    // the three dots sit level with the first of its wrapped lines (UI audit round 2: beside the middle one)
    const dots = line.querySelector(":scope > span[aria-hidden]")!.getBoundingClientRect();
    const firstLine = parseFloat(getComputedStyle(line).lineHeight);
    return {
      aboveComposer: box.bottom <= composer.top + 1,
      questionShown: turn.top >= 56,
      wraps: box.height > firstLine * 1.5,
      dotsOnFirstLine: Math.abs(dots.top + dots.height / 2 - (box.top + firstLine / 2)) <= 1.5,
    };
  });
}

// review round 2 of phase 2: on /ask the sticky question box covers the bottom of the screen too —
// focused citation markers and source chips ended up under it, and the live steps grew behind it
test.describe("phone: on Ask, focus and the growing answer stay clear of the question box", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("Tab through two answered questions", async ({ page }) => {
    await open(page, "/ask");
    for (const question of ASKED) await ask(page, question);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(await obscuredFocus(page, 60, "Tab")).toEqual([]);
  });

  test("at 320 × 640 the steps and the writing line grow above the question box", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await slowAnswer(page);
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("Which deadlines do I have?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(page.getByRole("main").getByText(/^Writing the answer — it appears once Ordnung has checked it against your records/)).toBeVisible();
    await expect.poll(() => writingLine(page)).toEqual({ aboveComposer: true, questionShown: true, wraps: true, dotsOnFirstLine: true });
  });
});

test.describe("laptop: on Ask, focus stays clear of the question box", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("Tab through two answered questions", async ({ page }) => {
    await open(page, "/ask");
    for (const question of ASKED) await ask(page, question);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(await obscuredFocus(page, 60, "Tab")).toEqual([]);
  });
});
