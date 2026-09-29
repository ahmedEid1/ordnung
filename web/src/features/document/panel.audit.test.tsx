/**
 * UI audit round 1, the letter page's panel: key facts, to-dos, thread / contract / drafts, Ideas
 * and "Explained simply" — what was cut, overflowed, misleading or repeated.
 */
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { Contract, DocumentDetail, Draft, Evidence, Item } from "@/api/types";
import { KeyFacts } from "./KeyFacts";
import { ItemsList } from "./ItemsList";
import { ContractsSection, DraftsSection, IdeasSection, ThreadSection } from "./Related";
import { ExplainedSimply } from "./Explained";
import { ideasForLetter, onThisLetter } from "./letter-ideas";
import { paysOnSite } from "./item-meta";
import { makeDetail, makeDoc, makeItem, makeSuggestion } from "./fixtures";
import { plainText } from "@/lib/glue";

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

const ev = (grounding: Evidence["grounding"], page = 1): Evidence => ({
  doc_id: "doc_1",
  page,
  quote: "…",
  grounding,
  value_consistent: true,
  score: 1,
  boxes: [],
});

describe("Key facts", () => {
  it("never cuts a reference, a payee or an IBAN, and breaks an IBAN only between its groups", () => {
    const doc = makeDoc({
      references: [
        { label: "Aktenzeichen", value: "32.4-VW-2026-0184512" },
        { label: "Kassenzeichen", value: "5126 0184 5122" },
      ],
      payment: { iban: "DE51123456000000100017", payee: "UAB RBS Zahlungszentrale / Beitragsservice Abteilung Forderungen", iban_valid: true, reference: "Kassenzeichen 5126 0184 5122" },
    });
    const { container } = renderWithProviders(<KeyFacts doc={doc} scam={false} />, { client: client() });
    expect(container.querySelector(".truncate")).toBeNull();
    const facts = screen.getByRole("region", { name: "Key facts" });
    expect(within(facts).getByText("UAB RBS Zahlungszentrale / Beitragsservice Abteilung Forderungen")).toHaveClass("[overflow-wrap:anywhere]");
    // "DE51 1234 5600 0000 1000 17": six groups that never split
    const groups = [...container.querySelectorAll("dd .whitespace-nowrap")].map((g) => g.textContent);
    expect(groups).toEqual(["DE51", "1234", "5600", "0000", "1000", "17"]);
    // label above the value on phones, beside it from sm, same columns as the facts
    const row = within(facts).getByText("5126 0184 5122").closest("div.grid")!;
    expect(row.className).toContain("sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]");
    expect(within(facts).getByRole("button", { name: "Copy Payment reference" })).toBeInTheDocument();
    expect(within(facts).getByText("Reference numbers — quote them when you reply")).toBeInTheDocument();
  });

  it("lists a number once: a reference already shown as a key fact gives the fact its copy button", () => {
    const doc = makeDoc({
      key_facts: [{ label: "Versicherten-Nr.", value: "R482019375", evidence: ev("verified") }],
      references: [
        { label: "Versicherten-Nr.", value: "R482019375" },
        { label: "Unser Zeichen", value: "BZ-S/2026/0917" },
      ],
    });
    renderWithProviders(<KeyFacts doc={doc} scam={false} />, { client: client() });
    expect(screen.getAllByText("R482019375")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Copy Insurance number" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy Their reference" })).toBeInTheDocument();
  });

  it("says 'Numbers in this letter' on a scam letter and 'Numbers on this document' on a passport", () => {
    const refs = [{ label: "Vorgang", value: "BS-2026-99812" }];
    const { unmount } = renderWithProviders(<KeyFacts doc={makeDoc({ references: refs })} scam />, { client: client() });
    expect(screen.getByText("Numbers in this letter")).toBeInTheDocument();
    expect(screen.queryByText(/quote them when you reply/)).toBeNull();
    unmount();
    renderWithProviders(<KeyFacts doc={makeDoc({ kind: "identity_document", references: refs })} scam={false} />, { client: client() });
    expect(screen.getByText("Numbers on this document")).toBeInTheDocument();
  });

  it("offers nothing to copy from a scam letter's bank details", () => {
    const doc = makeDoc({ payment: { iban: "LT717300010123456789", payee: "BS Inkasso Service", iban_valid: true, reference: "BS-2026-99812" } });
    renderWithProviders(<KeyFacts doc={doc} scam />, { client: client() });
    expect(screen.getByText(/don't pay to this account/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Copy/ })).toBeNull();
  });

  it("reads labels in English with the letter's German, and values in the app's format", () => {
    const doc = makeDoc({
      key_facts: [
        { label: "Gültig ab", value: "01.01.2026", evidence: ev("verified") },
        { label: "Voraussichtlicher Jahresverbrauch", value: "1.320 kWh", evidence: ev("verified") },
        { label: "Neue Gesamtmiete ab 01.11.2026", value: "670,00 € (bisher 640,00 €)", evidence: ev("verified") },
        { label: "Kündigungsfrist", value: "Bis zum 10. eines Monats zum Ende dieses Monats", evidence: ev("unverified") },
      ],
    });
    renderWithProviders(<KeyFacts doc={doc} scam={false} />, { client: client() });
    const facts = screen.getByRole("region", { name: "Key facts" });
    const valid = within(facts).getByText(/^Valid from/);
    expect(valid).toHaveTextContent("Valid from (Gültig ab)");
    expect(within(valid).getByText(/Gültig ab/).closest("[lang=de]")).not.toBeNull();
    expect(within(facts).getByText("Thu 1 Jan 2026")).toBeInTheDocument();
    expect(within(facts).getByText(/^1,320.kWh$/)).toBeInTheDocument();
    expect(within(facts).getByText("€670.00 (previously €640.00)")).toBeInTheDocument();
    // what stays German is marked German
    expect(within(facts).getByText("Neue Gesamtmiete ab 01.11.2026").closest("[lang=de]")).not.toBeNull();
    expect(within(facts).getByText("Bis zum 10. eines Monats zum Ende dieses Monats")).toHaveAttribute("lang", "de");
  });

  it("says a shared grounding once and makes each chip a 24 px icon button; no page on a one-page letter", async () => {
    const doc = makeDoc({
      pages: 1,
      key_facts: [
        { label: "Surname", value: "RIVERA", evidence: ev("model_read") },
        { label: "Given names", value: "SAM", evidence: ev("model_read") },
        { label: "Passport No.", value: "X1234567", evidence: ev("model_read") },
      ],
    });
    renderWithProviders(<KeyFacts doc={doc} scam={false} />, { client: client() });
    expect(screen.getByText(/Every fact below was read by AI from the photo/)).toBeInTheDocument();
    const chips = screen.getAllByRole("button", { name: /Read by AI from the photo — show/ });
    expect(chips).toHaveLength(3);
    expect(chips[0]).toHaveAccessibleName("Read by AI from the photo — show “Surname” on the page");
    expect(chips[0]).toHaveClass("size-6");
    expect(screen.queryByText(/p\.1/)).toBeNull();
  });

  it("keeps the page on a longer letter, in 12 px chips when the groundings differ", () => {
    const doc = makeDoc({
      pages: 2,
      key_facts: [
        { label: "Refund", value: "324,00 €", evidence: ev("verified", 2) },
        { label: "Tax", value: "1.200,00 €", evidence: ev("unverified", 1) },
      ],
    });
    renderWithProviders(<KeyFacts doc={doc} scam={false} />, { client: client() });
    const chip = screen.getByRole("button", { name: /Found in the letter · p\.2/ });
    expect(chip).toHaveClass("text-[12px]");
    expect(screen.queryByText(/Every fact below/)).toBeNull();
  });
});

