import { describe, expect, it } from "vitest";
import { BUNDESLAENDER, LANGUAGES, PRIVACY_STATEMENT } from "./options";
import {
  DONE_STEP,
  JOIN_LINK,
  JOIN_PATH,
  WIZARD_STEPS,
  addressEmpty,
  buildOnboardingRequest,
  canContinue,
  claudeState,
  claudeUsable,
  claudeView,
  initialDraft,
  returnLine,
  wizardTitle,
  type ClaudeView,
  type OnboardingDraft,
} from "./wizard";

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
    // one name for the program, in words a non-developer knows (UI audit R1-onboarding-6)
    expect(PRIVACY_STATEMENT).toContain("(Claude Code, the Claude program you installed and signed in to)");
    expect(PRIVACY_STATEMENT).not.toMatch(/CLI|Claude app/);
  });
});

describe("wizard", () => {
  it("offers another way in on its first step: bringing over the Ordnung of another computer (hand-off sync)", () => {
    expect(JOIN_LINK).toBe("I already use Ordnung on another computer");
    expect(JOIN_PATH).toBe("/join");
  });

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
    const base = { version: null, path: null, detail: null, needs_version: null };
    expect(claudeState(undefined)).toBe("missing");
    expect(claudeState({ ...base, installed: false, ok: null })).toBe("missing");
    expect(claudeState({ ...base, installed: true, ok: true })).toBe("ready");
    expect(claudeState({ ...base, installed: true, ok: false })).toBe("signed_out");
    expect(claudeState({ ...base, installed: true, ok: null })).toBe("unchecked");
    // older than Ordnung needs: not ready, and not a sign-in problem
    expect(claudeState({ ...base, installed: true, ok: false, version: "2.0.9 (Claude Code)", needs_version: "2.1.0" })).toBe("outdated");
  });

  it("tells a pending or failed health check apart from a missing Claude (UI audit R1-onboarding-6)", () => {
    const ready = { version: "2.1.4 (Claude Code)", path: null, detail: null, needs_version: null, installed: true, ok: true };
    expect(claudeView(undefined, { pending: true, failed: false })).toBe("checking");
    expect(claudeView(undefined, { pending: false, failed: true })).toBe("unknown");
    expect(claudeView(ready, { pending: false, failed: true })).toBe("ready"); // a failed refetch keeps the last answer
    expect(claudeView({ ...ready, installed: false, ok: null }, { pending: false, failed: false })).toBe("missing");
    const views: ClaudeView[] = ["ready", "unchecked", "signed_out", "outdated", "missing", "checking", "unknown"];
    expect(views.filter(claudeUsable)).toEqual(["ready", "unchecked"]);
  });

  it("names every step in the tab title (UI audit R1-onboarding-4)", () => {
    expect(WIZARD_STEPS.map((_, i) => wizardTitle(i))).toEqual([
      "Step 1 of 4: Welcome to Ordnung · Ordnung",
      "Step 2 of 4: Where do you live? · Ordnung",
      "Step 3 of 4: Your name and address · Ordnung",
      "Step 4 of 4: Is Claude ready? · Ordnung",
    ]);
    expect(wizardTitle(0, { revisit: true })).toBe("Step 1 of 4: Change your setup · Ordnung");
    expect(wizardTitle(DONE_STEP)).toBe("Setup complete · Ordnung");
  });

  it("offers “Skip for now” only while nothing is typed (UI audit R1-onboarding-7)", () => {
    expect(addressEmpty(draft())).toBe(true);
    expect(addressEmpty(draft({ name: "  ", address: "\n" }))).toBe(true);
    expect(addressEmpty(draft({ address: "Musterweg 12" }))).toBe(false);
    expect(addressEmpty(draft({ name: "Sam" }))).toBe(false);
  });
});
