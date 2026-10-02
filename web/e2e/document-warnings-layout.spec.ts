/**
 * The letter page's warnings, Pay panel, footer and not-found page on real pages (UI audit round 1,
 * document-c): "Please check" once per thing to check, no checksum warning a valid IBAN contradicts, an IBAN
 * that breaks only between its groups in a 320 px Pay sheet whose buttons stay in view, no "Draft a reply"
 * under a passport, and a not-found page with its h1 and a way back.
 */
import type { Locator, Page } from "@playwright/test";
import { apiGet, expect, letterId, open, openMail, setTour, shownAs, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Open the demo letter read from the sample `file` (never found by its title: the model writes it anew with each recording). */
async function openLetter(page: Page, file: string) {
  await open(page, `/documents/${await letterId(page, file)}`);
}

/** The lines each IBAN group spans in `root` (1 when it never splits). */
async function ibanGroupLines(root: Locator): Promise<number[]> {
  return root.evaluate((el) => [...el.querySelectorAll<HTMLElement>(".font-ident .whitespace-nowrap")].map((g) => g.getClientRects().length));
}

test.describe("phone 320 px", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("the Pay sheet keeps the IBAN's groups whole, says when to transfer, and its buttons stay in view", async ({ page }) => {
    await openLetter(page, "15_mahnung_techmarkt.pdf"); // the payment reminder
    await page.getByRole("button", { name: /^Pay €/ }).first().click();
    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText("Transfer by", { exact: true })).toBeVisible();
    await expect(sheet.getByText(/\(must arrive .+\)/)).toBeVisible();
    const groups = await ibanGroupLines(sheet);
    expect(groups.length).toBe(6);
    expect(groups.every((n) => n === 1)).toBe(true);
    await expect(sheet.getByRole("button", { name: "Copy IBAN" })).toBeVisible();
    // the sheet scrolls; "Mark as paid" is on screen without scrolling it
    await expect(sheet.getByRole("button", { name: "Mark as paid" })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("a passport's footer offers no reply, and its provenance chip is no stretched pill", async ({ page }) => {
    await openLetter(page, "18_reisepass.jpg");
    const footer = page.locator("footer").filter({ hasText: /Read by Claude|Kept private|Not read yet/ });
    await footer.scrollIntoViewIfNeeded();
    await expect(footer.getByRole("button", { name: "Draft a reply" })).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Delete" })).toBeVisible();
    const chip = footer.locator("p").first();
    const radius = await chip.evaluate((el) => parseFloat(getComputedStyle(el).borderTopLeftRadius));
    expect(radius).toBeLessThan(20);
  });
});

interface CheckedLetter {
  document: { filename: string; title: string | null; warnings: string[]; hidden_text: boolean };
  items: { title: string; status: string; evidence: { grounding: string; value_consistent: boolean }[] }[];
  scam_signs: string[];
}

/** The reading's own count of the dates it couldn't confirm ("1 date could not be confirmed against the letter's text."). */
const UNCONFIRMED_COUNT = /^\d+ dates? could not be confirmed against the letter/;

/** A warning as its card shows it: a "Please check:" prefix goes under the card's own heading. */
const withoutPleaseCheck = (w: string) => {
  const rest = w.replace(/^please check\s*[:—–-]\s*/i, "");
  return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : w;
};

interface LetterDetail {
  document: CheckedLetter["document"];
  items: (CheckedLetter["items"][number] & { id: string; grounding: string })[];
  scam_signs: string[];
}

/**
 * The open to-dos to check (their quote wasn't found or doesn't match) and the reading's own warnings of
 * `detail`, as the letter page sorts them: the count of unconfirmed dates is said by the to-dos' own cards,
 * and the hidden-text warning has a banner of its own (Warnings.tsx), so neither is a "Please check".
 */
function toCheckOf({ document, items }: LetterDetail): { toCheck: string[]; own: string[] } {
  return {
    toCheck: items
      .filter((i) => i.status === "open" && i.grounding !== "user" && (i.grounding === "unverified" || i.evidence.some((e) => e.grounding === "unverified" || !e.value_consistent)))
      .map((i) => i.title),
    own: document.warnings.map((w) => w.trim()).filter((w) => w && !UNCONFIRMED_COUNT.test(w) && !(document.hidden_text && /hidden text/i.test(w))),
  };
}

// UI audit round 1 (document-c): "Please check" three times on one letter — a to-do whose date doesn't match
// the sentence it came from (a card of its own), a warning of the reading's own (a card for all of them) and
// the reading's count of the dates it couldn't confirm, which that to-do's card already says. Each recording
// of the demo left the count on another letter (with prompt 11 the residence permit's appointment, then the
// broadcasting fee, whose day is now read from its letter) and the final one on none, so the test makes the
// state itself: it serves the demo letter with an open to-do and the most warnings of its own as a reading
// that couldn't confirm that to-do's date would come back — the count among its warnings, the to-do's date
// not matching its quote — and expects one heading per to-do to check plus one for the reading's own
// warnings, if it has any, and the count nowhere.
test("a letter whose reading counts unconfirmed dates says 'Please check' once per thing to check", async ({ page }) => {
  const docs = await apiGet<{ id: string }[]>(page, "/api/documents");
  const details = await Promise.all(docs.map(({ id }) => apiGet<LetterDetail>(page, `/api/documents/${id}`).then((detail) => ({ id, detail }))));
  const open_ = (i: LetterDetail["items"][number]) => i.status === "open" && i.grounding !== "user" && i.evidence.length > 0;
  const candidates = details
    .filter(({ detail }) => !detail.scam_signs.length && detail.items.some(open_))
    .sort((a, b) => toCheckOf(b.detail).own.length - toCheckOf(a.detail).own.length);
  expect(candidates.length, "a demo letter with an open to-do (no scam letter)").toBeGreaterThan(0);
  const { id, detail } = candidates[0];
  const target = detail.items.find(open_)!;
  const unconfirmed: LetterDetail = {
    ...detail,
    document: { ...detail.document, warnings: [...detail.document.warnings, "1 date could not be confirmed against the letter's text."] },
    items: detail.items.map((i) => (i.id === target.id ? { ...i, evidence: i.evidence.map((e, n) => (n === 0 ? { ...e, value_consistent: false } : e)) } : i)),
  };
  await page.route(
    (url) => url.pathname === `/api/documents/${id}`,
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ response: await route.fetch(), json: unconfirmed });
    },
  );
  const { toCheck, own } = toCheckOf(unconfirmed);
  expect(toCheck).toContain(target.title);

  await open(page, `/documents/${id}`);
  const warnings = page.getByRole("region", { name: "Warnings and things to check" });
  await expect(warnings).toBeVisible();
  await expect(warnings.getByRole("heading", { level: 2, name: "Please check" })).toHaveCount(toCheck.length + (own.length ? 1 : 0));
  for (const title of toCheck) await expect(warnings).toContainText(shownAs(title));
  for (const w of own) await expect(warnings).toContainText(shownAs(withoutPleaseCheck(w)));
  await expect(page.getByRole("main").getByText(/could not be confirmed against the letter/)).toHaveCount(0);
});

test("the gym contract doesn't claim its valid IBAN fails the checksum", async ({ page }) => {
  await openLetter(page, "02_fitnessstudio_mitgliedsvertrag.pdf");
  await expect(page.getByRole("main")).not.toContainText(/does not pass the standard IBAN checksum/);
});

test("the scam letter doesn't repeat the hidden-text banner as a warning sign", async ({ page }) => {
  await openMail(page, "Rundfunk-Beitragsservice");
  const scam = page.getByRole("alert").filter({ hasText: "This looks like a scam" });
  await expect(scam).toBeVisible();
  const all = scam.getByRole("button", { name: /^Show all \d+ signs/ });
  if (await all.count()) await all.click();
  await expect(scam).not.toContainText(/addressed to an AI|KI-Assistent/);
  await expect(page.getByText("This document contains hidden text aimed at software — we ignored it")).toBeVisible();
});

test("a letter link that finds nothing has its h1 and a way back", async ({ page }) => {
  await open(page, "/documents/doc_does_not_exist", /^(This letter is no longer here|This letter isn't in your inbox)$/);
  await expect(page.getByRole("main").getByRole("link", { name: /^(Back to Inbox|Open New mail)$/ })).toHaveAttribute("href", "/inbox");
});
