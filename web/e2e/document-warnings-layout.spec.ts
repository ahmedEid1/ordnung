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
  document: { warnings: string[] };
  items: { title: string; status: string; evidence: { grounding: string; value_consistent: boolean }[] }[];
}

/** The reading's own count of the dates it couldn't confirm ("1 date could not be confirmed against the letter's text."). */
const UNCONFIRMED_COUNT = /^\d+ dates? could not be confirmed against the letter/;

// UI audit round 1 (document-c): "Please check" three times on one letter. Prompt 11 reads the working-student
// contract with nothing left to check, so the letter is the residence permit's appointment: a to-do whose date
// doesn't match the sentence it came from (a card of its own), a warning of the reading's own (the passport's
// validity) and the reading's count of the dates it couldn't confirm, which that to-do's card already says —
// two things to check, each said once.
test("the residence-permit appointment says 'Please check' once per thing to check", async ({ page }) => {
  const id = await letterId(page, "17_auslaenderbehoerde_termin.pdf");
  const { document, items } = await apiGet<CheckedLetter>(page, `/api/documents/${id}`);
  const toCheck = items.filter((i) => i.status === "open" && i.evidence.some((e) => e.grounding === "unverified" || !e.value_consistent));
  const own = document.warnings.filter((w) => !UNCONFIRMED_COUNT.test(w));
  expect(
    { toCheck: toCheck.length, own: own.length, counted: document.warnings.some((w) => UNCONFIRMED_COUNT.test(w)) },
    "the reading leaves one to-do, one warning of its own and its count of unconfirmed dates",
  ).toEqual({ toCheck: 1, own: 1, counted: true });

  await open(page, `/documents/${id}`);
  const warnings = page.getByRole("region", { name: "Warnings and things to check" });
  await expect(warnings).toBeVisible();
  await expect(warnings.getByRole("heading", { level: 2, name: "Please check" })).toHaveCount(2);
  await expect(warnings).toContainText(shownAs(toCheck[0]!.title));
  await expect(warnings).toContainText(shownAs(own[0]!));
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
