/**
 * Ask on the real demo, where jsdom can't measure (UI audit round 1, ask): long words, an IBAN and a
 * law's web address never widen a 320 px phone, markers follow their word, sources and follow-up
 * chips wrap instead of cutting their text, two suggested questions in a row both replay, a question
 * without a recording gets a note (no Try again), and the question box leaves a phone room.
 */
import type { Page } from "@playwright/test";
import { apiGet, expect, open, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function sideways(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

const status = (page: Page) => page.getByRole("main").getByRole("status");

/** Answer `POST /api/ask` in the page with `events` (the checked answer included). */
async function answerWith(page: Page, events: object[]): Promise<void> {
  await page.addInitScript((events) => {
    const real = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, location.href).pathname !== "/api/ask" || (init?.method ?? "GET").toUpperCase() !== "POST") return real(input, init);
      const enc = new TextEncoder();
      const body = new ReadableStream({
        start(ctrl) {
          for (const e of events) ctrl.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`));
          ctrl.close();
        },
      });
      return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    };
  }, events);
}

test.describe("phone", () => {
  test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });

  test("long words, an IBAN and a web address wrap at 320 px; markers follow their word; sources wrap", async ({ page }) => {
    const docs = await apiGet<{ id: string; title: string | null }[]>(page, "/api/documents");
    const doc = docs.find((d) => (d.title ?? "").length > 40) ?? docs[0]!;
    await answerWith(page, [
      { type: "tool_use", name: "list_items", input: { kind: "deadline", status: "open" }, text: "Checked your open deadlines" },
      { type: "tool_result", name: "list_items", text: "Found 3 to-dos & dates" },
      { type: "text" },
      {
        type: "done",
        text:
          `Bring (Immatrikulationsbescheinigung, Finanzierungsnachweis) and the contract/Wohnungsgeberbestätigung [doc:${doc.id}]. ` +
          `Pay to DE89370400440532013000 with the reference RF18539007547034ABCDEFGHIJ (§ 56 Abs. 3 AufenthG) at the Musterfirma GmbH [doc:${doc.id}].\n\n` +
          "https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html",
        note: null,
        note_label: "Checked by Ordnung:",
        citations: [{ type: "document", id: doc.id, label: doc.title }],
        message_id: "msg_e2e_long",
        thread_id: "thr_e2e_long",
      },
    ]);
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("Warum steht in meiner Immatrikulationsbescheinigungsverlängerungsanfrage die IBAN DE89370400440532013000?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(status(page)).toHaveText("Answer ready.");
    expect(await sideways(page), "the page scrolls sideways").toBeLessThanOrEqual(0);

    const turn = page.getByRole("article").last();
    // a single step is shown as it is (no "Looked at 1 thing" toggle)
    await expect(turn.getByRole("button", { name: /^Looked at/ })).toHaveCount(0);
    await expect(turn.getByText("Checked your open deadlines")).toBeVisible();

    // the marker follows its word like a footnote (UI audit round 1: "GmbH ¹ ."), in a group that never wraps
    const groups = await turn.locator("p [aria-label^='Source']").evaluateAll((markers) => markers.map((m) => m.closest("span.whitespace-nowrap")?.textContent ?? ""));
    expect(groups).toEqual(["⁠1.", "GmbH1."]);

    // the source's whole title: wrapped inside the chip, the chip inside the answer column
    const source = turn.getByRole("link", { name: /^Source 1:/ }).last();
    const [chip, column] = await Promise.all([source.boundingBox(), turn.boundingBox()]);
    expect(chip!.x + chip!.width).toBeLessThanOrEqual(column!.x + column!.width + 0.5);
  });

  test("the question box leaves a 320 × 640 screen room: a one-line hint, no deep fade", async ({ page }) => {
    await open(page, "/ask");
    const hint = page.locator("#ask-hint");
    await expect(hint).toHaveText("Answers can be wrong — not legal advice.", { useInnerText: true });
    expect((await hint.boundingBox())!.height, "the hint is one line").toBeLessThanOrEqual(21);
    const composer = (await page.locator("[data-ask-composer]").boundingBox())!;
    expect(composer.height, "box, hint and padding").toBeLessThanOrEqual(120);
  });
});

test.describe("laptop", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("two suggested questions in a row both replay their recorded answers", async ({ page }) => {
    await open(page, "/ask");
    await page.getByRole("list", { name: "Suggested questions" }).getByRole("button").first().click();
    await expect(status(page)).toHaveText("Answer ready.");
    for (let i = 0; i < 2; i++) {
      const row = page.getByRole("list", { name: "Suggested questions" });
      const chip = row.getByRole("button").first();
      const question = (await chip.getAttribute("title"))!;
      await chip.click();
      const turn = page.getByRole("article", { name: `Question: ${question}` });
      await expect(turn).toBeVisible();
      await expect(status(page)).toHaveText("Answer ready.");
      await expect(turn.getByText(/Couldn't answer/)).toHaveCount(0);
    }
    await expect(page.getByRole("article")).toHaveCount(3);

    // a source opens its letter, whose breadcrumb leads back to Ask (the shell records where it came from)
    await page.getByRole("main").locator('a[aria-label^="Source"][href^="/documents/"]').first().click();
    await expect(page).toHaveURL(/\/documents\/doc_/);
    await expect(page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Ask", exact: true })).toHaveAttribute("href", "/ask");
  });

  test("a question without a recording gets a note, not a failure with a Try again that can't work", async ({ page }) => {
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("Which of my letters mention a Kaution?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(status(page)).toHaveText("No recorded answer for this question.");
    const turn = page.getByRole("article").last();
    await expect(turn.getByText("No recorded answer for this question")).toBeVisible();
    await expect(turn.getByRole("button", { name: "Try again" })).toHaveCount(0);
    await expect(turn.getByText(/Couldn't answer/)).toHaveCount(0);
  });

  test("an Idea's web addresses become links named by their site, on the permit's letter page", async ({ page }) => {
    // the student-permit Idea names the law and the advice service by their addresses (UI audit round 1:
    // plain text that ran past the card at 320 px)
    const ideas = await apiGet<{ body: string; refs: { type: string; id: string }[] }[]>(page, "/api/suggestions");
    const idea = ideas.find((s) => s.body.includes("https://www.gesetze-im-internet.de/"));
    expect(idea, "the student-permit Idea").toBeTruthy();
    const letter = idea!.refs.find((r) => r.type === "document")!;
    await page.setViewportSize({ width: 320, height: 640 });
    await open(page, `/documents/${letter.id}`);
    const law = page.getByRole("link", { name: /^gesetze.im.internet\.de/ });
    await law.scrollIntoViewIfNeeded();
    await expect(law).toHaveAttribute("target", "_blank");
    await expect(law).toHaveAttribute("href", "https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html");
    await expect(page.getByRole("link", { name: /^studierendenwerke\.de/ })).toBeVisible();
    expect(await sideways(page), "the page scrolls sideways").toBeLessThanOrEqual(0);
  });
});
