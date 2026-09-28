import { describe, expect, it } from "vitest";
import { DOMESTIC_NOTE, NOT_A_NUMBER, NOT_REGISTERED, ONLINE_STAMP_NOTE, WRONG_CHECK_DIGIT, asciiDigits, checkTracking, displayTracking, normaliseTracking, s10CheckDigit, trackingComplete } from "./tracking";

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
    expect(checkTracking("rt 123 456 785 de")).toEqual({ state: "valid", number: "RT123456785DE", display: "RT 123 456 785 DE", format: "s10", checked: true, note: null });
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

  it("keeps the number of an online stamp (Internetmarke) unchecked with a note, as tests/test_tracking.py", () => {
    for (const typed of ["A0 0123 45D6 0000 123C EC", "a0012345d60000123cec", "A0-0123-45D6-0000-123C-EC"]) {
      expect(checkTracking(typed)).toEqual({
        state: "valid",
        number: "A0012345D60000123CEC",
        display: "A0 0123 45D6 0000 123C EC",
        format: "online_stamp",
        checked: false,
        note: ONLINE_STAMP_NOTE,
      });
    }
    for (const text of ["A0012345D60000123CE", "A0012345D60000123CEC0", "G0012345D60000123CEC"]) {
      expect(checkTracking(text)).toEqual({ state: "invalid", message: NOT_A_NUMBER });
    }
    expect(NOT_A_NUMBER).toContain("20 characters next to the square code");
    expect(NOT_A_NUMBER).not.toContain("12 digits");
  });

  it("calls a number complete (a mistake is said while typing) only when it can't still become one", () => {
    expect(trackingComplete("RT 123 456 78")).toBe(false);
    expect(trackingComplete("RT 123 456 784 DE")).toBe(true); // 13 characters of an S10 number
    expect(trackingComplete("A0 0123 45D6 0000 12")).toBe(false); // an online stamp's, 18 of 20
    expect(trackingComplete("A0 0123 45D6 0000 123C EC")).toBe(true);
    expect(trackingComplete("1234567890123")).toBe(false); // digits only could still be a stamp's
    expect(trackingComplete("HELLO WORLD HELLO")).toBe(true);
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
