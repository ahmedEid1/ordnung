/** First-run wizard logic (pure, tested in `wizard.test.ts`). */
import type { ClaudeStatus, OnboardingRequest, Profile } from "@/api/types";
import { BUNDESLAENDER, LANGUAGES } from "./options";

export const WIZARD_STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "region", label: "Where you live" },
  { id: "address", label: "Your name & address" },
  { id: "claude", label: "Claude check" },
] as const;

/** Index of the "you're all set — add your first letters" screen after the four steps. */
export const DONE_STEP = WIZARD_STEPS.length;

export interface OnboardingDraft {
  /** Bundesland code ("NW"); empty until chosen */
  region: string;
  language: string;
  /** null = not answered */
  isStudentVisa: boolean | null;
  name: string;
  address: string;
}

/** Start values: the person's language/name/address if already known; the state must be chosen. */
export function initialDraft(profile?: Partial<Profile> | null): OnboardingDraft {
  const lang = LANGUAGES.some((l) => l.code === profile?.language) ? profile!.language! : "en";
  const known = profile?.onboarded && BUNDESLAENDER.some((b) => b.code === profile.region);
  return {
    region: known ? profile!.region! : "",
    language: lang,
    isStudentVisa: profile?.onboarded ? Boolean(profile.is_student_visa) : null,
    name: profile?.name ?? "",
    address: profile?.address ?? "",
  };
}

/** Can the person continue from `step`? (Only the state is required — it decides holidays.) */
export function canContinue(step: number, draft: OnboardingDraft): boolean {
  if (step === 1) return BUNDESLAENDER.some((b) => b.code === draft.region);
  return true;
}

/**
 * The `POST /api/onboarding` body. Empty name/address are left out (so "Skip for now" never
 * overwrites what is stored); an unanswered permit question counts as "no".
 */
export function buildOnboardingRequest(draft: OnboardingDraft, opts: { skipAi?: boolean } = {}): OnboardingRequest {
  const profile: Partial<Profile> = {
    region: draft.region,
    language: draft.language,
    country: "DE",
    is_student_visa: draft.isStudentVisa ?? false,
  };
  const name = draft.name.trim().replace(/\s+/g, " ");
  const address = draft.address
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
  if (name) profile.name = name;
  if (address) profile.address = address;
  return opts.skipAi ? { profile, skip_ai: true } : { profile };
}

/** One-line return address as printed above the window of a German letter. */
export function returnLine(name: string, address: string): string {
  return [name.trim(), ...address.split("\n").map((l) => l.trim())].filter(Boolean).join(" · ");
}

export type ClaudeState = "ready" | "unchecked" | "signed_out" | "missing";

/** What the Claude check shows: ready · installed but not probed · not signed in · not installed. */
export function claudeState(c: ClaudeStatus | null | undefined): ClaudeState {
  if (!c || !c.installed) return "missing";
  if (c.ok === true) return "ready";
  if (c.ok === false) return "signed_out";
  return "unchecked";
}
