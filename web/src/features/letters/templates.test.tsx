import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Party } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { ibanLooksValid, normalizeIban } from "@/lib/format";
import { __clearToasts } from "@/components/ui/Toast";
import LettersPage from "@/pages/LettersPage";
import { templateLetter as mockTemplateLetter } from "@/mocks/data/templateLetters";
import { followUpDate, mayBeCourt, needsTypedCourt, objectionCheck } from "./logic";
import {
  SCHUFA_ADDRESS,
  TEMPLATES,
  TEMPLATE_BY_KIND,
  detailsPayload,
  fieldError,
  isTemplateKind,
  joinAnd,
  letterDefaults,
  missingFields,
  nextDay,
  parseMoney,
  sortForTemplate,
  statutoryDeadlines,
  templateRefusal,
} from "./templates";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("template letter helpers", () => {
  it("reads amounts typed German or English style", () => {
    expect(parseMoney("1.234,50")).toBe(1234.5);
    expect(parseMoney("80")).toBe(80);
    expect(parseMoney("80,5")).toBe(80.5);
    expect(parseMoney("80,-")).toBe(80);
    expect(parseMoney("1,234.50")).toBe(1234.5);
    expect(parseMoney("1234.5")).toBe(1234.5);
    expect(parseMoney(" 50 € ")).toBe(50);
    expect(parseMoney("")).toBeNull();
    expect(parseMoney(undefined)).toBeNull();
    expect(parseMoney("fifty")).toBeNull();
    expect(parseMoney("-5")).toBeNull();
  });

  it("reads a dot or comma before three digits as thousands — 1.500 is never 1,50 €", () => {
    expect(parseMoney("1.500")).toBe(1500);
    expect(parseMoney("1.234")).toBe(1234);
    expect(parseMoney("12.000")).toBe(12000);
    expect(parseMoney("1.500.000")).toBe(1500000);
    expect(parseMoney("1,500")).toBe(1500);
    expect(parseMoney("12,000.5")).toBe(12000.5);
    // ambiguous or malformed: refused instead of guessed
    expect(parseMoney("1.2345")).toBeNull();
    expect(parseMoney("1.50.0")).toBeNull();
    expect(parseMoney("1234.567")).toBeNull();
    const deposit = TEMPLATE_BY_KIND.deposit_return.fields.find((f) => f.name === "amount")!;
    expect(fieldError(deposit, { amount: "1.500" }, "2026-09-28")).toBeNull();
    expect(detailsPayload(TEMPLATE_BY_KIND.deposit_return, { moved_out_on: "2026-09-01", amount: "1.500" })).toEqual({ moved_out_on: "2026-09-01", amount: 1500 });
    expect(fieldError(deposit, { amount: "1.2345" }, "2026-09-28")).toMatch(/Enter an amount/);
  });

  it("checks an instalment and a new date against the letter's own amount and deadline", () => {
    const plan = TEMPLATE_BY_KIND.payment_plan;
    const instalment = plan.fields.find((f) => f.name === "instalment")!;
    // "1.500" with an instalment of 50 is fine (it used to read as 1,50 €)
    expect(fieldError(instalment, { instalment: "50", amount: "1.500" }, "2026-09-28")).toBeNull();
    expect(fieldError(instalment, { instalment: "200" }, "2026-09-28", { deadline: null, amount: 120 })).toMatch(/more than the amount you owe/);
    expect(fieldError(instalment, { instalment: "200", amount: "300" }, "2026-09-28", { deadline: null, amount: 120 })).toBeNull();
    const until = TEMPLATE_BY_KIND.extension_request.fields.find((f) => f.name === "until")!;
    expect(fieldError(until, { until: "2026-10-10" }, "2026-09-28", { deadline: "2026-10-12", amount: null })).toMatch(/after the letter's deadline/);
    expect(fieldError(until, { until: "2026-10-20" }, "2026-09-28", { deadline: "2026-10-12", amount: null })).toBeNull();
    expect(
      letterDefaults([
        { kind: "payment", status: "open", due_date: "2026-10-20", amount: 99 },
        { kind: "payment", status: "done", due_date: "2026-10-01", amount: 5 },
        { kind: "payment", status: "open", due_date: "2026-10-05", amount: 120 },
        { kind: "deadline", status: "snoozed", due_date: "2026-10-12", amount: null },
        { kind: "task", status: "open", due_date: null, amount: null },
      ]),
    ).toEqual({ deadline: "2026-10-12", amount: 120 });
  });

  it("never offers a deadline the law sets as the one to extend", () => {
    const objection = { type: "relative", nature: "objection" } as const;
    const items = [
      { kind: "deadline", status: "open", due_date: "2026-10-05", amount: null, origin: "rule" as const },
      { kind: "deadline", status: "open", due_date: "2026-10-08", amount: null, origin: "extracted" as const, date_spec: { ...objection } },
      { kind: "deadline", status: "open", due_date: "2026-10-12", amount: null, origin: "extracted" as const },
    ] as Parameters<typeof letterDefaults>[0];
    expect(letterDefaults(items).deadline).toBe("2026-10-12");
    expect(statutoryDeadlines(items).map((i) => i.due_date)).toEqual(["2026-10-05", "2026-10-08"]);
    expect(letterDefaults(items.slice(0, 2)).deadline).toBeNull();
  });

  it("refuses more time against a court order or a dismissal, and instalments offered to a court", () => {
    expect(templateRefusal("extension_request", "court_payment_order")?.body).toMatch(/§ 692 ZPO/);
    expect(templateRefusal("extension_request", "enforcement_order")?.body).toMatch(/Notfrist/);
    expect(templateRefusal("extension_request", "dismissal")?.body).toMatch(/§ 4 KSchG/);
    expect(templateRefusal("payment_plan", "enforcement_order")?.title).toMatch(/claimant, not the court/);
    expect(templateRefusal("payment_plan", "dismissal")).toBeNull();
    expect(templateRefusal("extension_request", "tax_assessment")).toBeNull();
    expect(templateRefusal("withdrawal", "court_payment_order")).toBeNull();
  });

  it("lists the required facts still missing, in form order", () => {
    const plan = TEMPLATE_BY_KIND.payment_plan;
    expect(missingFields(plan, {})).toEqual(["the monthly instalment", "the day of the first instalment"]);
    expect(missingFields(plan, { instalment: "0" })).toEqual(["the monthly instalment", "the day of the first instalment"]);
    expect(missingFields(plan, { instalment: "50", first_instalment: "2026-11-01" })).toEqual([]);
    expect(missingFields(TEMPLATE_BY_KIND.data_access, {})).toEqual([]);
    expect(missingFields(TEMPLATE_BY_KIND.withdrawal, { subject_matter: "  " })).toEqual(["what you ordered"]);
    // every required fact says in plain words what is missing
    for (const t of TEMPLATES) for (const f of t.fields) if (f.required) expect(f.need).toMatch(/^[a-z]/);
    expect(joinAnd(["a"])).toBe("a");
    expect(joinAnd(["a", "b", "c"])).toBe("a, b and c");
    expect(nextDay("2026-09-30")).toBe("2026-10-01");
  });

  it("flags dates on the wrong side of today and unreadable amounts", () => {
    const plan = TEMPLATE_BY_KIND.payment_plan;
    const first = plan.fields.find((f) => f.name === "first_instalment")!;
    const instalment = plan.fields.find((f) => f.name === "instalment")!;
    expect(fieldError(first, { first_instalment: "2026-09-28" }, "2026-09-28")).toBe("Choose a day after today.");
    expect(fieldError(first, { first_instalment: "2026-10-01" }, "2026-09-28")).toBeNull();
    expect(fieldError(instalment, { instalment: "lots" }, "2026-09-28")).toMatch(/Enter an amount/);
    const received = TEMPLATE_BY_KIND.withdrawal.fields.find((f) => f.name === "received_on")!;
    expect(fieldError(received, { received_on: "2026-10-02" }, "2026-09-28")).toBe("This day can't be in the future.");
    const until = TEMPLATE_BY_KIND.extension_request.fields.find((f) => f.name === "until")!;
    expect(fieldError(until, { until: "2026-10-10", deadline: "2026-10-12" }, "2026-09-28")).toBe("Choose a day after the current deadline.");
  });

  it("sends only this template's facts, typed", () => {
    expect(detailsPayload(TEMPLATE_BY_KIND.payment_plan, { instalment: "1.000,00", first_instalment: "2026-11-01", amount: "", defect: "ignored" })).toEqual({
      instalment: 1000,
      first_instalment: "2026-11-01",
    });
    expect(detailsPayload(TEMPLATE_BY_KIND.withdrawal, { subject_matter: " Kaffeemaschine ", instructions_missing: true })).toEqual({
      subject_matter: "Kaffeemaschine",
      instructions_missing: true,
    });
    expect(detailsPayload(TEMPLATE_BY_KIND.data_access, {}, ` ${SCHUFA_ADDRESS} `)).toEqual({ recipient: SCHUFA_ADDRESS });
  });

  it("puts the likely recipients first", () => {
    const parties = [
      { kind: "bank", name: "Bank" },
      { kind: "landlord", name: "Wohnbau" },
      { kind: "person", name: "Anna" },
    ] as Pick<Party, "kind" | "name">[];
    expect(sortForTemplate(parties, TEMPLATE_BY_KIND.deposit_return).map((p) => p.name)).toEqual(["Wohnbau", "Anna", "Bank"]);
    expect(sortForTemplate(parties, null).map((p) => p.name)).toEqual(["Anna", "Bank", "Wohnbau"]);
  });

  it("knows every template kind", () => {
    expect(TEMPLATES).toHaveLength(8);
    expect(isTemplateKind("deposit_return")).toBe(true);
    expect(isTemplateKind("objection")).toBe(false);
    expect(isTemplateKind(null)).toBe(false);
  });
});

describe("statutory objections and follow-ups", () => {
  it("offers the law's remedy against court orders and a landlord's notice, whatever the instructions say", () => {
    expect(objectionCheck({ kind: "court_payment_order", remedy: null, area: "money" })).toMatchObject({ ok: true, term: "Widerspruch", statutory: true, remedy: null });
    expect(objectionCheck({ kind: "enforcement_order", remedy: { type: "none", addressee: null, period_text: null, form_text: null, quote: null }, area: "money" })).toMatchObject({
      ok: true,
      term: "Einspruch",
      statutory: true,
    });
    expect(objectionCheck({ kind: "landlord_notice", remedy: null, area: "home" })).toMatchObject({ ok: true, term: "Widerspruch", statutory: true });
    expect(objectionCheck({ kind: "dismissal", remedy: null, area: "work" })).toMatchObject({ ok: false, reason: "missing" });
  });

  it("the static demo's withdrawal says what the real rules say: e-mail first, holidays counted", () => {
    const ctx = { details: { subject_matter: "Kaffeemaschine", received_on: "2026-12-11" }, reference: null, docDate: null, topic: null, address: "", iban: "", taxOffice: false, schufa: false, today: "2026-12-14" };
    const letter = mockTemplateLetter("withdrawal", ctx);
    // 14 days end on Christmas Day (Fri 25 Dec 2026): the next working day is Mon 28 Dec (§ 193 BGB)
    expect(letter.guidance.send_by).toBe("2026-12-28");
    expect(letter.notes[0]).toContain("Mon 28 Dec 2026");
    const recommended = letter.guidance.channels.filter((c) => c.recommended).map((c) => c.channel);
    expect(recommended).toEqual(["email"]);
    expect(letter.guidance.channels.find((c) => c.channel === "online_button")?.note).toMatch(/Not for contracts made at the door or by phone/);
  });

  it("gives a data request a month to answer before the follow-up", () => {
    expect(followUpDate("2026-09-28", "data_access")).toBe("2026-11-02");
    expect(followUpDate("2026-09-28", "withdrawal")).toBe("2026-10-19");
  });

  it("checks an IBAN like the server", () => {
    expect(normalizeIban("de89 3704-0044 0532.0130 00")).toBe("DE89370400440532013000");
    expect(ibanLooksValid("DE89 3704 0044 0532 0130 00")).toBe(true);
    expect(ibanLooksValid("DE89 3704 0044 0532 0130 01")).toBe(false);
    expect(ibanLooksValid("not an iban")).toBe(false);
    // a valid checksum at the wrong length for its country: the server refuses it too
    expect(ibanLooksValid("DE86 3704 0044 0532 0130")).toBe(false);
    expect(ibanLooksValid("AT61 1904 3002 3457 3201")).toBe(true);
  });

  it("offers no hardship objection against a notice without notice period — as its card says", () => {
    const notice = { kind: "landlord_notice" as const, remedy: null, area: "home" as const };
    const fristlos = {
      kind: "landlord_notice" as const,
      title: "Notice from your landlord — get advice before you act",
      summary: "",
      urgent: false,
      steps: [],
      facts: [{ title: "This reads as a notice without notice period (fristlos)", text: "The hardship objection doesn't apply to it, so Ordnung doesn't draft one.", tone: "warn" as const, citation: "§ 574 Abs. 1 S. 2 BGB" }],
      help: [],
      rule_ids: [],
      draft: null,
      handled: false,
      closable: true,
    };
    expect(objectionCheck(notice, fristlos)).toMatchObject({ ok: false, reason: "no_hardship", title: "This reads as a notice without notice period (fristlos)" });
    expect(objectionCheck(notice, { ...fristlos, draft: "objection" })).toMatchObject({ ok: true, term: "Widerspruch" });
  });
});

describe("composer — template letters", () => {
  it("writes a data request to SCHUFA from a typed address", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router, container } = renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Ask for your data/ }));
    expect(within(dialog).getByText("Which company or office?")).toBeInTheDocument();
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("Choose who the letter is for.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use SCHUFA's address" }));
    expect(within(dialog).getByLabelText(/Or type their name and address/)).toHaveValue(SCHUFA_ADDRESS);
    expect(write).toBeEnabled();
    assertNoRawEnumsInElement(container);
    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "data_access", party_id: null, details: { recipient: SCHUFA_ADDRESS } });
  });

  it("keeps an instalment request disabled until its facts are there, then sends them typed", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Pay in instalments/ }));
    await user.selectOptions(within(dialog).getByLabelText(/Or write to someone without a letter/), "pty_finanzamt");
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("Still needed: the monthly instalment and the day of the first instalment.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Monthly instalment you can pay/), "50");
    const first = within(dialog).getByLabelText(/First instalment on/);
    // a future date can't be today: the picker starts tomorrow
    expect(first).toHaveAttribute("min", "2026-09-29");
    await user.type(first, "2026-09-01");
    expect(await within(dialog).findByText("Choose a day after today.")).toBeInTheDocument();
    expect(write).toBeDisabled();
    await user.clear(first);
    await user.type(first, "2026-11-01");
    await waitFor(() => expect(write).toBeEnabled());
    // how an amount was read is shown next to it: "1.500" is 1.500 €, not 1,50 €
    const total = within(dialog).getByLabelText(/Total amount/);
    await user.type(total, "1.500");
    expect(total).toHaveAccessibleDescription(/= €1,500\.00|= 1\.500,00 €/);
    await user.clear(total);

    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "payment_plan", party_id: "pty_finanzamt", details: { instalment: 50, first_instalment: "2026-11-01" } });
  });

  it("won't ask a court for more time or offer it instalments — before anything is written", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?new=1&doc=doc_mahnbescheid" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Ask for more time/ }));
    expect(await within(dialog).findByText("A court's deadline can't be extended")).toBeInTheDocument();
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    // nothing to fill in for a letter that can't be written
    expect(within(dialog).queryByLabelText(/New date you ask for/)).toBeNull();
    expect(within(dialog).queryByLabelText(/Your wishes/)).toBeNull();
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("This letter can't answer the one you chose — see why under the letters.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("radio", { name: /Pay in instalments/ }));
    expect(await within(dialog).findByText("Offer instalments to the claimant, not the court")).toBeInTheDocument();
    // review round 1: the offer acknowledges the claim (§ 212 BGB), and "§" never parts from its number
    expect(within(dialog).getByText(/limitation period starts again/).textContent).toContain("(§\u00a0212 Abs.\u00a01 Nr.\u00a01 BGB)");
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeDisabled();
    expect(calls.some((c) => c.method === "POST" && c.path === "/drafts")).toBe(false);
  });

  it("offers instalments on a court order to its claimant, typed in (review round 1: it was a dead end)", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?new=1&doc=doc_mahnbescheid" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Pay in instalments/ }));
    await user.click(await within(dialog).findByRole("button", { name: "Write to the claimant instead" }));
    const claimant = within(dialog).getByLabelText(/The claimant \(Antragsteller\)/);
    expect(within(dialog).queryByText("Offer instalments to the claimant, not the court")).toBeNull();
    // review round 2: focus goes to the claimant's box, the order stays chosen, and the court's deadline and
    // the acknowledgement are still said; no "To <court>" card
    await waitFor(() => expect(claimant).toHaveFocus());
    expect(within(dialog).getByRole("radio", { name: /Mahnbescheid|payment order/i, checked: true })).toBeInTheDocument();
    expect(within(dialog).getByText("The letter goes to the claimant")).toBeInTheDocument();
    expect(within(dialog).getByText(/Still pay or object by the court's deadline/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/^To$/)).toBeNull();
    await user.type(claimant, "Streamline Media GmbH{Enter}Musterweg 1{Enter}12345 Berlin");
    await user.type(within(dialog).getByLabelText(/Monthly instalment/), "20");
    await user.type(within(dialog).getByLabelText(/First instalment on/), "2026-10-15");
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    await waitFor(() => expect(write).toBeEnabled());
    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "payment_plan", doc_id: "doc_mahnbescheid", party_id: null, details: { recipient: "Streamline Media GmbH\nMusterweg 1\n12345 Berlin" } });
  });

  it("knows a court's name from a company's (review round 3 of phase 2)", () => {
    for (const court of ["Amtsgericht Hünfeld", "Zentrales Mahngericht Berlin-Brandenburg", "AG Hagen", "Arbeitsgericht Köln", "des LG Köln"]) {
      expect(mayBeCourt(court), court).toBe(true);
    }
    for (const other of ["TechMarkt Online GmbH", "LG Electronics Deutschland GmbH", "Gerichtskasse Hagen", "Gerichtsvollzieher Müller", "", null]) {
      expect(mayBeCourt(other), String(other)).toBe(false);
    }
    // review round 4 of phase 2: "AG" alone enabled "Write the letter", and the server refused it — a local court's
    // abbreviation needs its place; a federal court's may stand alone
    for (const bare of ["AG", "AG ", "LG", "OLG"]) expect(mayBeCourt(bare), bare).toBe(false);
    for (const federal of ["BGH", "BSG, 1. Senat", "AG Hünfeld\n36088 Hünfeld"]) expect(mayBeCourt(federal), federal).toBe(true);
    const order = { kind: "court_payment_order" as const, remedy: null };
    expect(needsTypedCourt(order, { name: "TechMarkt Online GmbH" })).toBe(true);
    expect(needsTypedCourt(order, null)).toBe(true);
    expect(needsTypedCourt(order, { name: "Amtsgericht Hagen" })).toBe(false);
    expect(needsTypedCourt({ ...order, remedy: { type: "widerspruch", addressee: "Amtsgericht Hagen", period_text: null, form_text: null, quote: null } }, { name: "TechMarkt" })).toBe(false);
    expect(needsTypedCourt({ kind: "tax_assessment", remedy: null }, null)).toBe(false);
  });

  it("sends an objection to a court order filed from the claimant's letter to the court, typed in", async () => {
    const { srv, calls } = useMockApi({ full: true });
    // the reminder re-filed as a Mahnbescheid: its sender is still TechMarkt (review round 3 of phase 2)
    await srv.handle("PATCH", "/documents/doc_tm_dunning", new URLSearchParams(), { kind: "court_payment_order" }, null);
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?new=1&kind=objection&doc=doc_tm_dunning" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const court = await within(dialog).findByLabelText(/The court that sent the order/);
    // the one field left to fill takes the focus (review round 4: it opened below the fold, unfocused)
    await waitFor(() => expect(court).toHaveFocus());
    // never "To TechMarkt": the objection doesn't go to the claimant
    expect(within(dialog).queryByText(/^To$/)).toBeNull();
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText(/Type the court's name and address/)).toBeInTheDocument();
    await user.type(court, "TechMarkt Online GmbH");
    expect(within(dialog).getByText(/doesn't look like a court's name/)).toBeInTheDocument();
    expect(write).toBeDisabled();
    await user.clear(court);
    await user.type(court, "Amtsgericht Hünfeld{Enter}Zentrales Mahngericht{Enter}36088 Hünfeld");
    await waitFor(() => expect(write).toBeEnabled());
    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "objection", doc_id: "doc_tm_dunning", party_id: null, details: { recipient: expect.stringContaining("Amtsgericht Hünfeld") } });
  });

  it("never takes the court for the claimant, and shows one recipient box (review round 3 of phase 2)", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?new=1&doc=doc_mahnbescheid" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Pay in instalments/ }));
    await user.click(await within(dialog).findByRole("button", { name: "Write to the claimant instead" }));
    // the claimant's box only: "Who is it for?" never next to it (both would hold the same text)
    expect(within(dialog).getAllByRole("textbox", { name: /claimant|Who is it for/i })).toHaveLength(1);
    // the offer's note keeps what money paid on a time-barred claim means (§ 214 Abs. 2 BGB)
    expect(within(dialog).getByText(/can't be reclaimed/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/The claimant \(Antragsteller\)/), "Amtsgericht Hünfeld");
    expect(within(dialog).getByText(/That's a court/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Monthly instalment/), "20");
    await user.type(within(dialog).getByLabelText(/First instalment on/), "2026-10-15");
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeDisabled();
    expect(calls.some((c) => c.method === "POST" && c.path === "/drafts")).toBe(false);
  });

  it("lists the letters a template answers first (review round 3 of phase 2)", async () => {
    useMockApi({ full: true });
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /See the receipts/ }));
    expect(within(dialog).getByText("Operating-cost and utility statements come first.")).toBeInTheDocument();
    const letters = within(dialog).getAllByRole("radio").filter((r) => r.getAttribute("name") === "letter-about");
    expect(letters[0]!.closest("label")?.textContent ?? letters[0]!.parentElement?.textContent).toMatch(/statement|Abrechnung|Nebenkosten|bill/i);
  });

  it("asks who a letter is for when its sender isn't in Ordnung, and starts a withdrawal with nothing guessed", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Withdraw from a purchase/ }));
    // a letter flagged as a possible scam is never answered with a template
    expect(within(dialog).queryByRole("radio", { name: /Last reminder/ })).toBeNull();
    await user.click(within(dialog).getByRole("radio", { name: /Passport \(photo\)/ }));
    // the letter's title is Ordnung's summary, not what was ordered
    expect(within(dialog).getByLabelText(/What did you order or sign up for/)).toHaveValue("");
    await user.type(within(dialog).getByLabelText(/What did you order or sign up for/), "Fotoservice");
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("Type who the letter is for — its sender isn't in Ordnung.")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Who is it for/), "Foto Schnell GmbH{Enter}Bahnhofstraße 1{Enter}12345 Musterstadt");
    await waitFor(() => expect(write).toBeEnabled());
    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "withdrawal", party_id: null, details: { subject_matter: "Fotoservice", recipient: expect.stringContaining("Foto Schnell GmbH") } });
  });
});
