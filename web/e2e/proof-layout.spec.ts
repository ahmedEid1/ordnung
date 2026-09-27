/**
 * Proof of sending, "Waiting for" and call notes against the real demo, from 320 px phones to a
 * 1920 px desktop: a cancellation sent by Einschreiben (tracking number, a posting receipt), a phone
 * call with a promise. Nothing sticks out of the proof card, the Waiting-for rows or the drawer's
 * Calls; the page never scrolls sideways; targets are at least 24 px; axe passes in light and dark.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { apiGet, expect, expectNoRawEnums, open, setTour, settle, test } from "./helpers";

const CLIENT = { "X-Ordnung-Client": "web" };
const TRACKING = "RT 123 456 785 DE";

interface Setup {
  draftId: string;
  partyId: string;
  partyName: string;
}

interface DraftRow {
  id: string;
  status: string;
  tracking_number: string | null;
  contract_id: string | null;
}

/** A small, well-formed one-page PDF standing in for the scan of the posting receipt. */
function receiptPdf(): Buffer {
  const text = `BT /F1 16 Tf 30 150 Td (Einlieferungsbeleg ${TRACKING}) Tj 0 -24 Td (22.09.2026 14:32) Tj ET`;
  const objects = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/Parent 2 0 R/MediaBox[0 0 420 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
    `<</Length ${text.length}>>\nstream\n${text}\nendstream`,
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/**
 * The FunkNetz cancellation, sent by Einschreiben with its tracking number and a posting receipt,
 * and a call with FunkNetz whose promise is overdue. Made once per demo run (the tests share it).
 */
async function setUp(page: Page): Promise<Setup> {
  const contracts = await apiGet<{ id: string; name: string | null; party_id: string | null }[]>(page, "/api/contracts");
  const contract = contracts.find((c) => /FunkNetz/.test(c.name ?? ""));
  expect(contract, "the FunkNetz contract").toBeTruthy();
  const parties = await apiGet<{ id: string; name: string }[]>(page, "/api/parties");
  const party = parties.find((p) => p.id === contract!.party_id)!;
  const drafts = await apiGet<DraftRow[]>(page, "/api/drafts");
  const done = drafts.find((d) => d.contract_id === contract!.id && d.status === "sent" && d.tracking_number);
  if (done) return { draftId: done.id, partyId: party.id, partyName: party.name };

  const made = await page.request.post("/api/drafts", { data: { kind: "cancellation", contract_id: contract!.id }, headers: CLIENT });
  expect(made.status(), "draft the cancellation").toBe(201);
  const draftId = ((await made.json()) as { id: string }).id;
  const sent = await page.request.post(`/api/drafts/${draftId}/sent`, { data: { channel: "registered_letter", date: "2026-09-22", tracking_number: TRACKING }, headers: CLIENT });
  expect(sent.ok(), "mark it sent").toBe(true);
  const proof = await page.request.post(`/api/drafts/${draftId}/proofs`, {
    multipart: { file: { name: "Einlieferungsbeleg.pdf", mimeType: "application/pdf", buffer: receiptPdf() }, kind: "posting_receipt", on_date: "2026-09-22", note: "Filiale Musterstadt-Mitte, 14:32" },
    headers: CLIENT,
  });
  expect(proof.status(), "add the posting receipt").toBe(201);
  const call = await page.request.post("/api/calls", {
    data: { party_id: party.id, called_on: "2026-09-23", contact: "Frau Weber, Kundenservice", summary: "Asked whether the cancellation arrived. She could see it and said the confirmation goes out this week.", promise: "Written confirmation of the cancellation", promise_due: "2026-09-26" },
    headers: CLIENT,
  });
  expect(call.status(), "note the call").toBe(201);
  return { draftId, partyId: party.id, partyName: party.name };
}

/** Layout faults inside each element `boxes` matches: things sticking out, small targets, sideways scroll. */
function faultsIn(boxes: Locator) {
  return boxes.evaluateAll((els) => {
    const faults: string[] = [];
    const describe = (el: Element) => `${el.tagName.toLowerCase()} "${(el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 40)}"`;
    if (document.documentElement.scrollWidth > window.innerWidth) faults.push(`page scrolls sideways (${document.documentElement.scrollWidth}px)`);
    if (!els.length) faults.push("nothing to check");
    for (const box of els) {
      const b = box.getBoundingClientRect();
      for (const el of Array.from(box.querySelectorAll("*"))) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height || el.closest(".sr-only")) continue;
        if (r.right > b.right + 1 || r.left < b.left - 1) faults.push(`sticks out: ${describe(el)} ${Math.round(r.left)}–${Math.round(r.right)} of ${Math.round(b.left)}–${Math.round(b.right)}`);
        if (el.matches("a[href], button, summary, select, input:not([type=hidden])") && r.height < 24 && r.width < 24) faults.push(`small target: ${describe(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
        if (el.matches("a[href], button") && r.height < 24 && !el.closest("p")) faults.push(`short target: ${describe(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
      }
    }
    return faults;
  });
}

let setup: Setup | null = null;

test.beforeEach(async ({ page }) => {
  await setTour(page, null);
  setup ??= await setUp(page);
});

for (const width of [320, 390, 768, 1280, 1920]) {
  test(`proof, Waiting for and Calls fit at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { draftId, partyId, partyName } = setup!;

    await open(page, `/letters/${draftId}`);
    const proof = page.getByRole("region", { name: "Proof of sending" });
    await expect(proof.getByText(TRACKING, { exact: true })).toBeVisible();
    await expect(proof.getByText("Check digit correct", { exact: true })).toBeVisible();
    await expect(proof.getByRole("link", { name: /Download Nachweis/ })).toBeVisible();
    await expect(proof).toContainText("Whether a proof is enough is for a court to decide");
    expect(await faultsIn(proof), `proof card at ${width}`).toEqual([]);

    await proof.getByRole("button", { name: "Add proof" }).click();
    const dialog = page.getByRole("dialog", { name: "Add proof" });
    await expect(dialog.getByText(/never sent to AI/)).toBeVisible();
    await settle(page);
    expect(await faultsIn(dialog), `Add proof at ${width}`).toEqual([]);
    await dialog.getByRole("button", { name: "Cancel" }).click();

    await open(page, "/letters/waiting", "Waiting for");
    await expect(page.getByRole("region", { name: /Overdue/ })).toContainText("Written confirmation of the cancellation");
    await expect(page.getByRole("region", { name: /^Waiting/ })).toContainText(TRACKING);
    expect(await faultsIn(page.getByRole("main").locator("ul.card > li")), `Waiting for at ${width}`).toEqual([]);
    await expectNoRawEnums(page, `/letters/waiting at ${width}`);

    await page.goto(`/letters?party=${partyId}`);
    const drawer = page.getByRole("dialog", { name: partyName });
    const calls = drawer.getByRole("region", { name: /^Calls/ });
    await expect(calls).toContainText("Frau Weber, Kundenservice");
    await calls.getByRole("button", { name: "Note a call" }).click();
    await calls.getByRole("button", { name: "Save note" }).click();
    await expect(calls.getByText("Write down what was said.")).toBeVisible();
    await calls.scrollIntoViewIfNeeded();
    await settle(page);
    expect(await faultsIn(calls), `Calls at ${width}`).toEqual([]);
  });
}

for (const scheme of ["light", "dark"] as const) {
  test(`proof, Waiting for and Calls pass axe (${scheme})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: scheme });
    await page.addInitScript((t) => localStorage.setItem("ordnung.theme", t), scheme);
    const { draftId, partyId, partyName } = setup!;
    const scan = async (include: string, what: string) => {
      await settle(page);
      const results = await new AxeBuilder({ page }).include(include).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(
        results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
        `${what} (${scheme})`,
      ).toEqual([]);
    };
    await open(page, `/letters/${draftId}`);
    await scan('section[aria-labelledby="proof-title"]', "proof card");
    await page.getByRole("region", { name: "Proof of sending" }).getByRole("button", { name: "Add proof" }).click();
    await expect(page.getByRole("dialog", { name: "Add proof" })).toBeVisible();
    await scan('[role="dialog"]', "Add proof");
    await page.keyboard.press("Escape");
    await open(page, "/letters/waiting", "Waiting for");
    await scan("main", "Waiting for");
    await page.goto(`/letters?party=${partyId}`);
    const calls = page.getByRole("dialog", { name: partyName }).getByRole("region", { name: /^Calls/ });
    await calls.getByRole("button", { name: "Note a call" }).click();
    await expect(calls.getByRole("form", { name: "Note a call" })).toBeVisible();
    await scan('[role="dialog"]', "drawer with the call form");
  });
}

