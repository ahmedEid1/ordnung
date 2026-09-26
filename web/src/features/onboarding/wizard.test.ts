import { describe, expect, it } from "vitest";
import { BUNDESLAENDER, LANGUAGES, PRIVACY_STATEMENT } from "./options";
import { buildOnboardingRequest, canContinue, claudeState, initialDraft, returnLine, type OnboardingDraft } from "./wizard";

const draft = (p: Partial<OnboardingDraft> = {}): OnboardingDraft => ({ ...initialDraft(), ...p });

describe("onboarding options", () => {
  it("lists all 16 Bundesländer with their codes", () => {
    expect(BUNDESLAENDER.map((b) => b.code)).toEqual(["BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH"]);
  });

  it("offers the seven languages in their own names", () => {
    expect(LANGUAGES.map((l) => l.label)).toEqual(["English", "Deutsch", "العربية", "Türkçe", "Українська", "Español", "Français"]);
  });

  it("uses the honest privacy wording from the spec", () => {
    expect(PRIVACY_STATEMENT).toMatch(/^Your files and your database stay on this computer\./);
    expect(PRIVACY_STATEMENT).toContain("no server, no telemetry and never sees your credentials");
  });
});

describe("wizard", () => {
  it("requires a state before leaving the region step", () => {
    expect(canContinue(1, draft())).toBe(false);
    expect(canContinue(1, draft({ region: "XX" }))).toBe(false);
    expect(canContinue(1, draft({ region: "BY" }))).toBe(true);
    expect(canContinue(2, draft())).toBe(true); // name & address are optional
  });

  it("does not preselect a state for first-run profiles (the default is not a choice)", () => {
    expect(initialDraft({ region: "NW", onboarded: false, language: "de" })).toMatchObject({ region: "", language: "de", isStudentVisa: null });
    expect(initialDraft({ region: "BE", onboarded: true, is_student_visa: true })).toMatchObject({ region: "BE", isStudentVisa: true });
  });

  it("builds the onboarding request, leaving out skipped fields", () => {
    expect(buildOnboardingRequest(draft({ region: "NW" }))).toEqual({
      profile: { region: "NW", language: "en", country: "DE", is_student_visa: false },
    });
    const full = buildOnboardingRequest(draft({ region: "HH", language: "tr", isStudentVisa: true, name: "  Sam   Rivera ", address: " Musterweg 12 \n\n 12345 Musterstadt " }), { skipAi: true });
    expect(full).toEqual({
      profile: { region: "HH", language: "tr", country: "DE", is_student_visa: true, name: "Sam Rivera", address: "Musterweg 12\n12345 Musterstadt" },
      skip_ai: true,
    });
  });

  it("formats the return line of a letter", () => {
    expect(returnLine("Sam Rivera", "Musterweg 12\n12345 Musterstadt")).toBe("Sam Rivera · Musterweg 12 · 12345 Musterstadt");
    expect(returnLine("", "")).toBe("");
  });

  it("maps the Claude status to what the check shows", () => {
    const base = { version: null, path: null, detail: null };
    expect(claudeState(undefined)).toBe("missing");
    expect(claudeState({ ...base, installed: false, ok: null })).toBe("missing");
    expect(claudeState({ ...base, installed: true, ok: true })).toBe("ready");
    expect(claudeState({ ...base, installed: true, ok: false })).toBe("signed_out");
    expect(claudeState({ ...base, installed: true, ok: null })).toBe("unchecked");
  });
});
