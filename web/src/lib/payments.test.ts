/**
 * `payments.ts` mirrors `ordnung/payments.py` (tests/test_payments.py has the same cases): a to-do
 * naming a direct debit in German or English — unless its debit failed or its action asks for a transfer
 * (a standing order to set up or change) — and the reference to type without its label.
 */
import { describe, expect, it } from "vitest";
import { asksForTransfer, isDirectDebit, isTransfer, paymentReference } from "./payments";

const todo = (title: string, action: string | null = null) => ({ kind: "payment" as const, title, action, description: null });

describe("isDirectDebit", () => {
  it.each([
    ["Monthly fee", "Collected by direct debit"],
    ["Monatsbeitrag", "Wird per Bankeinzug eingezogen"],
    ["Jahresbeitrag", "Will be debited from your account"],
    ["Monatliche Abbuchung Deutschlandticket", null],
    ["Monthly mobile fee", "Ensure sufficient funds for the monthly SEPA direct debit of 34.99 €."],
  ])("%s / %s is a direct debit", (title, action) => {
    expect(isDirectDebit(todo(title, action))).toBe(true);
  });

  it.each([
    ["Pay the invoice", "Transfer 49.99 EUR by 15.09.2026"],
    ["Rücklastschrift", "Bitte überweisen Sie den Betrag zuzüglich der Bankgebühr"],
    ["Kaution vor dem Einzug", null],
  ])("%s / %s is none", (title, action) => {
    expect(isDirectDebit(todo(title, action))).toBe(false);
  });

  // a debit that failed — with no "transfer" in the action — or moving in: a payment to make, so Today
  // files it under Pay / "Transfer by", not "Collected"
  it.each([
    ["Beitrag nachzahlen – konnte nicht eingezogen werden", "Pay 55.08 € by 15.10.2026"],
    ["Rundfunkbeitrag nachzahlen – Lastschrift konnte nicht eingelöst werden", "Pay 49.99 € by 01.10.2026"],
    ["Pay Rundfunkbeitrag (amount could not be debited)", "Pay 55.08 € by 15.10.2026"],
    ["Mitgliedsbeitrag nach Rücklastschrift", "Pay 47.40 € by 12.12.2025"],
    ["Gym fee: direct debit was returned by the bank", "Pay 47.40 € including the fee"],
    ["Abbuchung fehlgeschlagen", "Pay 29.90 € by 15.10.2026"],
    ["Die Lastschrift wurde mangels Deckung nicht ausgeführt", "Pay 29.90 € plus 3.00 € fee"],
    ["Beitrag (Mandatsreferenz M-4711)", "Mandate was cancelled; please pay yourself"],
    ["Die erste Miete von 640 € zahlen, sobald Sie eingezogen sind", null],
    ["Kaution von 1.560 € vor dem Einziehen bezahlen", null],
    ["First rent", "Pay the first rent of 640 € once you have moved in (eingezogen)"],
  ])("%s / %s is a payment to make", (title, action) => {
    const item = todo(title, action);
    expect(isDirectDebit(item)).toBe(false);
    expect(isTransfer({ ...item, direction: "out" })).toBe(true);
  });

  // a standing order the person sets up or changes is their own transfer (the demo's €670 rent had no send-by day)
  it.each([
    ["New monthly total rent €670", "Adjust your standing order to the new total rent unless you use direct debit."],
    ["Neue Gesamtmiete", "Dauerauftrag auf 670 € anpassen, falls Sie nicht per Lastschrift zahlen"],
    ["Beitrag bisher per Lastschrift", "Set up a standing order for the monthly fee"],
    ["Miete per Lastschrift", "Richten Sie einen Dauerauftrag über 670 € ein"],
  ])("%s / %s asks for a transfer", (title, action) => {
    expect(asksForTransfer(action)).toBe(true);
    expect(isDirectDebit(todo(title, action))).toBe(false);
    expect(isTransfer({ ...todo(title, action), direction: "out" })).toBe(true);
  });

  // one the person is told to cancel, stop or delete — the payee now collects — is no transfer
  it.each([
    ["Monthly rent collected by direct debit", "Cancel your standing order: the rent is now debited."],
    ["Miete per Lastschrift", "Dauerauftrag löschen – die Miete wird ab November abgebucht."],
    ["Beitrag per Lastschrift", "Bitte kündigen Sie Ihren Dauerauftrag."],
    ["Beitrag per Lastschrift", "Bitte stellen Sie Ihren Dauerauftrag ein."],
    ["Beitrag per Lastschrift", "Dauerauftrag einstellen"],
    ["Fee collected by direct debit", "Stop your standing order; you no longer need it."],
    ["Monatsbeitrag per Bankeinzug", "Ihren Dauerauftrag brauchen Sie nicht mehr."],
  ])("%s / %s stays a direct debit", (title, action) => {
    expect(asksForTransfer(action)).toBe(false);
    expect(isDirectDebit(todo(title, action))).toBe(true);
  });

  it.each([
    ["Pay the returned direct debit plus the €3 fee", null],
    ["Rücklastschriftgebühr 3,00 € bezahlen", null],
    ["Rundfunkbeitrag: direct debit failed", "Pay 55.08 € by 15.10.2026"],
    ["Rücklastschrift Rundfunkbeitrag", "Pay 55.08 € if you haven't yet"],
  ])("%s / %s says its debit failed as a fact", (title, action) => {
    expect(isDirectDebit(todo(title, action))).toBe(false);
  });

  // a warning of what a returned debit costs is stock wording on a direct-debit bill; "returned"
  // without a debit beside it is anything returned
  it.each([
    ["Monthly fee €49.90 collected by direct debit", "Keep the account covered; a returned debit (Rücklastschrift) costs €3."],
    ["Rechnung Oktober 49,99 € per Lastschrift", "Collected by SEPA direct debit on 15 Oct; a returned debit costs €3."],
    ["Beitrag per Lastschrift", "Bei Rücklastschrift berechnen wir 3,00 € Gebühr."],
    ["Beitrag per Lastschrift", "Sollte die Lastschrift nicht eingelöst werden, fallen Gebühren an."],
    ["Beitrag per Lastschrift", "Im Falle einer Rücklastschrift tragen Sie die Kosten."],
    ["Beitrag per Lastschrift", "If the debit is returned, the bank charges a fee."],
    ["Router rental collected by direct debit", "The router must be returned within 14 days."],
    ["Leihgerät per Lastschrift", "Das Gerät muss zurückgegeben werden."],
  ])("%s / %s stays a direct debit", (title, description) => {
    expect(isDirectDebit({ kind: "payment", title, action: null, description })).toBe(true);
  });
});

