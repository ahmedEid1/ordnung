/**
 * UI audit round 1, the verdict card: English first (the letter's German as a quote), headlines that
 * break German compounds at their joints, the right to-do in front, the date that matters first,
 * started drafts, the disclaimer where a law was used and inside the action band.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail, Draft, Item } from "@/api/types";
import * as ToastModule from "@/components/ui/Toast";
import { formatRelativeDays } from "@/lib/format";
import { VerdictCard } from "./VerdictCard";
import { selectPrimaryItem } from "./verdict";
import { isGermanText } from "./fact-text";
import { makeDetail, makeDoc, makeItem, makeReceipt } from "./fixtures";

const TODAY = "2026-09-28";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderVerdict(detail: DocumentDetail) {
  const primary = selectPrimaryItem(detail.items, detail.set_aside);
  renderWithProviders(<VerdictCard detail={detail} primary={primary} />, { client: client() });
  return screen.getByRole("article");
}

/** Every text in `root` outside a `lang="de"` element (the German the card marks as the letter's). */
function englishTexts(root: HTMLElement): string[] {
  const clone = root.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[lang=de]").forEach((el) => el.remove());
  return [...clone.querySelectorAll("p, h1, h2, li")].map((el) => el.textContent?.trim() ?? "").filter(Boolean);
}

const semesterFee = makeItem({
  id: "fee",
  kind: "payment",
  title: "Semesterbeitrag Sommersemester 2027 zahlen",
  action: "Semesterbeitrag von 312,40 € rechtzeitig überweisen",
  consequence: "Bei späterem Zahlungseingang wird eine Säumnisgebühr von 15,00 € erhoben. Ohne fristgerechte Rückmeldung droht die Exmatrikulation (§ 51 Abs. 2 HG NRW).",
  amount: 312.4,
  currency: "EUR",
  direction: "out",
  priority: "high",
  due_date: "2027-01-15",
  send_by: "2027-01-14",
  computation: makeReceipt({ due_date: "2027-01-15", rule_ids: ["date_as_written", "bgb_675s"] }),
});

describe("the verdict leads in English", () => {
  it("never shows a German verdict field without an English companion", () => {
    const detail = makeDetail({
      document: makeDoc({ title: "Re-registration for Summer Semester 2027" }),
      party: { id: "p", name: "Hochschule Musterstadt" } as DocumentDetail["party"],
      items: [semesterFee],
    });
    const verdict = renderVerdict(detail);
    for (const text of englishTexts(verdict)) expect(isGermanText(text), text).toBe(false);
    expect(within(verdict).getByText("Pay €312.40 to Hochschule Musterstadt")).toBeInTheDocument();
    expect(within(verdict).getByText(/warns of a late fee and losing your place at the university/)).toBeInTheDocument();
    // the German follows, smaller, as the letter's words
    const quotes = verdict.querySelectorAll("q[lang=de]");
    // (money and citations are glued with non-breaking spaces)
    expect([...quotes].map((q) => q.textContent?.replace(/\u00a0/g, " "))).toEqual([semesterFee.action, expect.stringMatching(/^Bei späterem Zahlungseingang/)]);
    expect(quotes[0]!.closest("p")).toHaveTextContent(/^The letter says:/);
  });
});

