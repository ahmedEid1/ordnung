/**
 * Ask on the real demo, where jsdom can't measure (UI audit round 1, ask): long words, an IBAN and a
 * law's web address never widen a 320 px phone, markers follow their word, sources and follow-up
 * chips wrap instead of cutting their text, two suggested questions in a row both replay, a question
 * without a recording gets a note (no Try again), the question box leaves a phone room, and the layout
 * sweep's target-size probe tells a marker after its words from a marker alone.
 */
import type { Page } from "@playwright/test";
import { layoutFindings } from "../scripts/ui-audit/probes.mjs";
import { apiGet, expect, open, setTour, shownAs, test } from "./helpers";

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

  // The layout sweep's target-size probe exempts a marker after its words (WCAG 2.5.8's inline exception). A
  // person's or organisation's marker is a button (it opens their drawer), not a link: it counts the same when
  // it follows words, also right after another marker ("…94.99 €¹ ²"); a marker alone in a list item does not
  // (the sweep's run after `pages` replayed list answers ending in a letter's and a person's marker).
  test("the target-size probe exempts markers after their words, a person's button too, but not a marker alone", async ({ page }) => {
    const docs = await apiGet<{ id: string; title: string | null }[]>(page, "/api/documents");
    const parties = await apiGet<{ id: string; name: string }[]>(page, "/api/parties");
    const doc = docs[0]!;
    const party = parties[0]!;
    await answerWith(page, [
      { type: "text" },
      {
        type: "done",
        text: `Due soon:\n\n- The phone bill, 94.99 € [doc:${doc.id}] [party:${party.id}]\n- Paid by transfer [party:${party.id}]\n- [party:${party.id}]`,
        note: null,
        note_label: "Checked by Ordnung:",
        citations: [
          { type: "document", id: doc.id, label: doc.title },
          { type: "party", id: party.id, label: party.name },
        ],
        message_id: "msg_e2e_markers",
        thread_id: "thr_e2e_markers",
      },
    ]);
    await open(page, "/ask");
    await page.getByRole("textbox").first().fill("What is due soon?");
    await page.getByRole("textbox").first().press("Enter");
    await expect(status(page)).toHaveText("Answer ready.");

    // the answer's list (the sources under it are a list too)
    const items = page.getByRole("article").last().getByRole("list").first().getByRole("listitem");
    await expect(items).toHaveCount(3);
    // the app draws them as the sweep sees them: small inline boxes, the person's a button
    const alone = items.nth(2).getByRole("button", { name: /^Source 2: / });
    await expect(items.nth(0).getByRole("button", { name: /^Source 2: / })).toBeVisible();
    await expect(alone).toBeVisible();
    expect((await alone.boundingBox())!.height).toBeLessThan(24);

    const { findings } = await layoutFindings(page);
    const markers = findings.filter((f) => f.probe === "target-size" && f.selector.includes('[aria-label="Source '));
    const where = await alone.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY) };
    });
    expect(markers.map((f) => ({ x: f.rect!.x, y: f.rect!.y })), "only the marker alone in its list item").toEqual([where]);
  });

  // The exemption is a marker's, in the line of the words it backs (review of the rule above): a small text
  // button on its own line under other text in the same box is still a standalone target, and so is a marker
  // that starts its own line under a paragraph or after a line break.
  test("the target-size probe still reports small buttons and markers on a line of their own", async ({ page }) => {
    // drawn like Ask's marker (17 px, inline-grid, raised); `name` "Source n: …" makes it a marker
    const btn = (id: string, text: string, name?: string) =>
      `<button id="${id}" ${name ? `aria-label="${name}"` : ""} style="display:inline-grid;place-items:center;position:relative;top:-0.35em;height:17px;min-width:17px;padding:0 4px;margin-left:2px;border:0;font-size:11px;line-height:1;background:#eef">${text}</button>`;
    const src = (n: number) => `Source ${n}: Person “Stadtwerke”`;
    await page.setContent(`<!doctype html><html lang="en"><head><title>Probe</title></head>
      <body style="font:16px/24px sans-serif;margin:16px"><main><h1>Probe</h1>
      <p>The phone bill is due soon, 94.99 €&#8288;${btn("after-words", "1", src(1))}${btn("after-marker", "2", src(2))}</p>
      <p>Paid by <strong>transfer</strong>&#8288;${btn("after-strong", "3", src(3))}</p>
      <ul><li>${btn("alone", "4", src(4))}</li><li>${btn("alone-run-1", "5", src(5))}${btn("alone-run-2", "6", src(6))}</li></ul>
      <div style="margin-top:40px"><p>A paragraph with plenty of words above the button.</p>${btn("undo-under-paragraph", "Undo")}</div>
      <div style="margin-top:40px"><h3 style="margin:0">Reminder</h3><span style="display:block">Some text.</span>${btn("remove-under-heading", "Remove")}</div>
      <div style="margin-top:40px"><label>Name</label><br>${btn("change-after-br", "Change")}</div>
      <div style="margin-top:40px"><p>A paragraph with plenty of words above the marker.</p>${btn("marker-under-paragraph", "7", src(7))}</div>
      <p style="margin-top:40px">Words on the line before<br>${btn("marker-after-br", "8", src(8))}</p>
      </main></body></html>`);
    const { findings } = await layoutFindings(page);
    const reported = findings.filter((f) => f.probe === "target-size").map((f) => /#([\w-]+)/.exec(f.selector)?.[1] ?? f.selector);
    expect(reported.sort()).toEqual(
      ["alone", "alone-run-1", "alone-run-2", "undo-under-paragraph", "remove-under-heading", "change-after-br", "marker-under-paragraph", "marker-after-br"].sort(),
    );
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

  test("an Idea's web addresses become links named by their site, on Today and on the letter it names", async ({ page }) => {
    // the student-permit rule names the law and the advice service by their addresses (UI audit round 1: plain
    // text that ran past the card at 320 px). Its Idea is about the person (a student visa), so Today always
    // shows it; it names the permit's letter only when the demo read a letter as a residence permit — the
    // model's reading, which changes with a re-recording — so the letter page is checked when there is one
    const ideas = await apiGet<{ title: string; status: string; body: string; refs: { type: string; id: string }[] }[]>(page, "/api/suggestions");
    const idea = ideas.find((s) => s.status === "new" && s.body.includes("https://www.gesetze-im-internet.de/"));
    expect(idea, "a new Idea naming the law by its address").toBeTruthy();
    const addresses = idea!.body.match(/https:\/\/[^\s]+/g)!;
    expect(addresses.length, "the Idea names the law and the advice service").toBeGreaterThanOrEqual(2);
    const letters = idea!.refs.filter((r) => r.type === "document").map((r) => `/documents/${r.id}`);

    await page.setViewportSize({ width: 320, height: 640 });
    for (const path of ["/", ...letters]) {
      await open(page, path);
      const heading = page.getByRole("main").getByRole("heading", { level: 3, name: shownAs(idea!.title) });
      // on Today a low-priority Idea may wait behind "Show more"; a cut body opens with "Read more"
      if (!(await heading.count())) await page.getByRole("button", { name: /^Show \d+ more Ideas?$/ }).click();
      await expect(heading).toBeVisible();
      const card = heading.locator("xpath=ancestor::*[self::article or self::li][1]");
      const more = card.getByRole("button", { name: "Read more" });
      if (await more.count()) await more.click();
      for (const address of addresses) {
        // the link is named by its site ("gesetze-im-internet.de", its hyphens unbreakable) and opens the address in a new tab
        const host = new URL(address).hostname.replace(/^www\./, "");
        const link = card.getByRole("link", { name: new RegExp(`^${host.replace(/\./g, "\\.").replace(/-/g, "[-\\u2011]")}`) });
        await link.scrollIntoViewIfNeeded();
        await expect(link, `${address} on ${path}`).toBeVisible();
        await expect(link).toHaveAttribute("target", "_blank");
        await expect(link).toHaveAttribute("href", address);
      }
      expect(await sideways(page), `${path} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  });
});
