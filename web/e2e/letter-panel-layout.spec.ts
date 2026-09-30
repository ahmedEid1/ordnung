/**
 * The letter page's panel on real pages (UI audit round 1): key facts, reference numbers and bank
 * details are never cut ("RE-2…", "DE51 / 1234 / …") and an IBAN breaks only between its groups; the
 * contract card fits a 320 px phone; a scam letter's demand is no to-do; the calendar sweep and the
 * verdict's own payment don't come back under "Ideas".
 */
import type { Locator, Page } from "@playwright/test";
import type { Contract } from "@/api/types";
import { apiGet, expect, letterId, letterItem, open, openMail, setTour, shownAs, test } from "./helpers";

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
});

/** The parking fine, a photographed letter (by its sample's file name: its title is the model's). */
const FINE = "21_verwarnungsgeld_parken.jpg";

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

/** Open the demo letter read from the sample `file` (never found by its title: the model writes it anew with each recording). */
async function openLetter(page: Page, file: string): Promise<string> {
  const id = await letterId(page, file);
  await open(page, `/documents/${id}`);
  return id;
}

test.describe("phone 320 px: the letter panel", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("key facts, references and bank details are never cut; the IBAN keeps its groups whole", async ({ page }) => {
    await openLetter(page, FINE);
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
    // The hardest card to fit, chosen by what the test needs rather than by a letter: the contract with a price
    // and the longest name (with prompt 11 the liability insurance's "Privat-Haftpflichtversicherung, Tarif Basis
    // Single"), on the letter it was read from. The health insurance notice this test used has no contract since
    // prompt 11 ("We couldn't match this letter to one of your contracts"), and a re-recording may rename or
    // re-link any contract.
    const contracts = await apiGet<Contract[]>(page, "/api/contracts");
    const priced = contracts.filter((c) => c.cost_amount != null && c.source_doc_id);
    expect(priced.length, "a demo contract with a price, read from a letter").toBeGreaterThan(0);
    const contract = priced.reduce((longest, c) => (c.name.length > longest.name.length ? c : longest));
    const id = contract.source_doc_id!;
    const detail = await apiGet<{ contracts: { id: string }[] }>(page, `/api/documents/${id}`);
    expect(detail.contracts.map((c) => c.id), `the letter “${contract.name}” was read from shows that one contract`).toEqual([contract.id]);
    await open(page, `/documents/${id}`);
    const card = page.getByRole("region", { name: "Contract" }).locator(".card").first();
    await expect(card).toContainText(shownAs(contract.name));
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
  const id = await openLetter(page, FINE);
  await expect(page.getByRole("region", { name: "Key facts" })).toBeVisible();
  // (however many dates the recording has)
  await expect(page.getByText(/^Add your \d+ dates? to your calendar/)).toHaveCount(0);
  // the payment's Idea is its to-do's title and when to pay: that title is the model's, read from the API
  const payment = await letterItem(page, id, "payment");
  await expect(page.getByText(new RegExp(`^${shownAs(payment.title).source}: pay by`))).toHaveCount(0);
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
