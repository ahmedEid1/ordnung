import { describe, expect, it } from "vitest";
import {
  AREA_COPY,
  CONTRACT_CATEGORY_COPY,
  DOCUMENT_KIND_COPY,
  ENUM_COVERAGE,
  GROUNDING_COPY,
  PARTY_KIND_COPY,
  PIPELINE_STEPS,
  TONES,
  assertNoRawEnums,
  copyFor,
  documentKindLabel,
  findRawEnums,
  splitRecordIds,
  humanize,
  stageToStep,
} from "./copy";
import { GLOSSARY_TERMS, lookupTerm, termWithTranslation } from "./glossary";

describe("enum copy", () => {
  it.each(ENUM_COVERAGE)("$name: every value has a human label, icon and tone", ({ values, map }) => {
    for (const v of values) {
      const c = map[v];
      expect(c, `${v} is missing`).toBeDefined();
      expect(c!.label.trim().length).toBeGreaterThan(0);
      expect(c!.label).not.toBe(v); // never the raw value
      expect(c!.label).not.toMatch(/_/);
      expect(c!.icon).toBeTruthy();
      expect(TONES[c!.tone]).toBeDefined();
      expect(() => assertNoRawEnums(c!.label, { exactWord: true })).not.toThrow();
    }
  });

  it.each([
    ["letter kinds", DOCUMENT_KIND_COPY],
    ["life areas", AREA_COPY],
    ["organisations", PARTY_KIND_COPY],
    ["contract categories", CONTRACT_CATEGORY_COPY],
  ] as const)("%s are categories, not alarms: no danger, warn or deadline tone", (_, map) => {
    for (const [value, c] of Object.entries(map)) expect(["danger", "warn", "deadline"], value).not.toContain(c.tone);
  });

  it("gives fines and payment reminders the payment tone, and health the appointment tone", () => {
    expect(DOCUMENT_KIND_COPY.fine.tone).toBe("payment");
    expect(DOCUMENT_KIND_COPY.dunning.tone).toBe("payment");
    expect(AREA_COPY.health.tone).toBe("appointment");
    expect(PARTY_KIND_COPY.health_insurer.tone).toBe("appointment");
  });

  it("uses the SPEC §21 trust wording", () => {
    expect(GROUNDING_COPY.verified.label).toBe("Found in the letter");
    expect(GROUNDING_COPY.model_read.label).toBe("Read by AI from the photo");
    expect(GROUNDING_COPY.unverified.label).toBe("Couldn't find this — please check");
    expect(Object.values(GROUNDING_COPY).map((c) => c.label.toLowerCase())).not.toContain("verified");
  });

  it("falls back to humanised text for unknown values", () => {
    expect(humanize("needs_review")).toBe("Needs review");
    expect(copyFor(GROUNDING_COPY, "brand_new_value").label).toBe("Brand new value");
    expect(documentKindLabel(null)).toBe("Other");
    expect(documentKindLabel("tax_assessment")).toBe("Tax assessment");
  });

  it("maps pipeline stages onto the 5-step stepper", () => {
    expect(PIPELINE_STEPS.map((s) => s.label)).toEqual(["Reading", "Understanding", "Checking", "Computing dates", "Filing"]);
    expect(stageToStep("intake")).toBe(0);
    expect(stageToStep("transcribe")).toBe(0);
    expect(stageToStep("extract")).toBe(1);
    expect(stageToStep("verify")).toBe(2);
    expect(stageToStep("compute")).toBe(3);
    expect(stageToStep("plan")).toBe(4);
    expect(stageToStep("done")).toBe(5);
    expect(stageToStep("mystery")).toBe(0);
    expect(stageToStep(null)).toBe(0);
  });
});

describe("assertNoRawEnums", () => {
  it("flags snake_case enum values and regime codes", () => {
    expect(findRawEnums("Status: needs_review")).toEqual(["needs_review"]);
    expect(findRawEnums("tax_assessment and bgb309_new")).toEqual(["tax_assessment", "bgb309_new"]);
    expect(() => assertNoRawEnums("This letter is a tax_assessment")).toThrow(/tax_assessment/);
  });

  it("flags ledger record ids, which must be shown as titles", () => {
    const text = "doc_0b2t88kqsf2n describes the fee increase for ctr_611d1sk7v1cr";
    expect(findRawEnums(text)).toEqual(["doc_0b2t88kqsf2n", "ctr_611d1sk7v1cr"]);
    expect(splitRecordIds(text)).toEqual([
      { kind: "id", id: "doc_0b2t88kqsf2n", prefix: "doc" },
      { kind: "text", text: " describes the fee increase for " },
      { kind: "id", id: "ctr_611d1sk7v1cr", prefix: "ctr" },
    ]);
    expect(findRawEnums("Transfer to doc_ok please")).toEqual([]);
  });

  it("accepts normal prose that happens to contain enum words", () => {
    expect(() => assertNoRawEnums("Your deadline for the payment is Friday")).not.toThrow();
    expect(() => assertNoRawEnums("Please check · Found in the letter · p.2")).not.toThrow();
    expect(() => assertNoRawEnums("snake_case_but_not_an_enum")).not.toThrow();
  });

  it("with exactWord, flags a bare lowercase enum word", () => {
    expect(() => assertNoRawEnums("deadline", { exactWord: true })).toThrow();
    expect(() => assertNoRawEnums("Deadline", { exactWord: true })).not.toThrow();
  });
});

describe("glossary", () => {
  const required = [
    "Einspruch",
    "Widerspruch",
    "Bescheid",
    "Bekanntgabe",
    "Frist",
    "Kündigung",
    "Mahnung",
    "Rechtsbehelfsbelehrung",
    "Aktenzeichen",
    "Nebenkostenabrechnung",
    "Abschlag",
    "Sonderkündigungsrecht",
    "Aufenthaltstitel",
    "Fiktionsbescheinigung",
    "Rundfunkbeitrag",
    "Semesterbeitrag",
    "Werkstudent",
    "Verwarnungsgeld",
    "Einschreiben",
  ];

  it.each(required)("explains %s in one English line", (term) => {
    const e = lookupTerm(term);
    expect(e).toBeDefined();
    expect(e!.translation.length).toBeGreaterThan(2);
    expect(e!.explanation.length).toBeGreaterThan(20);
    expect(e!.explanation).not.toMatch(/\n/);
  });

  it("writes money the app's English way in the explanations (€18.36, never 18,36 €)", () => {
    for (const e of GLOSSARY_TERMS) expect(e.explanation, e.term).not.toMatch(/\d\s*(€|EUR\b|Euro\b)/);
    expect(lookupTerm("Rundfunkbeitrag")!.explanation).toContain("€18.36 per month");
  });

  it("formats 'Einspruch (objection)' and is case-insensitive", () => {
    expect(termWithTranslation("einspruch")).toBe("Einspruch (objection)");
    expect(termWithTranslation("Unbekannt")).toBe("Unbekannt");
    expect(GLOSSARY_TERMS.length).toBeGreaterThanOrEqual(required.length);
  });
});