describe("the headline", () => {
  it("breaks a German compound at its joint, keeps a reference whole and is a size smaller for very long words", () => {
    renderVerdict(makeDetail({ document: makeDoc({ title: "Certificate of Enrolment (Immatrikulationsbescheinigung) for Winter Semester 2026/27" }) }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toContain("Immatrikulations\u00adbescheinigung");
    expect(h1.querySelector("[lang=de]")).not.toBeNull();
    expect(h1).toHaveClass("text-detail-long", "wrap-break-word", "hyphens-manual");
    expect(h1.className).not.toContain("overflow-wrap:anywhere");
  });

  it("never breaks a reference number at its hyphens", () => {
    renderVerdict(makeDetail({ document: makeDoc({ title: "1st Payment Reminder (Mahnung) – Invoice TM-2026-0048213" }) }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toContain("TM\u20112026\u20110048213");
    expect(h1).toHaveClass("text-detail");
  });

  it("says 'arrived the same day' rather than repeating the date, in one date style", () => {
    const verdict = renderVerdict(makeDetail({ document: makeDoc({ doc_date: "2025-09-15", received_date: "2025-09-15" }) }));
    expect(within(verdict).getByText(/Letter of/)).toHaveTextContent("Letter of 15 Sep 2025, arrived the same day");
    const other = renderWithProviders(<VerdictCard detail={makeDetail({ document: makeDoc({ id: "d2", doc_date: "2026-09-01", received_date: "2026-09-03" }) })} primary={null} />, {
      client: client(),
    });
    expect(within(other.container).getByText(/Letter of/)).toHaveTextContent("Letter of 1 Sep, arrived 3 Sep");
  });
});

describe("the date box", () => {
  it("a transfer counts to the day it has to go out, the due date below", () => {
    const pay = makeItem({ kind: "payment", title: "Pay the reminder", amount: 94.99, currency: "EUR", direction: "out", due_date: "2026-09-30", send_by: "2026-09-29" });
    const verdict = renderVerdict(makeDetail({ items: [pay] }));
    const box = within(verdict).getByRole("heading", { name: "Transfer by" }).parentElement!;
    expect(within(box).getByText("Tue 29 Sep")).toBeInTheDocument();
    expect(within(box).getByText("tomorrow")).toBeInTheDocument();
    expect(box).toHaveTextContent("Due Wed 30 Sep — it has to reach their account by then.");
  });

  it("a direct debit says when it is collected, in quiet colours", () => {
    const debit = makeItem({
      kind: "payment",
      title: "Monthly fee",
      action: "Ensure sufficient funds for the SEPA direct debit.",
      amount: 63,
      currency: "EUR",
      direction: "out",
      due_date: "2026-10-01",
      send_by: "2026-09-30",
      recurrence: { interval: 1, unit: "months", working_day: null },
      computation: makeReceipt({ rule_ids: ["date_as_written", "bgb_675s"] }),
    });
    const verdict = renderVerdict(makeDetail({ items: [debit] }));
    const section = within(verdict).getByRole("heading", { name: "Collected on" }).parentElement!;
    expect(section.innerHTML).not.toMatch(/bg-danger|bg-warn/);
    expect(within(section).getByText("in 3 days")).toBeInTheDocument();
    // nothing a law worked out: no legal disclaimer
    expect(within(verdict).queryByText(/Not legal advice/)).toBeNull();
  });

  it("counts with the app's one formatter (the same words as the to-do list)", () => {
    const deadline = makeItem({ due_date: "2026-10-21" });
    const verdict = renderVerdict(makeDetail({ items: [deadline] }));
    expect(within(verdict).getByText(formatRelativeDays("2026-10-21", TODAY))).toBeInTheDocument();
    expect(within(verdict).getByText("in 3 weeks")).toBeInTheDocument();
  });
});

describe("what the verdict leads with", () => {
  it("an invoice its reminder replaced opens the reminder, never Pay", () => {
    const invoice = makeItem({ id: "inv", kind: "payment", title: "Pay TechMarkt Online invoice TM-2026-0048213", amount: 89.99, currency: "EUR", direction: "out", due_date: "2026-09-03" });
    const detail = makeDetail({
      items: [invoice],
      related: [makeDoc({ id: "doc_rem", doc_date: "2026-09-10", kind: "dunning" })],
      set_aside: [{ item_id: "inv", reason: "replaced", replaced_by: "doc_rem" }],
    });
    const verdict = renderVerdict(detail);
    expect(within(verdict).queryByRole("button", { name: /^Pay/ })).toBeNull();
    expect(within(verdict).queryByText(/overdue/)).toBeNull();
    expect(within(verdict).getByRole("link", { name: /Open the payment reminder/ })).toHaveAttribute("href", "/documents/doc_rem");
    expect(within(verdict).getByText("Nothing to pay on this letter — a payment reminder replaced it.")).toBeInTheDocument();
    expect(within(verdict).getByText(/^Pay the reminder/)).toHaveTextContent("Pay the reminder of Thu 10 Sep instead — pay once, not twice.");
    expect(within(verdict).queryByRole("list", { name: "Probably dealt with" })).toBeNull();
  });

  it("lists a replaced payment quietly when another to-do leads", () => {
    const invoice = makeItem({ id: "inv", kind: "payment", title: "Pay the invoice", amount: 89.99, currency: "EUR", direction: "out", due_date: "2026-09-03" });
    const task = makeItem({ id: "task", kind: "task", title: "Keep the receipt for the warranty" });
    const detail = makeDetail({
      items: [invoice, task],
      related: [makeDoc({ id: "doc_rem", doc_date: "2026-09-10", kind: "dunning" })],
      set_aside: [{ item_id: "inv", reason: "replaced", replaced_by: "doc_rem" }],
    });
    const verdict = renderVerdict(detail);
    const rows = within(verdict).getByRole("list", { name: "Probably dealt with" });
    expect(rows).toHaveTextContent("Pay the invoice — replaced by the payment reminder of Thu 10 Sep: pay that one, not both.");
    expect(within(rows).getByRole("link", { name: /Open the reminder/ })).toHaveAttribute("href", "/documents/doc_rem");
  });

  it("a date long past when the letter was read is a quiet 'Still open?' row, not '362 days overdue'", () => {
    const deposit = makeItem({ id: "dep", kind: "payment", title: "Security deposit (Kaution)", amount: 1560, currency: "EUR", direction: "out", due_date: "2025-10-01" });
    const rent = makeItem({ id: "rent", kind: "payment", title: "Monthly rent payment", action: "Pay the total rent by the third working day of each month.", amount: 640, recurrence: { interval: 1, unit: "months", working_day: null } });
    const verdict = renderVerdict(makeDetail({ items: [deposit, rent], set_aside: [{ item_id: "dep", reason: "history", replaced_by: null }] }));
    expect(within(verdict).getByText("Pay the total rent by the third working day of each month.")).toBeInTheDocument();
    expect(within(verdict).queryByText(/overdue/)).toBeNull();
    const row = within(verdict).getByRole("list", { name: "Probably dealt with" });
    expect(row).toHaveTextContent("Still open? Security deposit (Kaution) was due 1 Oct 2025");
    expect(within(row).getByRole("button", { name: "Mark “Security deposit (Kaution)” done" })).toBeInTheDocument();
  });
});

describe("the action band", () => {
  const objection = makeItem({
    id: "obj",
    title: "Object to the decision (Einspruch)",
    due_date: "2026-10-21",
    computation: makeReceipt({ rule_ids: ["posting_day", "bgb_187_1", "bgb_188"] }),
  });
  const remedy = { type: "einspruch" as const, addressee: "Finanzamt", period_text: null, form_text: null, quote: null };

  it("offers to continue a started objection instead of drafting a second one", () => {
    const draft = { id: "drf_1", kind: "objection", status: "draft", updated_at: "2026-09-27T10:00:00Z", doc_id: "doc_1" } as Draft;
    const verdict = renderVerdict(makeDetail({ document: makeDoc({ remedy }), items: [objection], drafts: [draft] }));
    expect(within(verdict).queryByRole("button", { name: "Draft objection" })).toBeNull();
    expect(within(verdict).getByRole("link", { name: "Continue your objection" })).toHaveAttribute("href", "/letters/drf_1");
  });

  it("keeps the disclaimer inside the band, and only where a law worked the date out", () => {
    const verdict = renderVerdict(makeDetail({ document: makeDoc({ remedy }), items: [objection] }));
    const disclaimer = within(verdict).getByText(/Not legal advice/);
    const band = within(verdict).getByRole("button", { name: "Mark done" }).closest(".bg-surface-2\\/40");
    expect(band).not.toBeNull();
    expect(band!.contains(disclaimer)).toBe(true);
    expect(within(verdict).getByRole("button", { name: "Mark done" })).toHaveClass("ml-auto");
  });

  it("has no legal disclaimer under a passport's expiry", () => {
    const passport = makeItem({ kind: "expiry", title: "Passport expires", action: "Renew the passport before it expires.", due_date: "2027-02-10", computation: makeReceipt({ rule_ids: ["date_as_written"] }) });
    const verdict = renderVerdict(makeDetail({ items: [passport] }));
    expect(within(verdict).queryByText(/Not legal advice/)).toBeNull();
  });

  it("says so when 'Add to calendar' downloads the file", async () => {
    const spy = vi.spyOn(ToastModule.toast, "success");
    const verdict = renderVerdict(makeDetail({ items: [makeItem({ due_date: "2026-10-21" }) as Item] }));
    const link = within(verdict).getByRole("link", { name: "Add to calendar" });
    link.addEventListener("click", (e) => e.preventDefault()); // jsdom can't download
    await userEvent.click(link);
    expect(spy).toHaveBeenCalledWith("Calendar file downloaded", expect.objectContaining({ description: expect.stringMatching(/calendar/) }));
  });
});

describe("a price increase that asks for consent (walkthrough of phase 2)", () => {
  it("is a choice by a date, not a to-do: 'Decide by', and what happens if you don't agree", () => {
    const consent = makeItem({
      id: "itm_consent",
      kind: "deadline",
      title: "Give consent to the fee increase (Zustimmung erteilen)",
      action: "Consent to the new price online under “Postfach › Zustimmungen” or return the signed form.",
      consequence: "Without your consent, the bank may end the account with two months' notice.",
      due_date: "2026-11-30",
      date_spec: { type: "fixed", date: "2026-11-30", time: null, anchor: "explicit_date", anchor_date: "2026-11-30", amount: null, unit: null, delivery_rule: "none", shift_rule: "auto", nature: "declaration", legal_basis: null, text: "bis zum 30.11.2026" },
    });
    renderVerdict(makeDetail({ document: makeDoc({ kind: "price_increase", title: "Musterbank – new account fee" }), items: [consent] }));
    const verdict = screen.getByRole("article", { name: "Musterbank – new account fee" });
    expect(verdict).toHaveTextContent("Your choice: agree to the new price — or don't.");
    expect(verdict).toHaveTextContent(/If you agree:/);
    expect(within(verdict).getByText("Decide by")).toBeInTheDocument();
    expect(within(verdict).queryByText("By when")).toBeNull();
    expect(verdict).toHaveTextContent(/If you don't agree/);
  });
});