describe("paymentReference", () => {
  it.each([
    ["Kassenzeichen 5126 0184 5122", "5126 0184 5122"],
    ["Kassenzeichen: 5126 0184-5122", "5126 0184-5122"],
    ["Aktenzeichen OA/VW/2026/55012", "OA/VW/2026/55012"],
    ["Az. 5 C 123/26", "5 C 123/26"],
    ["Rechnung Nr. R-2026-0815", "R-2026-0815"],
    ["Rechnungsnr.: 0815", "0815"],
    ["Kunden-Nr. 4711", "4711"],
    ["Verwendungszweck: Kundennummer 12345", "12345"],
    ["Beitragsnummer 457 812 309", "457 812 309"],
    ["Reference RF18 5390 0754 7034", "RF18 5390 0754 7034"],
    ["Invoice no. 2026-17", "2026-17"],
    ["MV-2025-0412 NK 2025", "MV-2025-0412 NK 2025"],
    ["AZ-2026-12", "AZ-2026-12"],
    ["Kassenzeichen", "Kassenzeichen"],
    ["Referenz: ABC", "Referenz: ABC"],
    ["  457 812 309 ", "457 812 309"],
  ])("%s → %s", (reference, typed) => {
    expect(paymentReference(reference)).toBe(typed);
  });
});
