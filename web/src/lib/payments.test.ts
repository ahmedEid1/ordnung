/**
 * `payments.ts` mirrors `ordnung/payments.py` (tests/test_payments.py has the same cases): a to-do
 * naming a direct debit in German or English, and the reference to type without its label.
 */
import { describe, expect, it } from "vitest";
import { isDirectDebit, paymentReference } from "./payments";

const todo = (title: string, action: string | null = null) => ({ kind: "payment" as const, title, action, description: null });

describe("isDirectDebit", () => {
  it.each([
    ["Monthly fee", "Collected by direct debit"],
    ["Monatsbeitrag", "Wird per Bankeinzug eingezogen"],
    ["Jahresbeitrag", "Will be debited from your account"],
    ["Beitrag (Mandatsreferenz M-4711)", null],
    ["Monatliche Abbuchung Deutschlandticket", null],
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
