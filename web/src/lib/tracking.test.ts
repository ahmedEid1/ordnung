import { describe, expect, it } from "vitest";
import { DOMESTIC_NOTE, NOT_REGISTERED, WRONG_CHECK_DIGIT, asciiDigits, checkTracking, displayTracking, normaliseTracking, s10CheckDigit } from "./tracking";

describe("tracking numbers (the server's policy, checked while typing)", () => {
  it("computes the S10 check digit like the server's worked examples", () => {
    // tests/test_tracking.py uses the same rows
    expect(s10CheckDigit("12345678")).toBe(5);
    expect(s10CheckDigit("47312482")).toBe(9);
    expect(s10CheckDigit("00300000")).toBe(0); // remainder 1: 10 → 0
    expect(s10CheckDigit("00000000")).toBe(5); // remainder 0: 11 → 5
    expect(s10CheckDigit("01000000")).toBe(5); // remainder 6 also gives 5
    expect(() => s10CheckDigit("1234567")).toThrow();
  });

  it("accepts every serial with exactly one check digit", () => {
    for (let n = 0; n < 2000; n += 7) {
      const serial = String(n * 4999).padStart(8, "0").slice(-8);
      const valid = [...Array(10).keys()].filter((d) => checkTracking(`RT${serial}${d}DE`).state === "valid");
      expect(valid).toEqual([s10CheckDigit(serial)]);
    }
  });

  it("reads spacing and case the same way", () => {
    expect(normaliseTracking(" rt 123-456.785/de ")).toBe("RT123456785DE");
    expect(checkTracking("rt 123 456 785 de")).toEqual({ state: "valid", number: "RT123456785DE", display: "RT 123 456 785 DE", checked: true, note: null });
    expect(displayTracking("003404341234")).toBe("0034 0434 1234");
  });

  it("refuses a mistyped check digit and swapped digits", () => {
    expect(checkTracking("RT123456784DE")).toEqual({ state: "invalid", message: WRONG_CHECK_DIGIT });
    expect(checkTracking("RT213456785DE")).toEqual({ state: "invalid", message: WRONG_CHECK_DIGIT });
  });

  it("keeps unregistered and twelve-digit numbers with a note", () => {
    expect(checkTracking("LX123456785DE")).toMatchObject({ state: "valid", checked: true, note: NOT_REGISTERED });
    expect(checkTracking("0034 0434 1234")).toMatchObject({ state: "valid", checked: false, note: DOMESTIC_NOTE, display: "0034 0434 1234" });
  });

  it("refuses everything else with what a number looks like", () => {
    expect(checkTracking("RT12345678DE")).toMatchObject({ state: "invalid", message: expect.stringContaining("this one has 8 digits") });
    for (const text of ["hello", "12345678901", "1234567890123", "R".repeat(100)]) {
      expect(checkTracking(text)).toMatchObject({ state: "invalid", message: expect.stringContaining("doesn't look like a tracking number") });
    }
    expect(checkTracking("   ")).toEqual({ state: "empty" });
  });

  it("reads other digits as the server does and keeps only ASCII (tests/test_tracking.py has the same rows)", () => {
    const rows: [string, string][] = [
      ["RR１２３４５６７８５DE", "RR123456785DE"], // full-width digits
      ["ＲＲ１２３４５６７８５ＤＥ", "RR123456785DE"], // full-width letters too
      ["RR١٢٣٤٥٦٧٨٥DE", "RR123456785DE"], // Arabic-Indic digits
      ["RR۱۲۳۴۵۶۷۸۵DE", "RR123456785DE"], // Eastern Arabic-Indic (Persian)
      ["RR १२३ ४५६ ७८५ DE", "RR123456785DE"], // Devanagari, spaced
      ["１２３４５６７８９０１２", "123456789012"],
      ["٠٠٣٤ ٠٤٣٤ ١٢٣٤", "003404341234"],
    ];
    for (const [typed, number] of rows) {
      const check = checkTracking(typed);
      expect(check).toMatchObject({ state: "valid", number });
      expect(check.state === "valid" && /^[ -~]+$/.test(check.number)).toBe(true);
    }
    expect(checkTracking("RR١٢٣٤٥٦٧٨٤DE")).toEqual({ state: "invalid", message: WRONG_CHECK_DIGIT });
    expect(checkTracking("РТ123456785DE").state).toBe("invalid"); // Cyrillic letters only look Latin
    expect(asciiDigits("٠١٢٣٤٥٦٧٨٩")).toBe("0123456789");
  });
});
