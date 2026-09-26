import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { ADVICE_BY_KIND } from "@/mocks/data/advice";
import { DocumentWarnings } from "./Warnings";
import { ItemsList } from "./ItemsList";
import { LetterAdviceCard } from "./LetterAdvice";
import { chooseMainAction } from "./verdict";
import { VerdictCard } from "./VerdictCard";
import { makeDetail, makeDoc, makeItem, makeReceipt } from "./fixtures";

async function detailFromMock(id: string): Promise<DocumentDetail> {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  srv.openAllMail();
  const res = await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined);
  return (await res.json()) as DocumentDetail;
}

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const courtDoc = makeDoc({ id: "doc_court", kind: "court_payment_order", area: "money", title: "Mahnbescheid", received_date: null, doc_date: "2026-09-22" });

describe("the advice card of a high-stakes letter", () => {
  it("shows an urgent court order's steps, facts and free help — links open in a new tab", () => {
    const { container } = renderWithProviders(<LetterAdviceCard advice={ADVICE_BY_KIND.court_payment_order} doc={courtDoc} />, { client: client() });
    const card = screen.getByRole("region", { name: /Court payment order \(Mahnbescheid\)/ });
    expect(within(card).getByText("Act now — and get advice")).toBeInTheDocument();
    expect(within(card).getAllByRole("listitem").length).toBeGreaterThan(4);
    expect(within(card).getByText("Old claims may be time-barred")).toBeInTheDocument();
    const help = within(card).getByRole("link", { name: /Rechtsantragstelle at any Amtsgericht.*opens in a new tab/ });
    expect(help).toHaveAttribute("target", "_blank");
    expect(help).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(card).getByText(/Not legal advice/)).toBeInTheDocument();
    // the verdict's main button drafts the objection; the card doesn't repeat it
    expect(within(card).queryByRole("button")).toBeNull();
    assertNoRawEnumsInElement(container);
  });

  it("offers the receipts letter on an operating-cost statement", async () => {
    const detail = await detailFromMock("doc_nebenkosten");
    expect(detail.advice?.kind).toBe("operating_costs");
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    const card = screen.getByRole("region", { name: /Operating-cost statement/ });
    expect(within(card).getByText("Know your rights")).toBeInTheDocument();
    expect(within(card).getByText("On time")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Ask to see the receipts" })).toBeInTheDocument();
  });

  it("puts an urgent card first and asks for the delivery date of a court order", () => {
    const item = makeItem({
      id: "itm_rule",
      title: "Object to the court payment order — if you don't owe it",
      origin: "rule",
      grounding: "model_read",
      due_date: "2026-10-06",
      date_spec: { type: "relative", anchor: "receipt", amount: 2, unit: "weeks", nature: "objection", text: "", anchor_date: null, date: null, time: null, legal_basis: "§ 692 ZPO", delivery_rule: "none", shift_rule: "auto" },
      computation: makeReceipt({ rule_ids: ["zpo_692", "fallback_receipt"] }),
    });
    const detail = makeDetail({ document: courtDoc, items: [item], advice: ADVICE_BY_KIND.court_payment_order });
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    const section = screen.getByRole("region", { name: "Warnings and things to check" });
    const first = section.firstElementChild as HTMLElement;
    expect(within(first).getByText(/Court payment order \(Mahnbescheid\)/)).toBeInTheDocument();
    expect(screen.getByText("When was it delivered?")).toBeInTheDocument();
    expect(screen.getByText(/yellow envelope \(/)).toBeInTheDocument();
    expect(screen.getByLabelText("Delivery date")).toBeInTheDocument();
  });

  it("replaces the generic court-action card with the letter's own", () => {
    const doc = makeDoc({ kind: "dismissal", area: "work", remedy: { type: "klage", addressee: "Arbeitsgericht", period_text: null, form_text: null, quote: null } });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, advice: ADVICE_BY_KIND.dismissal })} />, { client: client() });
    expect(screen.queryByText(/only be challenged in court — get advice/)).toBeNull();
    expect(screen.getByRole("region", { name: ADVICE_BY_KIND.dismissal.title })).toBeInTheDocument();
  });

  it("drafts the objection from the verdict against a court order even without instructions", () => {
    const main = chooseMainAction(makeDetail({ document: courtDoc }), null);
    expect(main).toMatchObject({ type: "draft", draftKind: "objection" });
  });

  it("never tells the person a court order needs nothing — pay or object", () => {
    const item = makeItem({
      title: "Pay or object to the court payment order (Mahnbescheid)",
      action: "If you don't owe the money, object (Widerspruch). If you owe it, pay the claimant.",
      consequence: "After two weeks the claimant can ask for an enforcement order.",
      origin: "rule",
      due_date: "2026-10-06",
      date_spec: { type: "relative", anchor: "receipt", amount: 2, unit: "weeks", nature: "objection", text: "", anchor_date: null, date: null, time: null, legal_basis: "§ 692 ZPO", delivery_rule: "none", shift_rule: "auto" },
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: courtDoc, items: [item] })} primary={item} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Nothing to do/)).toBeNull();
    expect(screen.getByText("By when")).toBeInTheDocument();
    expect(screen.getByText("If you ignore it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Draft objection" })).toBeInTheDocument();
  });

  it("marks to-dos the law adds as set by law", () => {
    const item = makeItem({ origin: "rule", grounding: "model_read", title: "Register as a job seeker", due_date: "2026-10-01" });
    renderWithProviders(<ItemsList items={[item]} docId="doc_1" />, { client: client() });
    expect(screen.getByText("Set by law")).toBeInTheDocument();
  });
});