test("keyboard focus never falls to <body> after the proof, Waiting-for and call actions", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { draftId, partyId, partyName } = setup!;

  // tracking number: Remove → the field (with Undo in the toast); Undo → "Change"
  await open(page, `/letters/${draftId}`);
  const proof = page.getByRole("region", { name: "Proof of sending" });
  await proof.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(proof.getByRole("textbox", { name: "Tracking number" })).toBeFocused();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(proof.getByRole("button", { name: "Change", exact: true })).toBeFocused();
  // the number never breaks inside: plain spaces in a no-wrap element, no-break spaces in running text
  expect(await proof.getByText(TRACKING, { exact: true }).evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
  expect(await proof.getByRole("region", { name: "Timeline" }).getByText(/^Tracking number/).textContent()).toContain("RT 123 456 785 DE");

  // "I got an answer" on the letter's box: the box keeps focus; Undo brings the button back
  await proof.getByRole("button", { name: "I got an answer — close this" }).click();
  await expect(page.locator("#proof-waiting")).toBeFocused();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(proof.getByRole("button", { name: "I got an answer — close this" })).toBeVisible();

  // Waiting for: a closed row hands focus to the row now in its place; Undo puts it back on the row
  await open(page, "/letters/waiting", "Waiting for");
  const letterRow = page.getByRole("main").getByRole("listitem").filter({ hasText: "A written confirmation of the end date" });
  await letterRow.getByRole("button", { name: "I got an answer — close this" }).click();
  await expect(letterRow).toHaveCount(0);
  await expect(page.locator("[data-waiting-heading]:focus, main h1:focus")).toHaveCount(1);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("heading", { name: "A written confirmation of the end date" })).toBeFocused();

  // Calls: the form opens on its first field, a failed save focuses what's missing, Save and Cancel
  // return to "Note a call", a deleted note hands focus to the section heading
  await page.goto(`/letters?party=${partyId}`);
  const calls = page.getByRole("dialog", { name: partyName }).getByRole("region", { name: /^Calls/ });
  await calls.getByRole("button", { name: "Note a call" }).click();
  const form = calls.getByRole("form", { name: "Note a call" });
  await expect(form.getByLabel("When")).toBeFocused();
  await form.getByRole("button", { name: "Save note" }).click();
  await expect(form.getByLabel("What was said")).toBeFocused();
  await form.getByRole("button", { name: "Cancel" }).click();
  await expect(calls.getByRole("button", { name: "Note a call" })).toBeFocused();
  await calls.getByRole("button", { name: "Note a call" }).click();
  await form.getByLabel("What was said").fill("A quick call to check the address — nothing promised.");
  await form.getByRole("button", { name: "Save note" }).click();
  await expect(calls.getByRole("button", { name: "Note a call" })).toBeFocused();
  const note = calls.getByRole("listitem").filter({ hasText: "A quick call to check the address" });
  await note.getByRole("button", { name: /^Delete the note/ }).click();
  await note.getByRole("group", { name: "Delete this note?" }).getByRole("button", { name: "Delete" }).click();
  await expect(note).toHaveCount(0);
  await expect(calls.getByRole("heading", { name: /^Calls/ })).toBeFocused();
});
