/** First-run wizard logic (pure, tested in `wizard.test.ts`). */
import type { ClaudeStatus, OnboardingRequest, Profile } from "@/api/types";
import { BUNDESLAENDER, LANGUAGES } from "./options";

/** The four steps: `label` for the progress dots, `heading` is the step's h1 (and the tab title). */
export const WIZARD_STEPS = [
  { id: "welcome", label: "Welcome", heading: "Welcome to Ordnung" },
  { id: "region", label: "Where you live", heading: "Where do you live?" },
  { id: "address", label: "Your name & address", heading: "Your name and address" },
  { id: "claude", label: "Claude check", heading: "Is Claude ready?" },
] as const;

/** Index of the "you're all set — add your first letters" screen after the four steps. */
export const DONE_STEP = WIZARD_STEPS.length;

/** Step 1's other way in (hand-off sync): bring the Ordnung of another computer here instead of setting up a new one. */
export const JOIN_LINK = "I already use Ordnung on another computer";
export const JOIN_PATH = "/join";

/** Step 1's heading when someone who has already set Ordnung up opens the wizard again. */
export const REVISIT_HEADING = "Change your setup";

/** "Step 2 of 4" — the eyebrow above a step's heading. */
export function stepLabel(step: number): string {
  return `Step ${step + 1} of ${WIZARD_STEPS.length}`;
}

/** The browser tab's title: "Step 2 of 4: Where do you live? · Ordnung", then "Setup complete · Ordnung". */
export function wizardTitle(step: number, opts: { revisit?: boolean } = {}): string {
  if (step >= DONE_STEP) return "Setup complete · Ordnung";
  const heading = step === 0 && opts.revisit ? REVISIT_HEADING : WIZARD_STEPS[Math.max(0, step)]!.heading;
  return `${stepLabel(step)}: ${heading} · Ordnung`;
}

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

/** Nothing typed on the name & address step: its button reads "Skip for now" instead of "Continue". */
export function addressEmpty(draft: Pick<OnboardingDraft, "name" | "address">): boolean {
  return !draft.name.trim() && !draft.address.trim();
}

/** Can the person continue from `step`? (Only the state is required — it decides holidays.) */
export function canContinue(step: number, draft: OnboardingDraft): boolean {
  if (step === 1) return BUNDESLAENDER.some((b) => b.code === draft.region);
  return true;
}

/**
 * The `POST /api/onboarding` body. Empty name/address are left out (so skipping them never
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

export type ClaudeState = "ready" | "unchecked" | "signed_out" | "outdated" | "missing";

/**
 * What the Claude check shows: ready · installed but not probed · not signed in · older than Ordnung needs
 * (`needs_version`, the server's minimum) · not installed.
 */
export function claudeState(c: ClaudeStatus | null | undefined): ClaudeState {
  if (!c || !c.installed) return "missing";
  if (c.needs_version) return "outdated";
  if (c.ok === true) return "ready";
  if (c.ok === false) return "signed_out";
  return "unchecked";
}

/**
 * The Claude step's state, adding "the health answer isn't here yet" (`checking`) and "Ordnung
 * didn't answer" (`unknown`) — neither of them means Claude isn't installed.
 */
export type ClaudeView = ClaudeState | "checking" | "unknown";

export function claudeView(c: ClaudeStatus | null | undefined, health: { pending: boolean; failed: boolean }): ClaudeView {
  if (c) return claudeState(c);
  if (health.pending) return "checking";
  if (health.failed) return "unknown";
  return "missing";
}

/** Claude can read letters (or will be checked with the first one): the wizard offers "Finish setup". */
export function claudeUsable(view: ClaudeView): boolean {
  return view === "ready" || view === "unchecked";
}
