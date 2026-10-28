import { describe, expect, it } from "vitest";
import type { DocumentRow } from "@/api/types";
import { makeRow } from "@/features/document/fixtures";
import CASES from "./selection-cases.json";
import { earlyUntil, exportQuery, forTaxes, letterDay, letterYear, matchesChoice, parseDay, selectForExport, zipName, type ExportChoice } from "./selection";

/** A letter of the shared table as the list gives it: no dates, no sender, processed, no choice of the person's — unless the case says otherwise. */
const shared = (fields: Partial<DocumentRow>): DocumentRow => makeRow({ doc_date: null, received_date: null, party_id: null, ...fields });
const DOCS = (CASES.docs as Partial<DocumentRow>[]).map(shared);

describe("selectForExport", () => {
  it("takes the letters the server puts in the ZIP, for every case the server's test reads too", () => {
    expect(CASES.cases.length).toBeGreaterThan(5);
    for (const c of CASES.cases) {
      expect(
        selectForExport(DOCS, c.choice as ExportChoice).map((d) => d.id),
        c.name,
      ).toEqual(c.expected_ids);
    }
  });

  it("counts the letters the person marked or unmarked for taxes as the server does (their choice over Claude's mark)", () => {
    const choices = Object.fromEntries(DOCS.filter((d) => d.tax_choice != null).map((d) => [d.id, d.tax_choice]));
    expect(choices).toEqual({ doc_private_marked_2025: true, doc_unmarked_2025: false, doc_held_marked: true });
    const forTaxesIds = selectForExport(DOCS, { tax: true }).map((d) => d.id);
    // a private letter the person marked counts; one Claude marked that they took off doesn't; a waiting one never goes
    expect(forTaxesIds).toContain("doc_private_marked_2025");
    expect(forTaxesIds).not.toContain("doc_unmarked_2025");
    expect(forTaxesIds).not.toContain("doc_held_marked");
    expect(forTaxes(DOCS.find((d) => d.id === "doc_unmarked_2025")!)).toBe(false);
  });

  it("names the ZIP as the server does", () => {
    for (const c of CASES.cases) expect(zipName(c.choice as ExportChoice, CASES.today), c.name).toBe(c.expected_name);
  });

  it("ignores until without a year", () => {
    const june = shared({ id: "june", doc_date: "2026-06-01" });
    expect(matchesChoice(june, { until: "2026-05-31" })).toBe(true);
    expect(matchesChoice(june, { year: 2025, until: "2026-05-31" })).toBe(false);
  });
});

describe("letterDay", () => {
  it("is the date on the letter, else the day it arrived — a date that can't be is no date", () => {
    expect(letterDay({ doc_date: "2025-03-14", received_date: "2025-03-17" })).toBe("2025-03-14");
    expect(letterDay({ doc_date: null, received_date: "2025-03-17" })).toBe("2025-03-17");
    expect(letterDay({ doc_date: "2025-02-30", received_date: "2025-03-17" })).toBe("2025-03-17");
    expect(letterDay({ doc_date: "14.03.2025", received_date: null })).toBeNull();
    expect(letterYear({ doc_date: "2025-12-31T23:00:00Z", received_date: null })).toBe(2025);
    expect(letterYear({ doc_date: null, received_date: null })).toBeNull();
  });

  it("reads a real day only", () => {
    expect(parseDay("2024-02-29")).toBe("2024-02-29");
    expect(parseDay("2025-02-29")).toBeNull();
    expect(parseDay("2025-13-01")).toBeNull();
    expect(parseDay("")).toBeNull();
    expect(parseDay(undefined)).toBeNull();
  });
});

describe("exportQuery", () => {
  it("carries only what narrows the export", () => {
    expect(exportQuery({})).toEqual({});
    expect(exportQuery({ year: 2025, until: earlyUntil(2025), tax: true, party_id: "pty_a" })).toEqual({
      year: 2025,
      until: "2026-05-31",
      tax: true,
      party_id: "pty_a",
    });
    // until goes with a year; tax only when on; no sender is every sender
    expect(exportQuery({ until: "2026-05-31", tax: false, party_id: null })).toEqual({});
    expect(exportQuery({ year: 2024, until: null, party_id: "" })).toEqual({ year: 2024 });
  });
});
