/**
 * The verdict card and the page viewer on real pages (UI audit round 1): the verdict leads in English
 * and with the right to-do, its headline breaks German compounds only at their joints, and the page
 * viewer has no scroll box of its own on phones and tablets (a swipe scrolled only the box).
 */
import type { Locator, Page } from "@playwright/test";
import type { DocumentDetail } from "@/api/types";
import { apiGet, expect, letterId, letterItem, open, setTour, shownAs, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Open the demo letter read from the sample `file` (never found by its title: the model writes it anew with each recording). */
async function openLetter(page: Page, file: string) {
  await open(page, `/documents/${await letterId(page, file)}`);
}

/**
 * A to-do the server set aside as history (already past when its letter was added) on some demo letter, found
 * through the API: which letter has one depends on the recording. Fails when none has.
 */
async function historyItem(page: Page): Promise<{ docId: string; title: string }> {
  for (const doc of await apiGet<{ id: string }[]>(page, "/api/documents")) {
    const detail = await apiGet<DocumentDetail>(page, `/api/documents/${doc.id}`);
    const aside = detail.set_aside.find((a) => a.reason === "history");
    const item = aside && detail.items.find((i) => i.id === aside.item_id);
    if (item) return { docId: doc.id, title: item.title };
  }
  throw new Error("no demo letter has a to-do that was already past when the letter was added (set aside as history)");
}

/** Words of `el` broken across two lines without a hyphen (a compound cut mid-syllable). */
async function brokenWords(el: Locator): Promise<string[]> {
  return el.evaluate((root) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
      const text = node.data;
      for (const m of text.matchAll(/[\p{L}\u00ad]{8,}/gu)) {
        const range = document.createRange();
        range.setStart(node, m.index!);
        range.setEnd(node, m.index! + m[0].length);
        const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
        // a break at a soft hyphen shows a hyphen: fine; anywhere else it cut the word
        if (lines.size > 1 && !m[0].includes("\u00ad")) out.push(m[0]);
      }
    }
    return out;
  });
}

test.describe("phone 320 px: the verdict", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("the headline never cuts a German compound mid-word and the page never scrolls sideways", async ({ page }) => {
    // Since extraction prompt 11 no demo title carries a long German compound, so each letter is shown with the
    // title an earlier recording gave it, the letter's German term in brackets: the page's own answer is
    // rewritten in the browser, the shared demo stays as it is.
    for (const [file, title] of [
      ["11_immatrikulationsbescheinigung_wise_2026.pdf", "Certificate of Enrolment (Immatrikulationsbescheinigung) for Winter Semester 2026/27"],
      ["13_nebenkostenabrechnung_2025.pdf", "Operating and Heating Cost Statement 2025 (Betriebs- und Heizkostenabrechnung) – Wohnbau Musterstadt eG"],
      ["15_mahnung_techmarkt.pdf", "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213"],
    ] as const) {
      const id = await letterId(page, file);
      await page.route(
        (url) => url.pathname === `/api/documents/${id}`,
        async (route) => {
          if (route.request().method() !== "GET") return route.fallback();
          const response = await route.fetch();
          const detail = (await response.json()) as { document: object };
          await route.fulfill({ response, json: { ...detail, document: { ...detail.document, title } } });
        },
      );
      await open(page, `/documents/${id}`);
      const h1 = page.getByRole("article").first().getByRole("heading", { level: 1 });
      await expect(h1).toContainText(shownAs(title));
      expect(await brokenWords(h1), title).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${title} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  });

  test("leads in English, with the letter's German below it", async ({ page }) => {
    // Since extraction prompt 11 the semester fee's to-do is read in English (title, action and consequence), and
    // no demo to-do is read in German any more. So the fee is shown as an earlier recording read it, in the
    // letter's German: the page's own answer is rewritten in the browser, the shared demo stays as it is.
    const id = await letterId(page, "10_rueckmeldung_sose_2027.pdf"); // the semester fee
    const fee = await letterItem(page, id, "payment");
    const german = {
      title: "Semesterbeitrag Sommersemester 2027 zahlen",
      action: "Semesterbeitrag von 312,40 € rechtzeitig überweisen",
      consequence: "Bei späterem Zahlungseingang wird eine Säumnisgebühr von 15,00 € erhoben. Ohne fristgerechte Rückmeldung droht die Exmatrikulation.",
    };
    await page.route(
      (url) => url.pathname === `/api/documents/${id}`,
      async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        const response = await route.fetch();
        const detail = (await response.json()) as { items: { id: string }[] };
        const items = detail.items.map((item) => (item.id === fee.id ? { ...item, ...german } : item));
        await route.fulfill({ response, json: { ...detail, items } });
      },
    );
    await open(page, `/documents/${id}`);
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText(/^Pay €312\.40 to /)).toBeVisible();
    await expect(verdict.getByText(/^The letter warns of a late fee/)).toBeVisible();
    await expect(verdict.locator("q[lang=de]").first()).toContainText("Semesterbeitrag");
  });
});

