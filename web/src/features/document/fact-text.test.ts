import { describe, expect, it } from "vitest";
import { plainText } from "@/lib/glue";
import { bracketed, englishInline, factLabel, factValue, isGermanText, sameNumber, unbrokenNumber } from "./fact-text";

const shown = (value: string) => {
  const v = factValue(value);
  return { text: plainText(v.text), german: v.german };
};

describe("key fact values in the app's format (UI audit round 1)", () => {
  it.each([
    // numbers and units: "1.320 kWh" read as 1.32
    ["1.320 kWh", "1,320 kWh"],
    ["32,90 ct/kWh (brutto)", "32.90 ct/kWh (gross)"],
    ["ca. 48,6 m²", "approx. 48.6 m²"],
    ["92 Tage", "92 days"],
    ["1 Monat", "1 month"],
    // money with an interval
    ["63,00 € pro Monat", "€63.00/month"],
    ["520,00 € monatlich", "€520.00/month"],
    ["11,90 €/Monat (brutto)", "€11.90/month (gross)"],
    // money inside a value
    ["670,00 € (bisher 640,00 €)", "€670.00 (previously €640.00)"],
    ["0.00 € (promotional, normally 39.99 €)", "€0.00 (promotional, normally €39.99)"],
    ["59.90 € on 01.12.2026", "€59.90 on Tue 1 Dec 2026"],
    // dates and periods
    ["01.10.–31.12.2025 (92 Tage)", "1 Oct – 31 Dec 2025 (92 days)"],
    ["01.08.2026 – 31.08.2026", "1 Aug – 31 Aug 2026"],
    ["01.12.2025 – 31.01.2026", "1 Dec 2025 – 31 Jan 2026"],
    ["10.2026 – 12.2026", "Oct – Dec 2026"],
    ["12.09.2026, 14:37–16:05 Uhr", "Sat 12 Sep 2026, 14:37–16:05"],
    // whole values as before
    ["156,55 €", "€156.55"],
    ["30.11.2026", "Mon 30 Nov 2026"],
  ])("%s → %s", (value, text) => {
    expect(shown(value)).toEqual({ text, german: false });
  });

  it("leaves a German sentence German (and says so) and never mixes an English date into it", () => {
    expect(shown("Bis zum 10. eines Monats zum Ende dieses Monats")).toEqual({ text: "Bis zum 10. eines Monats zum Ende dieses Monats", german: true });
    expect(shown("12 Monate ab 15.01.2025")).toEqual({ text: "12 Monate ab 15.01.2025", german: true });
    expect(shown("1.560,00 €, zahlbar in 3 Raten")).toEqual({ text: "€1,560.00, zahlbar in 3 Raten", german: true });
    expect(shown("Pkw, amtliches Kennzeichen MU-CS 482").german).toBe(true);
  });

  it("keeps English values and numbers as they are", () => {
    expect(shown("Parked without a valid parking ticket, duration over 1 up to 2 hours")).toEqual({
      text: "Parked without a valid parking ticket, duration over 1 up to 2 hours",
      german: false,
    });
    expect(shown("R482019375")).toEqual({ text: "R482019375", german: false });
    expect(shown("5")).toEqual({ text: "5", german: false });
    expect(shown("Lithuania (LT)")).toEqual({ text: "Lithuania (LT)", german: false });
    // an impossible date stays as written
    expect(shown("31.02.2026 – 31.03.2026").text).toBe("31.02.2026 – 31.03.2026");
  });
});

describe("key fact labels", () => {
  it("puts the English first and the letter's German in brackets", () => {
    expect(factLabel("Gültig ab")).toEqual({ en: "Valid from", de: "Gültig ab" });
    expect(factLabel("Monatsbeitrag")).toEqual({ en: "Monthly fee", de: "Monatsbeitrag" });
    expect(factLabel("Tatvorwurf")).toEqual({ en: "Alleged offence", de: "Tatvorwurf" });
    expect(factLabel("Festgesetzte Einkommensteuer")).toEqual({ en: "Income tax assessed", de: "Festgesetzte Einkommensteuer" });
    expect(factLabel("Versicherten-Nr.")).toEqual({ en: "Insurance number", de: "Versicherten-Nr." });
    // the model's own translation in brackets
    expect(factLabel("Tatzeit (time of offence)")).toEqual({ en: "Time of offence", de: "Tatzeit" });
    expect(bracketed("Mietsicherheit (Kaution)")).toBe("Mietsicherheit, Kaution");
  });

  it("keeps English labels and flags German ones it can't translate", () => {
    expect(factLabel("Invoice number")).toEqual({ en: "Invoice number", de: null });
    expect(factLabel("BAföG-based assessment basis (Wintersemester 2026/27)")).toEqual({
      en: "BAföG-based assessment basis (Wintersemester 2026/27)",
      de: null,
    });
    expect(factLabel("Neue Gesamtmiete ab 01.11.2026")).toEqual({ en: null, de: "Neue Gesamtmiete ab 01.11.2026" });
    expect(factLabel("Semesterbeitrag Sommersemester 2027")).toEqual({ en: null, de: "Semesterbeitrag Sommersemester 2027" });
  });

  it("tells German from English", () => {
    expect(isGermanText("Kündigungsfrist")).toBe(true);
    expect(isGermanText("Payment IBAN country")).toBe(false);
    expect(isGermanText("Consequence of no consent")).toBe(false);
  });
});

describe("English running text", () => {
  it("writes German dates and money the app's way, also at the end of a sentence", () => {
    expect(plainText(englishInline("It is valid until 30.11.2026. Pay the 100,00 € fee by 14.10.2026, on site."))).toBe(
      "It is valid until Mon 30 Nov 2026. Pay the €100.00 fee by Wed 14 Oct 2026, on site.",
    );
    // a version number is no date
    expect(englishInline("Version 1.30.11.2026")).toBe("Version 1.30.11.2026");
  });
});

describe("a reference breaks before its number, never inside it", () => {
  it("keeps digit groups and hyphens together", () => {
    const shown = unbrokenNumber("Kassenzeichen 5126 0184 5122");
    expect(shown.split(" ")).toHaveLength(2);
    expect(plainText(shown)).toBe("Kassenzeichen 5126 0184 5122");
    expect(unbrokenNumber("TM-2026-0048213")).not.toContain("-");
  });
});

describe("the same number written two ways", () => {
  it("ignores spaces, dots, dashes and case", () => {
    expect(sameNumber("5126 0184 5122", "512601845122")).toBe(true);
    expect(sameNumber("0481 1123 5", "0481-1123-5")).toBe(true);
    expect(sameNumber("X1234567", "x1234567")).toBe(true);
    expect(sameNumber("MV-2025-0412", "MV-2025-0413")).toBe(false);
    expect(sameNumber("", "")).toBe(false);
  });
});
