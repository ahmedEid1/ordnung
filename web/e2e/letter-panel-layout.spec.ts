/**
 * The letter page's panel on real pages (UI audit round 1): key facts, reference numbers and bank
 * details are never cut ("RE-2…", "DE51 / 1234 / …") and an IBAN breaks only between its groups; the
 * contract card fits a 320 px phone; a scam letter's demand is no to-do; the calendar sweep and the
 * verdict's own payment don't come back under "Ideas".
 */
import type { Locator, Page } from "@playwright/test";
import { apiGet, documentId, expect, open, openMail, setTour, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** Text inside `root` that is cut off (an ellipsis, or clipped by its box), with its full text. */
async function cutText(root: Locator): Promise<string[]> {
  return root.evaluate((el) => {
    const out: string[] = [];
    for (const node of el.querySelectorAll<HTMLElement>("*")) {
      // (screen-reader-only text is clipped on purpose)
      if (node.closest("svg, .sr-only") || !node.textContent?.trim()) continue;
      const s = getComputedStyle(node);
      const clipsX = s.overflowX !== "visible" && node.scrollWidth > node.clientWidth + 1;
      if (s.textOverflow === "ellipsis" && clipsX) out.push(`ellipsis: "${node.textContent.trim()}"`);
      else if (clipsX && !node.matches(".card")) out.push(`clipped: "${node.textContent.trim()}"`);
    }
    return out;
  });
}

/** The lines an IBAN group spans (1 when it never splits). */
async function ibanGroupLines(root: Locator): Promise<number[]> {
  return root.evaluate((el) => {
    const iban = [...el.querySelectorAll("dt")].find((dt) => dt.textContent?.trim() === "IBAN")?.nextElementSibling;
    return [...(iban?.querySelectorAll<HTMLElement>(".whitespace-nowrap") ?? [])].map((g) => g.getClientRects().length);
  });
}

async function openLetter(page: Page, title: RegExp) {
  await open(page, `/documents/${await documentId(page, title)}`);
}

test.describe("phone 320 px: the letter panel", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("key facts, references and bank details are never cut; the IBAN keeps its groups whole", async ({ page }) => {
    await openLetter(page, /Verwarnungsgeld/);
    const facts = page.getByRole("region", { name: "Key facts" });
    await expect(facts.getByText(/^32\.4.VW.2026.0184512$/)).toBeVisible();
    await expect(facts.getByText("Stadtkasse Musterstadt")).toBeVisible();
    expect(await cutText(facts)).toEqual([]);
    const groups = await ibanGroupLines(facts);
    expect(groups.length).toBeGreaterThan(4);
    expect(groups.every((n) => n === 1)).toBe(true);
  });

  test("no letter's key facts cut a value", async ({ page }) => {
    test.setTimeout(180_000);
    const docs = await apiGet<{ id: string; title: string | null }[]>(page, "/api/documents");
    const cut: string[] = [];
    for (const doc of docs) {
      await open(page, `/documents/${doc.id}`);
      const facts = page.getByRole("region", { name: "Key facts" });
      if (!(await facts.count())) continue;
      for (const problem of await cutText(facts)) cut.push(`${doc.title ?? doc.id}: ${problem}`);
    }
    expect(cut).toEqual([]);
  });

  test("the contract card keeps its name and price inside the card", async ({ page }) => {
    await openLetter(page, /Health Insurance Contribution/);
    const card = page.getByRole("region", { name: "Contract" }).locator(".card").first();
    const box = (await card.boundingBox())!;
    const inside = await card.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return [...el.querySelectorAll("*")].every((n) => n.getBoundingClientRect().right <= r.right + 0.5);
    });
    expect(inside).toBe(true);
    expect(box.x + box.width).toBeLessThanOrEqual(320);
    await expect(card.getByRole("link", { name: /Open in Contracts/ })).toHaveAttribute("href", /\/contracts\?contract=ctr_/);
  });
});

test("Ideas on a letter: not the verdict's payment again, not the calendar sweep", async ({ page }) => {
  await openLetter(page, /Verwarnungsgeld/);
  await expect(page.getByRole("region", { name: "Key facts" })).toBeVisible();
  await expect(page.getByText("Add your 26 dates to your calendar")).toHaveCount(0);
  await expect(page.getByText(/^Pay Verwarnungsgeld \(traffic fine\): pay by/)).toHaveCount(0);
});

test("a scam letter's demand is shown for what it is — no countdown, nothing to tick off", async ({ page }) => {
  await openMail(page, "Rundfunk-Beitragsservice");
  const todos = page.getByRole("region", { name: /^To-dos & dates/ });
  await expect(todos.getByText("Payment this letter demands — don't pay")).toBeVisible();
  await expect(todos.getByRole("button", { name: /as done$/ })).toHaveCount(0);
  await expect(todos.locator("time")).toHaveCount(0);
  await expect(todos).not.toContainText("transfer by");
  // its bank details are flagged, with nothing to copy
  const facts = page.getByRole("region", { name: "Key facts" });
  await expect(facts.getByText(/don.t pay to this account/)).toBeVisible();
  await expect(facts.getByRole("button", { name: "Copy IBAN" })).toHaveCount(0);
});