test.describe("phone 390 px: what the verdict leads with, and the viewer", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("an invoice its payment reminder replaced sends you to the reminder — never Pay twice", async ({ page }) => {
    await openLetter(page, "08_rechnung_techmarkt.pdf");
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText("Nothing to pay on this letter — a payment reminder replaced it.")).toBeVisible();
    await expect(verdict.getByRole("button", { name: /^Pay/ })).toHaveCount(0);
    await expect(verdict.getByText(/overdue/)).toHaveCount(0);
    await expect(verdict.getByRole("link", { name: /Open the payment reminder/ })).toBeVisible();
    // the list below says so too, uncounted (UI audit round 2: "25 days overdue" in red under this verdict)
    const todos = page.getByRole("region", { name: /To-dos & dates/ });
    await expect(todos).not.toContainText("overdue");
    await expect(todos).toContainText("Replaced by the payment reminder of");
    await expect(todos.getByRole("heading", { level: 2 })).toContainText("0 open");
  });

  // This was one test on the lease, whose deposit was due before the letter was added. Since prompt 11 the deposit
  // has no due date, so it is no longer history: the "Still open?" half runs on whichever letter has a to-do the
  // server set aside as history (with prompt 11, the electricity contract's meter reading), the lease keeps the
  // Contract half.
  test("a to-do already past when its letter was added is 'Still open?', not '362 days overdue'", async ({ page }) => {
    const history = await historyItem(page);
    await open(page, `/documents/${history.docId}`);
    const verdict = page.getByRole("article").first();
    await expect(verdict.getByText(/overdue/)).toHaveCount(0);
    await expect(verdict.getByRole("list", { name: "Probably dealt with" })).toContainText(shownAs(`Still open? ${history.title}`));
    // … and so does the list below (UI audit round 2)
    const todos = page.getByRole("region", { name: /To-dos & dates/ });
    await expect(todos).not.toContainText("overdue");
    await expect(todos).toContainText("Already past when the letter was added");
  });

  test("the lease you can cancel any month has no 'decide by'", async ({ page }) => {
    // (UI audit round 2: "decide by … tomorrow" on a lease)
    await openLetter(page, "03_mietvertrag.pdf");
    const contract = page.getByRole("region", { name: "Contract" });
    await expect(contract).toContainText("Cancel any time");
    await expect(contract).not.toContainText(/decide by/i);
  });

  test("the pages are no scroll box of their own; the pager turns them", async ({ page }) => {
    await openLetter(page, "13_nebenkostenabrechnung_2025.pdf"); // two pages
    const pages = page.getByRole("region", { name: "Letter pages" });
    const images = pages.getByRole("group", { name: "Page images" });
    const box = await images.evaluate((el) => ({ overflowY: getComputedStyle(el).overflowY, scroll: el.scrollHeight - el.clientHeight }));
    expect(box.overflowY).not.toMatch(/auto|scroll/);
    expect(box.scroll).toBeLessThanOrEqual(1);
    const pager = pages.getByRole("navigation", { name: "Turn pages" });
    await pager.getByRole("button", { name: "Next" }).click();
    await expect(pages.getByRole("img", { name: "Page 2 of 2" })).toBeVisible();
  });

  test("a fact on a photo: the quote sits under the photo, Escape closes it, and 'Back to …' returns", async ({ page }) => {
    await openLetter(page, "18_reisepass.jpg"); // a photo
    const chip = page.getByRole("button", { name: /show “.*” on the page/ }).first();
    await chip.scrollIntoViewIfNeeded();
    const before = (await chip.boundingBox())!.y;
    await chip.click();
    const quote = page.getByTestId("evidence-quote");
    await expect(quote).toBeVisible();
    const photo = (await page.getByRole("img", { name: /^Page 1 of/ }).boundingBox())!;
    expect((await quote.boundingBox())!.y).toBeGreaterThanOrEqual(photo.y + photo.height - 1);
    await page.keyboard.press("Escape");
    await expect(quote).toHaveCount(0);
    await page.getByRole("button", { name: /^Back to/ }).click();
    await expect.poll(async () => Math.round((await chip.boundingBox())!.y)).toBe(Math.round(before));
  });
});
