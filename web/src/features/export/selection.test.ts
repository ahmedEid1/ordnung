import { describe, expect, it } from "vitest";
import type { Document } from "@/api/types";
import { makeDoc } from "@/features/document/fixtures";
import CASES from "./selection-cases.json";
import { earlyUntil, exportQuery, letterDay, letterYear, matchesChoice, parseDay, selectForExport, zipName, type ExportChoice } from "./selection";

/** A letter of the shared table: no dates, no sender, processed — unless the case says otherwise. */
const shared = (fields: Partial<Document>): Document => makeDoc({ doc_date: null, received_date: null, party_id: null, ...fields });
const DOCS = (CASES.docs as Partial<Document>[]).map(shared);

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
