import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import { DocumentWarnings } from "./Warnings";
import { makeDetail, makeDoc, makeItem, makeReceipt, makeSuggestion } from "./fixtures";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => vi.unstubAllGlobals());

const WARNING = "Claude's reading of this letter left out a date the letter sets for you. Ordnung added it as a to-do from the letter's own words — please check it against the letter.";

describe("round-5 limits review (RL-T6 web mutants)", () => {
  it("asks a court order for the court's letter's envelope date", () => {
    const doc = makeDoc({ id: "doc_c", kind: "court_payment_order", area: "money", title: "Mahnbescheid", received_date: null, doc_date: "2026-09-22" });
    const spec = { type: "relative" as const, anchor: "receipt" as const, amount: 2, unit: "weeks" as const, nature: "objection" as const, text: "", anchor_date: null, date: null, time: null, legal_basis: null, delivery_rule: "none" as const, shift_rule: "auto" as const };
    const item = makeItem({ id: "itm_c", due_date: "2026-10-06", date_spec: spec, computation: makeReceipt({ rule_ids: ["zpo_180"] }) });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [item] })} />, { client: client() });
    expect(screen.getByText(/the court's letter was delivered/)).toBeInTheDocument();
  });

  it("knows a dropped date's to-do by its slot's prefix and keeps its warning", () => {
    const doc = makeDoc({ id: "doc_dl", kind: "invoice", area: "money", title: "Rechnung", warnings: [WARNING], doc_date: "2026-10-01" });
    const item = makeItem({
      id: "itm_dl2",
      slot_key: "check:deadline#2026-10-15-payment",
      kind: "payment",
      title: "Payment the letter asks for",
      due_date: "2026-10-15",
      evidence: [{ doc_id: "doc_dl", quote: "Bitte überweisen Sie den Betrag bis zum 15.10.2026.", grounding: "verified", value_consistent: false, score: 100, page: 1, boxes: [] }],
    });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [item] })} />, { client: client() });
    expect(screen.getByText(/Ordnung took this date from the letter's own words/)).toBeInTheDocument();
    expect(screen.getByText(WARNING)).toBeInTheDocument();
  });

  it("never lists the dropped-date warning as a scam sign", () => {
    const signs = [WARNING, "Possible scam: the IBAN differs from the one this sender used before."];
    const doc = makeDoc({ id: "doc_s", kind: "invoice", area: "money", title: "Rechnung", warnings: signs, doc_date: "2026-10-01" });
    const scam = makeSuggestion({ kind: "scam", refs: [{ type: "document", id: "doc_s" }] });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [], suggestions: [scam], scam_signs: signs })} />, { client: client() });
    expect(screen.getByText(/Possible scam: the IBAN differs/)).toBeInTheDocument();
    expect(screen.queryByText(WARNING)).toBeNull();
  });
});