describe("To-dos & dates", () => {
  const due = (d: string) => ({ due_date: d, due_date_source: "fixed" as const });

  it("shows a scam letter's demand for what it is: no countdown, no transfer-by, nothing to tick off", () => {
    const item = makeItem({ id: "itm_scam", kind: "payment", direction: "out", title: "Pay alleged arrears (254,35 EUR)", amount: 254.35, ...due("2026-09-30"), send_by: "2026-09-29" });
    renderWithProviders(<ItemsList items={[item]} docId="doc_1" scam />, { client: client() });
    const todos = screen.getByRole("region", { name: "To-dos & dates" });
    expect(within(todos).getByText("Payment this letter demands — don't pay")).toBeInTheDocument();
    expect(within(todos).queryByRole("button", { name: /as done/ })).toBeNull();
    expect(within(todos).queryByRole("button", { name: /More actions/ })).toBeNull();
    expect(todos.querySelector("time")).toBeNull();
    expect(within(todos).queryByText(/transfer by/)).toBeNull();
    // no count of "to-dos" in the heading
    expect(within(todos).getByRole("heading", { level: 2 })).not.toHaveTextContent("·");
    // the title reads the app's way: "(€254.35)"
    expect(within(todos).getByText(/€254\.35\)/)).toBeInTheDocument();
  });

  it("says 'pay on site' for a fee paid at the appointment, 'collected' for a direct debit, and no 'No date' for income", () => {
    const items: Item[] = [
      makeItem({ id: "itm_fee", kind: "payment", direction: "out", title: "Fee for the permit", amount: 100, ...due("2026-10-14"), send_by: "2026-10-13", action: "Pay the €100 fee on site at the appointment by girocard (cash is not accepted)." }),
      makeItem({ id: "itm_debit", kind: "payment", direction: "out", title: "Monthly ticket", amount: 63, ...due("2026-10-01"), send_by: "2026-09-30", action: "Ensure sufficient funds for the SEPA direct debit." }),
      makeItem({ id: "itm_salary", kind: "payment", direction: "in", title: "Monthly salary", amount: 1285.2, recurrence: { interval: 1, unit: "months", working_day: null } }),
      makeItem({ id: "itm_refund", kind: "payment", direction: "in", title: "Tax refund", amount: 324 }),
    ];
    renderWithProviders(<ItemsList items={items} docId="doc_1" />, { client: client() });
    const row = (title: string) => screen.getByText(title).closest("li")!;
    expect(within(row("Fee for the permit")).getByText("pay on site")).toBeInTheDocument();
    expect(within(row("Fee for the permit")).queryByText(/transfer by/)).toBeNull();
    const debit = within(row("Monthly ticket"));
    expect(debit.getByText("collected")).toBeInTheDocument();
    // never red, as on Today
    expect(row("Monthly ticket").querySelector("time")!.getAttribute("data-urgency")).not.toBe("danger");
    expect(within(row("Monthly salary")).getByText("Money in")).toBeInTheDocument();
    expect(within(row("Monthly salary")).queryByText("No date")).toBeNull();
    expect(within(row("Monthly salary")).getByText("every month")).toBeInTheDocument();
    expect(within(row("Tax refund")).getByText("expected")).toBeInTheDocument();
  });

  it("has a 24 px mark-done target with a 3:1 border and a name that says what it does (no aria-pressed)", () => {
    renderWithProviders(<ItemsList items={[makeItem({ title: "Send the form" })]} docId="doc_1" />, { client: client() });
    const tick = screen.getByRole("button", { name: "Mark “Send the form” as done" });
    expect(tick).toHaveClass("size-6");
    expect(tick).not.toHaveAttribute("aria-pressed");
    expect(tick.querySelector("span")).toHaveClass("border-muted");
  });

  it("keeps a ticked-off to-do in its place until you leave the page", () => {
    const a = makeItem({ id: "itm_a", title: "First", ...due("2026-10-01") });
    const b = makeItem({ id: "itm_b", title: "Second", ...due("2026-10-05") });
    let setItems: (items: Item[]) => void = () => {};
    function Page() {
      const [items, set] = useState([a, b]);
      setItems = set;
      return <ItemsList items={items} docId="doc_1" />;
    }
    renderWithProviders(<Page />, { client: client() });
    const titles = () => screen.getAllByRole("listitem").map((li) => within(li).getAllByText(/First|Second/)[0]!.textContent);
    expect(titles()).toEqual(["First", "Second"]);
    // the refreshed list puts done to-dos last; the page keeps the row where it was
    act(() => setItems([b, { ...a, status: "done" }]));
    expect(titles()).toEqual(["First", "Second"]);
    expect(screen.getByRole("button", { name: "Reopen “First”" })).toBeInTheDocument();
  });

  it("closes the date editor with Escape and hands focus back to the row's menu button", async () => {
    const item = makeItem({ id: "itm_x", title: "Pay the fee", kind: "payment", ...due("2026-10-09") });
    renderWithProviders(<ItemsList items={[item]} docId="doc_1" />, { client: client() });
    const user = userEvent.setup();
    const more = screen.getByRole("button", { name: "More actions for Pay the fee" });
    await user.click(more);
    await user.click(await screen.findByRole("menuitem", { name: "Change date" }));
    const input = await screen.findByLabelText("New date for Pay the fee");
    // Save and Cancel stay together
    const save = screen.getByRole("button", { name: "Save date" });
    expect(save.parentElement).toBe(screen.getByRole("button", { name: "Cancel" }).parentElement);
    input.focus();
    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("New date for Pay the fee")).toBeNull();
    await waitFor(() => expect(more).toHaveFocus());
  });

  it("knows a payment made in person", () => {
    expect(paysOnSite(makeItem({ kind: "payment", action: "Pay the 4,50 € in fees at the service desk or the payment machine." }))).toBe(true);
    expect(paysOnSite(makeItem({ kind: "payment", action: "Transfer 55.08 € to the Beitragsservice, or pay in cash." }))).toBe(false);
    expect(paysOnSite(makeItem({ kind: "payment", action: "Transfer the amount by the deadline." }))).toBe(false);
  });
});

