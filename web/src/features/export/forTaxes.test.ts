/**
 * "For taxes" on any letter (D3 contract): one helper decides whether a letter counts for taxes — the person's
 * own choice if they made one, else Claude's mark (`secretary.tax_choice.for_taxes` on the server) — and the
 * Tax year page, the export's count and the Inbox read years with one parser.
 */
import { describe, expect, it } from "vitest";
import { makeDoc, makeRow } from "@/features/document/fixtures";
import { isTaxLetter, parseTaxYear, taxLetters } from "@/features/taxes/taxYear";
import { forTaxes, matchesChoice, parseYear } from "./selection";

describe("forTaxes", () => {
  it("is the person's choice, else Claude's mark", () => {
    expect(forTaxes({ tax_relevant: false, tax_choice: null })).toBe(false);
    expect(forTaxes({ tax_relevant: true, tax_choice: null })).toBe(true);
    expect(forTaxes({ tax_relevant: false, tax_choice: true })).toBe(true);
    expect(forTaxes({ tax_relevant: true, tax_choice: false })).toBe(false);
    // a full letter (no choice field at all) goes by Claude's mark
    expect(forTaxes(makeDoc({ tax_relevant: true }))).toBe(true);
  });

  it("decides the export's Only letters for taxes and the Tax year page", () => {
    const marked = makeRow({ id: "doc_marked", doc_date: "2025-03-01", tax_relevant: false, tax_choice: true });
    const unmarked = makeRow({ id: "doc_unmarked", doc_date: "2025-04-01", tax_relevant: true, tax_choice: false });
    const claudes = makeRow({ id: "doc_claudes", doc_date: "2025-05-01", tax_relevant: true });
    expect(claudes.tax_choice).toBeNull();
    const docs = [marked, unmarked, claudes];
    expect(docs.filter((d) => matchesChoice(d, { tax: true })).map((d) => d.id)).toEqual(["doc_marked", "doc_claudes"]);
    expect(docs.filter(isTaxLetter).map((d) => d.id)).toEqual(["doc_marked", "doc_claudes"]);
    expect(taxLetters(docs, 2025).map((d) => d.id)).toEqual(["doc_marked", "doc_claudes"]);
    // a letter waiting from the folder never counts, whatever the choice
    expect(isTaxLetter(makeRow({ status: "held", tax_choice: true }))).toBe(false);
  });
});

describe("parseYear", () => {
  it("reads four digits from 1900 to 2100", () => {
    expect(parseYear("2025")).toBe(2025);
    expect(parseYear("1900")).toBe(1900);
    expect(parseYear("2100")).toBe(2100);
    for (const bad of ["1899", "2101", "25", "2025x", " 2025", "", null]) expect(parseYear(bad)).toBeNull();
    expect(parseTaxYear).toBe(parseYear);
  });
});
