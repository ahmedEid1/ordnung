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
import { ThreadSection } from "./Related";
import { LetterAdviceCard, keepCitations } from "./LetterAdvice";
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
    const help = within(card).getByRole("link", { name: /Rechtsantragstelle at the Amtsgericht.*opens in a new tab/ });
    // another court's desk only counts once its record reaches the issuing court (§ 129a Abs. 3 S. 2 ZPO)
    expect(within(card).getByText(/§ 129a Abs\. 3 S\. 2 ZPO/)).toBeInTheDocument();
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
    // the date is on the envelope — the person never sees the Zustellungsurkunde itself
    expect(screen.getByText(/the postman wrote that date on the yellow envelope/)).toBeInTheDocument();
    expect(screen.queryByText(/Zustellungsurkunde/)).toBeNull();
    // the envelope date is often days before the letter was opened: nothing is filled in, no "Today"
    const input = screen.getByLabelText("Date on the yellow envelope") as HTMLInputElement;
    expect(input.value).toBe("");
    // an empty field isn't an error (WCAG 3.3.1): Save waits for a date instead
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("asks a court letter filed as another kind for its envelope date, never 'Today'", () => {
    // a Versäumnisurteil's Einspruch counts from delivery (its receipt cites § 180 ZPO)
    const doc = makeDoc({ id: "doc_vu", kind: "authority_letter", area: "money", title: "Versäumnisurteil", received_date: null, doc_date: "2026-09-22" });
    const item = makeItem({
      id: "itm_vu",
      title: "Object to the default judgment (Einspruch)",
      due_date: "2026-10-06",
      date_spec: { type: "relative", anchor: "receipt", amount: 2, unit: "weeks", nature: "objection", text: "", anchor_date: null, date: null, time: null, legal_basis: "§ 339 ZPO", delivery_rule: "none", shift_rule: "auto" },
      computation: makeReceipt({ rule_ids: ["zpo_339", "zpo_180", "receipt_fallback"] }),
    });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [item] })} />, { client: client() });
    expect(screen.getByText("When was it delivered?")).toBeInTheDocument();
    expect((screen.getByLabelText("Date on the yellow envelope") as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
  });

  it("never files a landlord's notice without a to-do as 'nothing to do'", () => {
    // a notice without notice period, or one whose end we couldn't read, has no objection to-do
    const doc = makeDoc({ id: "doc_notice", kind: "landlord_notice", area: "home", title: "Fristlose Kündigung" });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: doc, items: [] })} primary={null} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Nothing right now/)).toBeNull();
    expect(screen.getByText(/Get advice now: your landlord is ending your tenancy/)).toBeInTheDocument();
  });

  it("says to check a late statement's back-payment before paying, and doesn't lead with Pay", () => {
    const doc = makeDoc({ id: "doc_statement", kind: "utility_bill", area: "home", title: "Operating-cost statement 2024" });
    const pay = makeItem({
      kind: "payment",
      title: "Pay the back-payment",
      amount: 120,
      due_date: "2026-09-30",
      computation: makeReceipt({ rule_ids: ["date_as_written", "bgb_556_3"] }),
    });
    const detail = makeDetail({ document: doc, items: [pay] });
    renderWithProviders(<VerdictCard detail={detail} primary={pay} onAskArrival={() => {}} />, { client: client() });
    expect(screen.getByText(/Check before you pay: this statement seems to have come too late/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay/ })).toBeNull();
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

  it("never gives a dismissal the calm 'nothing to do' verdict, and lists the other deadline the law sets", () => {
    const doc = makeDoc({ id: "doc_dismissal", kind: "dismissal", area: "work", title: "Dismissal", received_date: "2026-09-25" });
    const spec = { type: "relative", anchor: "receipt", unit: "weeks", text: "", anchor_date: null, date: null, time: null, delivery_rule: "none", shift_rule: "auto" } as const;
    const court = makeItem({
      id: "itm_court",
      title: "Get advice now: court action against the dismissal (Kündigungsschutzklage)",
      action: "If you think the dismissal is wrong, talk to your union, an employment lawyer or the labour court's Rechtsantragstelle today.",
      origin: "rule",
      priority: "critical",
      due_date: "2026-10-16",
      date_spec: { ...spec, amount: 3, nature: "objection", legal_basis: "§ 4 S. 1 KSchG" },
    });
    const register = makeItem({
      id: "itm_register",
      title: "Register as job-seeking (arbeitsuchend) at the Agentur für Arbeit",
      origin: "rule",
      priority: "high",
      due_date: "2026-12-31",
      date_spec: { ...spec, amount: 3, unit: "days", nature: "declaration", legal_basis: "§ 38 Abs. 1 SGB III" },
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: doc, items: [court, register] })} primary={court} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Nothing to do/)).toBeNull();
    expect(screen.queryByText("Only if you disagree")).toBeNull();
    expect(screen.getByText("By when")).toBeInTheDocument();
    const also = screen.getByRole("list", { name: "Also due by law" });
    expect(within(also).getByText(/Register as job-seeking/)).toBeInTheDocument();
  });

  it("lets the person say what kind of letter it is", async () => {
    const detail = await detailFromMock("doc_parking");
    const user = (await import("@testing-library/user-event")).default.setup();
    const patched: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") patched.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify(detail.document), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    renderWithProviders(<VerdictCard detail={detail} primary={detail.items[0] ?? null} onAskArrival={() => {}} />, { client: client() });
    await user.click(screen.getByRole("button", { name: "Change what kind of letter this is" }));
    const dialog = await screen.findByRole("dialog", { name: "What kind of letter is this?" });
    const select = within(dialog).getByLabelText("Kind of letter");
    expect(within(select).getByRole("group", { name: "Letters with deadlines set by law" })).toBeInTheDocument();
    await user.selectOptions(select, "court_payment_order");
    expect(within(dialog).getByText(/Mahnbescheid: two weeks to pay or object/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(patched).toEqual([{ kind: "court_payment_order" }]));
  });

  it("the static demo has a Mahnbescheid and a dismissal with their cards and the deadlines the law sets", async () => {
    const order = await detailFromMock("doc_mahnbescheid");
    expect(order.document.kind).toBe("court_payment_order");
    expect(order.advice?.urgent).toBe(true);
    const [objection] = order.items;
    expect(objection?.computation?.rule_ids).toContain("zpo_692");
    expect(objection?.computation?.confidence).toBe("low");
    const dismissal = await detailFromMock("doc_dismissal");
    expect(dismissal.advice?.kind).toBe("dismissal");
    expect(dismissal.items.map((i) => [i.slot_key, i.origin, i.due_date])).toEqual([
      ["rule:kschg_4", "rule", "2026-10-19"],
      ["rule:sgb3_38", "rule", "2026-10-01"],
    ]);
    // the envelope date recomputes the court deadline with the real rules' receipt
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    srv.openAllMail();
    await srv.handle("PATCH", "/documents/doc_mahnbescheid", new URLSearchParams(), { received_date: "2026-09-25" });
    const after = (await (await srv.handle("GET", "/documents/doc_mahnbescheid", new URLSearchParams(), undefined)).json()) as DocumentDetail;
    expect(after.items[0]?.due_date).toBe("2026-10-09");
    expect(after.items[0]?.computation?.confidence).toBe("medium");
  });

  it("asks for a court order's delivery date once — the reading's own 'when was it delivered' warning is not repeated", async () => {
    const detail = await detailFromMock("doc_mahnbescheid");
    expect(detail.document.warnings.join(" ")).toMatch(/when the letter was delivered/);
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    expect(screen.getByText("When was it delivered?")).toBeInTheDocument();
    expect(screen.queryByText("Please check")).toBeNull();
    expect(screen.queryByText(/We don't know yet when the letter was delivered/)).toBeNull();
  });

  it("offers only the letter the backend says fits — no hardship objection to a notice without notice period", () => {
    const notice = makeDoc({ id: "doc_notice", kind: "landlord_notice", area: "home", title: "Kündigung" });
    const { unmount } = renderWithProviders(<LetterAdviceCard advice={ADVICE_BY_KIND.landlord_notice} doc={notice} />, { client: client() });
    expect(ADVICE_BY_KIND.landlord_notice.draft).toBe("objection");
    expect(screen.getByRole("button", { name: "Draft a hardship objection" })).toBeInTheDocument();
    unmount();
    const fristlos = {
      ...ADVICE_BY_KIND.landlord_notice,
      draft: null,
      facts: [{ title: "This reads as a notice without notice period (fristlos)", text: "The hardship objection doesn't apply to it.", tone: "warn" as const, citation: "§ 574 Abs. 1 S. 2 BGB" }],
    };
    renderWithProviders(<LetterAdviceCard advice={fristlos} doc={notice} />, { client: client() });
    expect(screen.getByText("This reads as a notice without notice period (fristlos)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /hardship objection/ })).toBeNull();
  });

  it("never calls a landlord's notice 'nothing to do if the decision is right'", () => {
    const doc = makeDoc({ id: "doc_notice", kind: "landlord_notice", area: "home", title: "Kündigung Ihrer Wohnung", received_date: "2026-09-25" });
    const item = makeItem({
      title: "Decide whether to object to the notice (Widerspruch)",
      action: "Your tenancy ends on Wed 31 Mar 2027. Have the notice checked by a tenants' association (form, reason, period).",
      consequence: "After this day the landlord may refuse to continue the tenancy.",
      origin: "rule",
      due_date: "2027-01-29",
      date_spec: { type: "relative", anchor: "explicit_date", amount: -2, unit: "months", nature: "objection", text: "", anchor_date: "2027-03-31", date: null, time: null, legal_basis: "§ 574b Abs. 2 BGB", delivery_rule: "none", shift_rule: "auto" },
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: doc, items: [item] })} primary={item} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Nothing to do/)).toBeNull();
    expect(screen.queryByText("Only if you disagree")).toBeNull();
    expect(screen.getByText(/Your tenancy ends on Wed 31 Mar 2027/)).toBeInTheDocument();
    expect(screen.getByText("By when")).toBeInTheDocument();
    expect(screen.getByText("If you ignore it")).toBeInTheDocument();
  });

  it("asks when a court order was delivered, not when it arrived", () => {
    const item = makeItem({
      title: "Pay or object to the court payment order (Mahnbescheid)",
      origin: "rule",
      due_date: "2026-10-06",
      date_spec: { type: "relative", anchor: "receipt", amount: 2, unit: "weeks", nature: "objection", text: "", anchor_date: null, date: null, time: null, legal_basis: "§ 692 ZPO", delivery_rule: "none", shift_rule: "auto" },
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: courtDoc, items: [item] })} primary={item} onAskArrival={() => {}} />, { client: client() });
    expect(screen.getByRole("button", { name: "Tell us when it was delivered" })).toBeInTheDocument();
  });

  it("the static demo's cards stop asking for an arrival day the person entered", async () => {
    const dismissal = await detailFromMock("doc_dismissal");
    expect(dismissal.document.received_date).toBe("2026-09-28");
    expect(dismissal.advice?.steps[0]).toMatch(/which you entered/);
    const order = await detailFromMock("doc_mahnbescheid");
    expect(order.advice?.steps[0]).toMatch(/^Find the delivery date/);
  });

  it("static demo: choosing another kind drops the letter's own card and the deadlines the law added, and brings them back", async () => {
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    srv.openAllMail();
    const get = async (id: string) => (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
    await srv.handle("PATCH", "/documents/doc_nebenkosten", new URLSearchParams(), { kind: "other" });
    expect((await get("doc_nebenkosten")).advice).toBeNull();
    await srv.handle("PATCH", "/documents/doc_dismissal", new URLSearchParams(), { kind: "employment" });
    const refiled = await get("doc_dismissal");
    expect(refiled.advice).toBeNull();
    expect(refiled.items.filter((i) => i.origin === "rule")).toEqual([]);
    await srv.handle("PATCH", "/documents/doc_dismissal", new URLSearchParams(), { kind: "dismissal" });
    const back = await get("doc_dismissal");
    expect(back.advice?.kind).toBe("dismissal");
    expect(back.items.map((i) => i.slot_key)).toEqual(["rule:kschg_4", "rule:sgb3_38"]);
  });

  it("keeps the 'This letter' badge outside a long, truncated title in the thread", async () => {
    const detail = await detailFromMock("doc_dismissal");
    expect(detail.related.length).toBeGreaterThan(0);
    renderWithProviders(<ThreadSection detail={detail} />, { client: client() });
    const badge = screen.getByText("This letter");
    expect(badge.closest(".truncate")).toBeNull();
    expect(badge).toHaveClass("shrink-0");
    expect(screen.getByText(detail.document.title!)).toHaveClass("truncate");
  });

  it("never breaks a citation after its § sign", () => {
    expect(keepCitations("(§ 38 Abs. 1 S. 4 SGB III, § 111 Abs. 2 ArbGG, Art. 15 GDPR)")).toBe(
      "(§\u00a038 Abs.\u00a01 S.\u00a04 SGB III, §\u00a0111 Abs.\u00a02 ArbGG, Art.\u00a015 GDPR)",
    );
    renderWithProviders(<LetterAdviceCard advice={ADVICE_BY_KIND.dismissal} doc={makeDoc({ kind: "dismissal" })} />, { client: client() });
    expect(screen.getByText(/Apprentices:/).textContent).toContain("§\u00a038 Abs.\u00a01 S.\u00a04 SGB III");
  });

  it("settles a court order once the person has dealt with every to-do", () => {
    // objected and marked "Pay or object" done: filed — no "get advice now", no objection to draft
    const done = makeItem({ title: "Pay or object to the court payment order (Mahnbescheid)", origin: "rule", status: "done", due_date: "2026-10-06" });
    const detail = makeDetail({ document: courtDoc, items: [done], advice: { ...ADVICE_BY_KIND.court_payment_order, urgent: false, handled: true } });
    renderWithProviders(<VerdictCard detail={detail} primary={null} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Get advice now/)).toBeNull();
    expect(screen.getByText(/Nothing right now — it's filed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draft objection" })).toBeNull();
    expect(chooseMainAction(detail, null).type).toBe("none");
  });

  it("never files a notice without notice period away because the arrears it demands were paid", () => {
    // final review 2: the server decides — the paid arrears carry no deadline of the notice, so it isn't handled
    const doc = makeDoc({ id: "doc_notice", kind: "landlord_notice", area: "home", title: "Fristlose Kündigung" });
    const arrears = makeItem({ kind: "payment", title: "Pay the rent arrears", amount: 1920, status: "done", due_date: "2026-10-10" });
    const advice = { ...ADVICE_BY_KIND.landlord_notice, urgent: true, handled: false, draft: null };
    const detail = makeDetail({ document: doc, items: [arrears], advice });
    renderWithProviders(<VerdictCard detail={detail} primary={null} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Nothing right now/)).toBeNull();
    expect(screen.getByText(/Get advice now: your landlord is ending your tenancy/)).toBeInTheDocument();
  });

  it("static demo: a settled court order stops asking for its envelope date and repeating the arrival warning", async () => {
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    srv.openAllMail();
    const get = async () => (await (await srv.handle("GET", "/documents/doc_mahnbescheid", new URLSearchParams(), undefined)).json()) as DocumentDetail;
    const before = await get();
    expect(before.advice?.handled).toBe(false);
    for (const item of before.items) await srv.handle("PATCH", `/items/${item.id}`, new URLSearchParams(), { status: "done" });
    const settled = await get();
    expect(settled.advice).toMatchObject({ urgent: false, handled: true });
    expect(settled.advice?.steps.some((step) => step.startsWith("Find the delivery date"))).toBe(false);
    renderWithProviders(<DocumentWarnings detail={settled} />, { client: client() });
    expect(screen.queryByText("When was it delivered?")).toBeNull();
    expect(screen.queryByText("Please check")).toBeNull();
    expect(screen.queryByText(/We don't know yet when the letter was delivered/)).toBeNull();
  });

  it("says a rent increase's new rent is only owed once the person agrees, and doesn't lead with Pay", () => {
    const doc = makeDoc({ id: "doc_increase", kind: "rent_increase", area: "home", title: "Rent increase request" });
    const rent = makeItem({
      kind: "payment",
      title: "New monthly rent",
      amount: 670,
      due_date: "2026-12-01",
      recurrence: { interval: 1, unit: "months" },
      computation: makeReceipt({ rule_ids: ["date_as_written", "bgb_558b"] }),
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ document: doc, items: [rent], advice: ADVICE_BY_KIND.rent_increase })} primary={rent} onAskArrival={() => {}} />, {
      client: client(),
    });
    expect(screen.getByText(/Decide before you pay: the higher rent is only owed once you agree/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay/ })).toBeNull();
  });

  it("stops saying 'decide before you pay' once the person closed the consent decision", () => {
    // final review 2: agreed and marked "Decide whether to agree" done — the new rent is what they pay now
    const doc = makeDoc({ id: "doc_increase", kind: "rent_increase", area: "home", title: "Rent increase request" });
    const rent = makeItem({
      id: "rent",
      kind: "payment",
      title: "New monthly rent",
      amount: 670,
      due_date: "2026-12-01",
      recurrence: { interval: 1, unit: "months" },
      computation: makeReceipt({ rule_ids: ["date_as_written", "bgb_558b"] }),
    });
    const decided = makeItem({ id: "consent", origin: "rule", status: "done", title: "Decide whether to agree to the rent increase", computation: makeReceipt({ rule_ids: ["bgb_558b"] }) });
    const detail = makeDetail({ document: doc, items: [rent, decided], advice: ADVICE_BY_KIND.rent_increase });
    renderWithProviders(<VerdictCard detail={detail} primary={rent} onAskArrival={() => {}} />, { client: client() });
    expect(screen.queryByText(/Decide before you pay/)).toBeNull();
    expect(chooseMainAction(detail, rent).type).toBe("pay");
  });

  it("marks to-dos the law adds as set by law", () => {
    const item = makeItem({ origin: "rule", grounding: "model_read", title: "Register as a job seeker", due_date: "2026-10-01" });
    renderWithProviders(<ItemsList items={[item]} docId="doc_1" />, { client: client() });
    expect(screen.getByText("Set by law")).toBeInTheDocument();
  });
});