describe("Thread, contract and your letters", () => {
  it("wraps a contract's name and amount instead of widening the card, and opens that contract", () => {
    const contract = {
      id: "ctr_bkk",
      name: "Gesetzliche Kranken- und Pflegeversicherung bei Muster BKK",
      category: "insurance",
      cost_amount: 156.55,
      cost_currency: "EUR",
      cost_interval: "monthly",
      status: "active",
      computed: null,
    } as unknown as Contract;
    renderWithProviders(<ContractsSection contracts={[contract]} />, { client: client() });
    const name = screen.getByText(contract.name);
    expect(name).toHaveClass("min-w-0", "[overflow-wrap:anywhere]");
    expect(name).toHaveAttribute("lang", "de");
    expect(name.parentElement).toHaveClass("flex-wrap");
    expect(screen.getByRole("link", { name: /Open in Contracts/ })).toHaveAttribute("href", "/contracts?contract=ctr_bkk");
  });

  it("clamps other letters' titles and draft subjects to two lines, the whole in the tooltip", async () => {
    const long = "Nebenkostenabrechnung 2025 für die Wohnung Nr. 05-2-03 mit Nachzahlung und neuer Vorauszahlung ab November";
    const detail: DocumentDetail = makeDetail({ document: makeDoc({ id: "doc_1" }), related: [makeDoc({ id: "doc_2", title: long, doc_date: "2025-01-01" })] });
    renderWithProviders(<ThreadSection detail={detail} />, { client: client() });
    // on screen the flat number keeps its hyphens unbroken ("05‑2‑03"); the tooltip has the plain words
    const link = screen.getByRole("link", { name: (name) => plainText(name) === long });
    expect(link).toHaveClass("line-clamp-2");
    expect(link).toHaveAttribute("title", long);

    const draft = { id: "drf_1", kind: "objection", subject: long, language: "de", status: "draft", updated_at: "2026-09-20T10:00:00Z" } as unknown as Draft;
    renderWithProviders(<DraftsSection drafts={[draft]} />, { client: client() });
    const subject = screen.getAllByText(long).find((el) => el.closest("a[href='/letters/drf_1']"))!;
    expect(subject).toHaveClass("line-clamp-2");
    expect(subject.closest("a")).toHaveAttribute("title", long);
  });
});

