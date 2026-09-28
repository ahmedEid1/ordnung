/**
 * The letter page's warnings, Pay panel, footer and not-found page on real pages (UI audit round 1,
 * document-c): "Please check" once per thing to check, no checksum warning a valid IBAN contradicts, an IBAN
 * that breaks only between its groups in a 320 px Pay sheet whose buttons stay in view, no "Draft a reply"
 * under a passport, and a not-found page with its h1 and a way back.
 */
import type { Locator, Page } from "@playwright/test";
import { documentId, expect, open, openMail, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

async function openLetter(page: Page, title: RegExp) {
  await open(page, `/documents/${await documentId(page, title)}`);
}

/** The lines each IBAN group spans in `root` (1 when it never splits). */
async function ibanGroupLines(root: Locator): Promise<number[]> {
  return root.evaluate((el) => [...el.querySelectorAll<HTMLElement>(".font-ident .whitespace-nowrap")].map((g) => g.getClientRects().length));
}

test.describe("phone 320 px", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("the Pay sheet keeps the IBAN's groups whole, says when to transfer, and its buttons stay in view", async ({ page }) => {
    await openLetter(page, /1st Payment Reminder/);
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
    await openLetter(page, /Passport/);
    const footer = page.locator("footer").filter({ hasText: /Read by Claude|Kept private|Not read yet/ });
    await footer.scrollIntoViewIfNeeded();
    await expect(footer.getByRole("button", { name: "Draft a reply" })).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Delete" })).toBeVisible();
    const chip = footer.locator("p").first();
    const radius = await chip.evaluate((el) => parseFloat(getComputedStyle(el).borderTopLeftRadius));
    expect(radius).toBeLessThan(20);
  });
});

test("the working-student contract says 'Please check' once per thing to check", async ({ page }) => {
  await openLetter(page, /working student contract/);
  // (the high-stakes spec may have re-filed it as a dismissal on the shared server: then its cards differ)
  const warnings = page.getByRole("region", { name: "Warnings and things to check" });
  await expect(warnings).toBeVisible();
  expect(await warnings.getByRole("heading", { level: 2, name: "Please check" }).count()).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main").getByText(/could not be confirmed against the letter/)).toHaveCount(0);
});

test("the gym contract doesn't claim its valid IBAN fails the checksum", async ({ page }) => {
  await openLetter(page, /Gym Membership Contract/);
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
