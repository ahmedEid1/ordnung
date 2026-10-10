import { describe, expect, it } from "vitest";
import type { Document } from "@/api/types";
import { makeDoc } from "@/features/document/fixtures";
import {
  TAX_SEASON_SENTENCE,
  defaultTaxYear,
  earlyStatements,
  groupByKind,
  inTaxSeason,
  parseTaxYear,
  taxGroups,
  taxLetters,
  taxYears,
  undatedTaxLetters,
} from "./taxYear";

const tax = (id: string, fields: Partial<Document> = {}): Document =>
  makeDoc({ id, tax_relevant: true, doc_date: null, received_date: null, created_at: `2026-01-01T00:00:${id.length}Z`, ...fields });

const DOCS: Document[] = [
  tax("payslip_mar", { kind: "payslip", doc_date: "2025-03-31" }),
  tax("payslip_jan", { kind: "payslip", doc_date: "2025-01-31" }),
  tax("insurance", { kind: "insurance", received_date: "2025-11-02" }),
  tax("statement", { kind: "payslip", doc_date: "2026-02-10" }),
  tax("may", { kind: "bank_letter", doc_date: "2026-05-31" }),
  tax("june", { kind: "bank_letter", doc_date: "2026-06-01" }),
  tax("undated", { kind: "receipt", title: "Laptop receipt" }),
  tax("held", { doc_date: "2025-05-05", status: "held", ai_private: true }),
  tax("trashed", { doc_date: "2025-05-06", deleted_at: "2026-01-01T00:00:00Z" }),
  makeDoc({ id: "rent", tax_relevant: false, doc_date: "2025-04-01" }),
];

describe("taxLetters and taxYears", () => {
  it("lists a year's letters for taxes by the letter's date, else the day it arrived", () => {
    expect(taxLetters(DOCS, 2025).map((d) => d.id)).toEqual(["payslip_mar", "payslip_jan", "insurance"]);
    expect(taxLetters(DOCS, 2026).map((d) => d.id)).toEqual(["statement", "may", "june"]);
    expect(taxLetters(DOCS, 2024)).toEqual([]);
  });

  it("offers only the years that have letters for taxes, newest first, with their counts", () => {
    expect(taxYears(DOCS)).toEqual([
      { year: 2026, count: 3 },
      { year: 2025, count: 3 },
    ]);
    expect(taxYears([])).toEqual([]);
  });

  it("keeps undated letters out of every year and names them apart", () => {
    expect(undatedTaxLetters(DOCS).map((d) => d.id)).toEqual(["undated"]);
  });
});

describe("defaultTaxYear", () => {
  it("is last year during the tax season (January–July), when it has letters", () => {
    expect(defaultTaxYear("2026-03-01", [2026, 2025])).toBe(2025);
    expect(defaultTaxYear("2026-07-31", [2026, 2025])).toBe(2025);
  });

  it("is this year after July, or when last year has none", () => {
    expect(defaultTaxYear("2026-09-28", [2026, 2025])).toBe(2026);
    expect(defaultTaxYear("2026-03-01", [2026, 2023])).toBe(2026);
  });

  it("is the newest year with letters when neither has any, and nothing without letters", () => {
    expect(defaultTaxYear("2026-09-28", [2023, 2021])).toBe(2023);
    expect(defaultTaxYear("2026-09-28", [])).toBeNull();
  });
});

describe("inTaxSeason", () => {
  it("is true only while the tax Idea would be live for that year", () => {
    expect(inTaxSeason("2026-03-01", 2025)).toBe(true);
    expect(inTaxSeason("2026-08-01", 2025)).toBe(false);
    expect(inTaxSeason("2026-03-01", 2024)).toBe(false);
    expect(TAX_SEASON_SENTENCE).toBe(
      "If you have to file a return it is usually due by the end of July; filing voluntarily is possible for four years and often brings money back.",
    );
  });
});

describe("earlyStatements", () => {
  it("are the next year's letters for taxes dated January to May, once that year has begun", () => {
    expect(earlyStatements(DOCS, 2025, "2026-09-28").map((d) => d.id)).toEqual(["statement", "may"]);
    expect(earlyStatements(DOCS, 2025, "2025-12-31")).toEqual([]);
    expect(earlyStatements(DOCS, 2026, "2026-09-28")).toEqual([]);
  });
});

describe("groupByKind and taxGroups", () => {
  it("makes one group per kind in label order, oldest letter first", () => {
    const groups = groupByKind(taxLetters(DOCS, 2025));
    expect(groups.map((g) => [g.label, g.docs.map((d) => d.id)])).toEqual([
      ["Insurance", ["insurance"]],
      ["Payslip", ["payslip_jan", "payslip_mar"]],
    ]);
  });

  it("ends with the next year's early letters in a group of their own", () => {
    const groups = taxGroups(DOCS, 2025, "2026-09-28");
    expect(groups.map((g) => g.label)).toEqual(["Insurance", "Payslip", "Dated January–May 2026"]);
    expect(groups.at(-1)!.docs.map((d) => d.id)).toEqual(["statement", "may"]);
    expect(new Set(groups.map((g) => g.key)).size).toBe(groups.length);
  });
});

describe("parseTaxYear", () => {
  it("reads a four-digit year the export accepts", () => {
    expect(parseTaxYear("2025")).toBe(2025);
    expect(parseTaxYear("1899")).toBeNull();
    expect(parseTaxYear("25")).toBeNull();
    expect(parseTaxYear("2025x")).toBeNull();
    expect(parseTaxYear(null)).toBeNull();
  });
});
