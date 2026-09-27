/**
 * UI audit round 1 (document-c): the letter page's warnings, "Why this date?", the Pay panel, the footer and
 * the panel's section headings.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { ADVICE_LINKS } from "@/components/ui/Disclaimer";
import { DocumentFooter, keepTogether, NO_REPLY_KINDS } from "./DocumentFooter";
import { PanelSection } from "./PanelSection";
import { PayPanel } from "./PayPanel";
import { DocumentWarnings, IBAN_FAILS_CHECK, squareIbanClaims } from "./Warnings";
import { adviceFor, receiptDates, WhyThisDate } from "./WhyThisDate";
import { makeDetail, makeDoc, makeItem, makeReceipt, makeSuggestion } from "./fixtures";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const unconfirmed = makeItem({
  id: "itm_probation",
  kind: "milestone",
  title: "End of probation period (Probezeit)",
  due_date: "2026-07-01",
  grounding: "verified",
  evidence: [{ doc_id: "doc_1", page: 1, quote: "Die ersten drei Monate gelten als Probezeit.", grounding: "verified", value_consistent: false, score: 1, boxes: [] }],
});

describe("Please check (R1-document-c-1)", () => {
  it("says it once per thing to check, in one style: the reading's count of unconfirmed dates is left to the to-do's card", () => {
    const doc = makeDoc({
      status: "needs_review",
      warnings: ["Please check: 1 date could not be confirmed against the letter's text.", "Please check: the hourly wage on page 2 is hard to read."],
    });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [unconfirmed] })} />, { client: client() });
    expect(screen.queryByText(/could not be confirmed/)).toBeNull();
    // the other warning keeps its own card, without "Please check:" again under the card's heading
    expect(screen.getByText("The hourly wage on page 2 is hard to read.")).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2, name: "Please check" });
    expect(headings).toHaveLength(2);
    expect(headings[0]!.className).toBe(headings[1]!.className);
    expect(screen.getByText("End of probation period (Probezeit)", { exact: false })).toBeInTheDocument();
  });

  it("drops the count when the dates were confirmed since (nothing left to check)", () => {
    const doc = makeDoc({ warnings: ["Please check: 2 dates could not be confirmed against the letter's text."] });
    const { container } = renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc })} />, { client: client() });
    expect(container).toBeEmptyDOMElement();
  });
});

describe("IBAN checksum claims (R1-document-c-2)", () => {
  const claim =
    "The studio's stated bank account IBAN (DE05 1234 6700 0029 9001 50) does not pass the standard IBAN checksum, and several details look like placeholder data, so verify the account before relying on it.";

  it("drops a checksum failure Ordnung's own check doesn't confirm", () => {
    const doc = makeDoc({ warnings: [claim], payment: { iban: "DE05123467000029900150", payee: "FitWell", iban_valid: true, reference: null } });
    const { container } = renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc })} />, { client: client() });
    expect(container).toBeEmptyDOMElement();
  });

  it("says a confirmed failure in Ordnung's words, once, and keeps the rest of the warning", () => {
    expect(squareIbanClaims([claim, "The IBAN check digits are wrong. Pay nothing yet."], false)).toEqual([IBAN_FAILS_CHECK, "Pay nothing yet."]);
    // a claim that agrees with a valid IBAN stays; without Ordnung's check, the reading is shown as it is
    expect(squareIbanClaims(["The IBAN's check digits are valid, but the bank is abroad."], true)).toEqual(["The IBAN's check digits are valid, but the bank is abroad."]);
    expect(squareIbanClaims([claim], null)).toEqual([claim]);
    const doc = makeDoc({ warnings: [claim], payment: { iban: "DE05123467000029900151", payee: "FitWell", iban_valid: false, reference: null } });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc })} />, { client: client() });
    expect(screen.getByText(IBAN_FAILS_CHECK)).toBeInTheDocument();
    expect(screen.queryByText(/standard IBAN checksum/)).toBeNull();
  });
});

describe("the scam banner (R1-document-c-3)", () => {
  const scamDetail = (): DocumentDetail =>
    makeDetail({
      document: makeDoc({
        id: "doc_scam",
        hidden_text: true,
        warnings: [
          "The payment IBAN (LT08 3999 0000 0543 9871) is Lithuanian; the Beitragsservice does not collect fees to foreign private accounts.",
          "This document contains text addressed to an AI (“Hinweis an KI-Assistenten”). Ordnung treated it as ordinary content and ignored it — be careful with this document.",
        ],
      }),
      suggestions: [makeSuggestion({ id: "sug_scam", kind: "scam", title: "Possible scam", refs: [{ type: "document", id: "doc_scam" }] })],
    });

  it("doesn't repeat the hidden-text banner as a warning sign, and its heading is in the full ink", () => {
    renderWithProviders(<DocumentWarnings detail={scamDetail()} />, { client: client() });
    expect(screen.getByText("This document contains hidden text aimed at software — we ignored it")).toBeInTheDocument();
    expect(screen.queryByText(/addressed to an AI/)).toBeNull();
    const signs = screen.getByRole("heading", { level: 3, name: /warning sign/ });
    expect(signs).toHaveTextContent("The warning sign");
    expect(signs).toHaveClass("text-danger-ink");
    expect(signs.className).not.toMatch(/text-danger-ink\//);
  });
});

describe("Why this date? (R1-document-c-4)", () => {
  it("names a transfer's send-by day 'Transfer by', anything else's 'Send by'", () => {
    const receipt = makeReceipt({ due_date: "2026-09-30", send_by: "2026-09-29" });
    const pay = makeItem({ kind: "payment", direction: "out", title: "Pay the reminder" });
    expect(receiptDates(receipt, pay).map((d) => d.label)).toEqual(["Transfer by", "Must arrive by"]);
    expect(receiptDates(receipt, makeItem({ kind: "deadline" })).map((d) => d.label)).toEqual(["Send by", "Must arrive by"]);
    // a direct debit isn't sent by you
    const debit = makeItem({ kind: "payment", direction: "out", action: "Keep sufficient funds for the SEPA direct debit." });
    expect(receiptDates(receipt, debit)[0]!.label).toBe("Send by");
  });

  it("points a tenancy letter to the tenants' association and a company's to consumer advice, whatever area it was read under", () => {
    expect(adviceFor("residence", "utility_bill", "landlord")).toBe(ADVICE_LINKS.rent);
    expect(adviceFor("residence", "rent_lease", null)).toBe(ADVICE_LINKS.rent);
    expect(adviceFor("residence", "residence_permit", "immigration_office")).toBe(ADVICE_LINKS.residence);
    expect(adviceFor("home", "contract", "utility")).toBe(ADVICE_LINKS.consumer);
    expect(adviceFor("money", "dunning", "retailer")).toBeUndefined();
    // without the letter's kinds, by area as before
    expect(adviceFor("residence")).toBe(ADVICE_LINKS.residence);
    expect(adviceFor("tax")).toBe(ADVICE_LINKS.tax);
  });

  it("opens the receipt with 'Transfer by' and the letter's own advice", async () => {
    const qc = client();
    const statement = makeDetail({
      document: makeDoc({ id: "doc_nk", kind: "utility_bill", area: "residence", party_id: "pty_landlord" }),
      party: { id: "pty_landlord", name: "Wohnbau Musterstadt eG", kind: "landlord" } as DocumentDetail["party"],
    });
    qc.setQueryData(qk.documents.detail("doc_nk"), statement);
    const item = makeItem({ kind: "payment", direction: "out", title: "Back payment", doc_id: "doc_nk", area: "residence", priority: "high" });
    renderWithProviders(<WhyThisDate receipt={makeReceipt({ due_date: "2026-10-09", send_by: "2026-10-08" })} area="residence" item={item} />, { client: qc });
    await userEvent.setup().click(screen.getByRole("button", { name: /Why this date\?/ }));
    const pop = await screen.findByRole("dialog", { name: "Why this date?" });
    expect(within(pop).getByText("Transfer by")).toBeInTheDocument();
    expect(within(pop).getByRole("link", { name: /Mieterverein/ })).toBeInTheDocument();
    expect(within(pop).queryByText(/Studierendenwerk/)).toBeNull();
  });
});

describe("the Pay panel (R1-document-c-5)", () => {
  const doc = makeDoc({ payment: { iban: "DE70123478000048213000", payee: "TechMarkt Online GmbH", iban_valid: true, reference: "TM-2026-0048213" } });
  const item = makeItem({ kind: "payment", direction: "out", title: "Pay the reminder", amount: 94.99, currency: "EUR", due_date: "2026-09-30", send_by: "2026-09-29" });

  it("keeps the IBAN's groups whole, says when to transfer, and names its copy buttons as written", () => {
    renderWithProviders(<PayPanel item={item} doc={doc} onPaid={() => {}} close={() => {}} />, { client: client() });
    const groups = [...document.querySelectorAll(".font-ident .whitespace-nowrap")].map((g) => g.textContent);
    expect(groups).toEqual(["DE70", "1234", "7800", "0048", "2130", "00"]);
    expect(screen.getByText("Transfer by")).toBeInTheDocument();
    expect(screen.getByText(/must arrive/)).toHaveTextContent("(must arrive Wed 30 Sep)");
    for (const name of ["Copy IBAN", "Copy reference", "Copy amount"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy iban/ })).toBeNull();
    // the buttons stay in view at the bottom of a scrolled panel
    expect(screen.getByRole("button", { name: "I've paid it" }).parentElement).toHaveClass("sticky", "bg-surface");
  });

  it("counts to the due date once the transfer day has passed", () => {
    const late = { ...item, send_by: "2026-09-27" };
    renderWithProviders(<PayPanel item={late} doc={doc} onPaid={() => {}} />, { client: client() });
    expect(screen.queryByText("Transfer by")).toBeNull();
    expect(screen.getByText("by")).toBeInTheDocument();
  });
});

describe("the footer (R1-document-c-6)", () => {
  it("offers no reply to a passport, a payslip, a certificate or an appointment card — but to a letter", () => {
    for (const kind of ["identity_document", "payslip", "certificate", "appointment"] as const) {
      expect(NO_REPLY_KINDS.has(kind)).toBe(true);
      const { unmount } = renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ kind }) })} />, { client: client() });
      expect(screen.queryByRole("button", { name: "Draft a reply" })).toBeNull();
      unmount();
    }
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ kind: "invoice" }) })} />, { client: client() });
    expect(screen.getByRole("button", { name: "Draft a reply" })).toBeInTheDocument();
    // Delete sits apart at the end of its row, also when it wraps alone
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass("ml-auto");
  });

  it("wraps the provenance chip as a card, never between '1' and 'page' or inside the date", () => {
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ text_mode: "vision", pages: 1 }) })} />, { client: client() });
    const chip = screen.getByText(/^Read by Claude on/).closest("p")!;
    expect(chip).toHaveClass("rounded-xl");
    expect(chip).not.toHaveClass("rounded-full");
    // it breaks after the dot: "Read by Claude on 28 Sep 2026 ·" / "from a photo, 1 page"
    expect(keepTogether("Read by Claude on 28 Sep 2026 · from a photo, 1 page")).toBe(
      "Read by Claude on 28\u00a0Sep\u00a02026\u00a0· from\u00a0a\u00a0photo,\u00a01\u00a0page",
    );
    expect(keepTogether("Not read yet · 2 pages")).toBe("Not read yet\u00a0· 2\u00a0pages");
  });
});

describe("panel section headings", () => {
  it("say what a count counts to a screen reader, in the app's eyebrow", () => {
    renderWithProviders(
      <PanelSection id="todos" title="To-dos & dates" count={3} countLabel="3 open">
        <p>…</p>
      </PanelSection>,
    );
    expect(screen.getByRole("region", { name: "To-dos & dates, 3 open" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveClass("eyebrow");
  });
});
