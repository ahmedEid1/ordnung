/**
 * A letter with signs of a scam, on its page: its dates stay in view while it is flagged (no countdown, no Pay),
 * "If you pay" only where it asks for money, and once the person checked it ("I checked — it's genuine": the
 * server sets nothing aside any more) the verdict leads with its deadline again.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail, Item, Suggestion } from "@/api/types";
import { plainText } from "@/lib/glue";
import { ItemsList } from "./ItemsList";
import { VerdictCard } from "./VerdictCard";
import { selectPrimaryItem } from "./verdict";
import { makeDetail, makeDoc, makeItem, makeSuggestion } from "./fixtures";

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
afterEach(() => vi.unstubAllGlobals());

// the tests' today is Mon 28 Sep 2026
const objection = makeItem({ id: "itm_obj", kind: "deadline", title: "Object in writing if the assessment is wrong", due_date: "2026-10-19", send_by: "2026-10-15", priority: "high" });
const payment = makeItem({ id: "itm_pay", kind: "payment", direction: "out", title: "Pay the income tax", amount: 412, due_date: "2026-10-12", send_by: "2026-10-09" });
const warning = (status: Suggestion["status"]) =>
  makeSuggestion({
    id: "sug_scam",
    kind: "scam",
    status,
    title: "Possible scam: check this letter before you act",
    refs: [{ type: "document", id: "doc_1" }],
    action: { type: "open", draft_kind: null, target_type: "document", target_id: "doc_1", label: "See why" },
  });
const genuine = makeDoc({ id: "doc_1", kind: "tax_assessment", title: "Income tax assessment 2025", area: "tax" });

function renderVerdict(detail: DocumentDetail) {
  renderWithProviders(<VerdictCard detail={detail} primary={selectPrimaryItem(detail.items, detail.set_aside)} />, { client: client() });
  return screen.getByRole("article");
}

describe("the verdict once the person checked the letter", () => {
  it("leads with the deadline again: the warning dismissed and nothing set aside", () => {
    const verdict = renderVerdict(makeDetail({ document: genuine, items: [objection], suggestions: [warning("dismissed")], set_aside: [] }));
    expect(within(verdict).queryByText("Possible scam")).toBeNull();
    expect(within(verdict).queryByText(/Nothing right now/)).toBeNull();
    expect(within(verdict).getByText("Object in writing if the assessment is wrong")).toBeInTheDocument();
    // the date box: the send-by day and the due date
    expect(within(verdict).getByRole("heading", { level: 2, name: "By when" })).toBeInTheDocument();
    expect(verdict.querySelector("time[datetime='2026-10-19']")).not.toBeNull();
  });
});

describe("“If you pay” on a flagged letter", () => {
  it("is there only when the letter asks for money, in a sentence true for every sign", () => {
    const pays = renderVerdict(makeDetail({ document: genuine, items: [objection, payment], suggestions: [warning("new")] }));
    const section = within(pays).getByRole("heading", { level: 2, name: "If you pay" }).parentElement!;
    expect(section).toHaveTextContent("If this letter isn't from who it claims, money you send is hard to get back.");
    // the reason may be any sign (hidden text, a warning in the reading), not always another account
    expect(pays).not.toHaveTextContent(/account this sender has never used/);
  });

  it("is left out on a letter that asks for no money (only a deadline)", () => {
    const deadlineOnly = renderVerdict(makeDetail({ document: genuine, items: [objection], suggestions: [warning("new")] }));
    expect(within(deadlineOnly).getByText("Possible scam")).toBeInTheDocument();
    expect(within(deadlineOnly).queryByRole("heading", { name: "If you pay" })).toBeNull();
  });

  it("is left out when the letter's payment is already done", () => {
    const paid = renderVerdict(makeDetail({ document: genuine, items: [objection, { ...payment, status: "done" }], suggestions: [warning("new")] }));
    expect(within(paid).queryByRole("heading", { name: "If you pay" })).toBeNull();
  });
});

describe("a flagged letter's to-dos keep their dates", () => {
  const row = (todos: HTMLElement, title: string) => within(todos).getByText(title).closest("li")!;

  it("shows each demand's date quietly — no countdown, no Pay, nothing to tick off", () => {
    renderWithProviders(<ItemsList items={[objection, payment]} docId="doc_1" scam />, { client: client() });
    const todos = screen.getByRole("region", { name: "To-dos & dates" });
    for (const [item, iso] of [
      [objection, "2026-10-19"],
      [payment, "2026-10-12"],
    ] as [Item, string][]) {
      const li = row(todos, item.title);
      expect(li.querySelector(`time[datetime='${iso}']`), item.title).not.toBeNull();
      expect(li).toHaveTextContent(/due \d+ Oct\b/);
      expect(li).not.toHaveTextContent(/was due|in \d+ days|overdue|transfer by|post by/);
    }
    expect(within(todos).queryByRole("button", { name: /as done|^Pay/ })).toBeNull();
  });

  it("never says a date still ahead “was due”: the server set it aside, the warning is gone", () => {
    // the warning dismissed, but the to-dos still set aside as from a scam letter (a server before the check counted)
    const asides = [
      { item_id: objection.id, reason: "suspicious" as const, replaced_by: null },
      { item_id: payment.id, reason: "suspicious" as const, replaced_by: null },
    ];
    renderWithProviders(<ItemsList items={[objection, payment]} docId="doc_1" setAside={asides} />, { client: client() });
    const todos = screen.getByRole("region", { name: /^To-dos & dates/ });
    const li = row(todos, objection.title);
    expect(plainText(li.textContent ?? "")).toMatch(/due 19 Oct/);
    expect(li).not.toHaveTextContent(/was due/);
    expect(row(todos, payment.title)).not.toHaveTextContent(/was due/);
  });

  it("still says “was due” for a date that has passed", () => {
    const old = makeItem({ id: "itm_old", kind: "payment", direction: "out", title: "Deposit", amount: 900, due_date: "2025-10-01", filed_on: "2026-09-20" });
    renderWithProviders(<ItemsList items={[old]} docId="doc_1" setAside={[{ item_id: old.id, reason: "history", replaced_by: null }]} />, { client: client() });
    expect(row(screen.getByRole("region", { name: /^To-dos & dates/ }), "Deposit")).toHaveTextContent(/was due 1 Oct 2025/);
  });
});

describe("a letter titled by its file name", () => {
  it("keeps a reference whole in the headline, as everywhere else a file name is a title", () => {
    const unread = makeDoc({ id: "doc_2", title: null, filename: "Scan_FN-5521904-2026.pdf", ai_private: true, ai_processed_at: null });
    renderVerdict(makeDetail({ document: unread }));
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Scan_FN‑5521904‑2026.pdf");
    expect(h1.querySelectorAll("wbr")).toHaveLength(1);
  });
});