describe("Ideas on the letter page", () => {
  const own = [makeItem({ id: "itm_pay", title: "Pay the fine" }), makeItem({ id: "itm_form", title: "Return the form" })];
  const DOC = "doc_x7k2m9p4q1";

  it("shows only Ideas about this letter that the verdict doesn't already say", () => {
    const ideas = [
      makeSuggestion({ id: "sug_verdict", kind: "deadline", title: "Pay the fine by Thu 1 Oct", refs: [{ type: "item", id: "itm_pay" }, { type: "document", id: "doc_1" }] }),
      makeSuggestion({ id: "sug_calendar", kind: "hygiene", rule_id: "calendar_outdated", title: "Add your 26 dates to your calendar", refs: [{ type: "item", id: "itm_pay" }, { type: "item", id: "itm_other" }] }),
      makeSuggestion({ id: "sug_check", kind: "info", rule_id: "please_check", title: "Please check: the fine", refs: [{ type: "document", id: "doc_1" }, { type: "item", id: "itm_form" }] }),
      makeSuggestion({ id: "sug_scam", kind: "scam", title: "Looks like a scam", refs: [{ type: "document", id: "doc_1" }] }),
      makeSuggestion({ id: "sug_keep", kind: "saving", title: "Compare accounts", refs: [{ type: "document", id: "doc_1" }] }),
      makeSuggestion({ id: "sug_items", kind: "hygiene", title: "Send your certificate", refs: [{ type: "item", id: "itm_form" }, { type: "document", id: "doc_other" }] }),
      makeSuggestion({ id: "sug_done", kind: "saving", status: "dismissed", title: "Hidden", refs: [{ type: "document", id: "doc_1" }] }),
      // a Weekly Ideas insight about the verdict's to-do is new
      makeSuggestion({ id: "sug_review", kind: "followup", source: "review", title: "You now have the receipt — send it", refs: [{ type: "item", id: "itm_pay" }, { type: "document", id: "doc_other" }] }),
    ];
    expect(ideasForLetter(ideas, { docId: "doc_1", items: own, primaryId: "itm_pay" }).map((s) => s.id)).toEqual(["sug_keep", "sug_items", "sug_review"]);
  });

  it("names this letter instead of linking to it", () => {
    expect(onThisLetter("The price-increase letter (doc_0b2t88kqsf2n) about ctr_611d1sk7v1cr shows it.", "doc_0b2t88kqsf2n", [])).toBe(
      "The price-increase letter about ctr_611d1sk7v1cr shows it.",
    );
    expect(onThisLetter("Open item itm_vrtb25ccjmkt from doc_pa2w9q3gxzqk asks for it.", "doc_pa2w9q3gxzqk", [{ id: "itm_vrtb25ccjmkt", title: "Report other funding" }])).toBe(
      "Open item “Report other funding” from this letter asks for it.",
    );
  });

  it("offers the Idea's action (never one that opens this page), 'Remind me in a week' and 'Not relevant'", async () => {
    const fetchSpy = vi.mocked(fetch);
    const ideas = [
      makeSuggestion({
        id: "sug_draft",
        kind: "followup",
        title: "Send your certificate to FitWell",
        rationale: `The letter (${DOC}) asks for it.`,
        refs: [{ type: "document", id: DOC }],
        action: { type: "draft", draft_kind: "general_reply", target_type: "contract", target_id: "ctr_gym", label: null },
      }),
      makeSuggestion({
        id: "sug_self",
        kind: "info",
        title: "Know your limits",
        refs: [{ type: "document", id: DOC }],
        action: { type: "open", draft_kind: null, target_type: "document", target_id: DOC, label: "Open it" },
      }),
    ];
    renderWithProviders(<IdeasSection suggestions={ideas} docId={DOC} items={own} />, { client: client() });
    const section = screen.getByRole("region", { name: "Ideas" });
    const draft = within(section).getByRole("link", { name: /^Draft/ });
    expect(draft).toHaveAttribute("href", expect.stringContaining("/letters?"));
    // a long action wraps inside the card (it pushed the page to 343 px at 320)
    expect(draft).toHaveClass("whitespace-normal", "max-w-full");
    expect(within(section).queryByRole("link", { name: "Open it" })).toBeNull();
    expect(within(section).getByText(/Why: The letter asks for it\./)).toBeInTheDocument();
    expect(within(section).getAllByRole("button", { name: "Remind me in a week" })).toHaveLength(2);
    const user = userEvent.setup();
    await act(() => user.click(within(section).getAllByRole("button", { name: "Not relevant" })[0]!));
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([url, init]) => String(url) === "/api/suggestions/sug_draft" && (init as RequestInit).body === JSON.stringify({ status: "dismissed" }))).toBe(true),
    );
  });
});

describe("Explained simply", () => {
  it("writes money and dates the app's way and marks German terms German, so a long one breaks cleanly", () => {
    const doc = makeDoc({
      explanation: "The ticket becomes valid on 01.01.2026 and 63.00 € will be collected every month.",
      tax_relevant: true,
      tax_note: "The monthly cost may be deductible as work-related travel expenses (Werbungskosten/Entfernungspauschale).",
    });
    const { container } = renderWithProviders(<ExplainedSimply doc={doc} />, { client: client() });
    expect(container).toHaveTextContent("valid on Thu 1 Jan 2026 and €63.00 will be collected");
    const term = screen.getByText("Entfernungspauschale");
    expect(term).toHaveAttribute("lang", "de");
    expect(screen.getByText("Werbungskosten")).toHaveAttribute("lang", "de");
    expect(term.closest("span.min-w-0")).toHaveClass("[overflow-wrap:anywhere]", "hyphens-auto");
  });
});
