import { useId, useState, type ReactNode, type Ref } from "react";
import { BellRing, Check, CircleAlert, CircleCheck, FileSearch, Info, Lock, PenLine, RotateCw, Scale, Terminal, type LucideIcon } from "lucide-react";
import type { ClaudeStatus } from "@/api/types";
import { ACCEPTED_SHORT } from "@/components/shell/AddLetters";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";
import { CopyCommand } from "./CopyCommand";
import { BUNDESLAENDER, CLAUDE_INSTALL_CMD, CLAUDE_LOGIN_CMD, LANGUAGES, PRIVACY_STATEMENT } from "./options";
import { REVISIT_HEADING, WIZARD_STEPS, claudeUsable, returnLine, stepLabel, type ClaudeView, type OnboardingDraft } from "./wizard";

/**
 * Step heading. The wizard passes a callback ref that focuses it when a new step mounts (after
 * the previous one has faded out), so screen readers announce the step and Tab starts there.
 */
export function StepHeading({ children, eyebrow, headingRef, description }: { children: ReactNode; eyebrow?: string; headingRef: Ref<HTMLHeadingElement>; description?: ReactNode }) {
  return (
    <div>
      {eyebrow ? <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">{eyebrow}</p> : null}
      <h1 ref={headingRef} tabIndex={-1} className="display mt-1.5 text-balance text-[28px] font-semibold leading-tight text-ink outline-none sm:text-[32px]">
        {children}
      </h1>
      {description ? <p className="mt-2 text-pretty text-[15px] leading-relaxed text-muted">{description}</p> : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// 1 · Welcome
// ------------------------------------------------------------------------------------------------

const PROMISES: { icon: LucideIcon; title: string; text: ReactNode }[] = [
  { icon: FileSearch, title: "Reads your letters", text: `${ACCEPTED_SHORT} in German — explained simply in your language.` },
  { icon: Scale, title: "Computes every deadline", text: "With tested legal rules, not guesses — and shows you why." },
  { icon: BellRing, title: "Reminds, suggests, drafts", text: "It never sends, cancels or pays anything on its own." },
];

/** Step 1. `revisit`: someone who has set Ordnung up already opened the wizard again. */
export function StepWelcome({ headingRef, revisit = false }: { headingRef: Ref<HTMLHeadingElement>; revisit?: boolean }) {
  return (
    <div className="space-y-6">
      <StepHeading
        headingRef={headingRef}
        eyebrow={stepLabel(0)}
        description={
          revisit
            ? "Ordnung is set up already. Go through the four steps again to change your state, language, name or address — or go back to Ordnung."
            : "Your private secretary for letters, bills and deadlines. Let's set it up — it takes about a minute."
        }
      >
        {revisit ? REVISIT_HEADING : WIZARD_STEPS[0].heading}
      </StepHeading>
      {/* the cards share their rows (subgrid): the descriptions start level however the titles wrap */}
      <ul className="grid gap-3 sm:grid-cols-3 sm:grid-rows-[auto_auto_1fr]">
        {PROMISES.map((p) => (
          <li key={p.title} className="rounded-xl border border-line bg-surface-2/50 p-3.5 sm:row-span-3 sm:grid sm:grid-rows-subgrid sm:gap-y-0">
            <p.icon className="size-[18px] text-accent" aria-hidden />
            <p className="mt-2 text-balance text-[14px] font-semibold leading-snug text-ink">{p.title}</p>
            <p className="mt-0.5 text-[13px] leading-snug text-muted">{p.text}</p>
          </li>
        ))}
      </ul>
      <section aria-labelledby="privacy-title" className="rounded-xl border border-accent/20 bg-accent-soft/60 p-4">
        <h2 id="privacy-title" className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Lock className="size-4 text-accent" aria-hidden /> Your privacy
        </h2>
        <p className="mt-1.5 text-[14px] leading-relaxed text-ink/85">{PRIVACY_STATEMENT}</p>
      </section>
      <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          <span className="font-semibold text-ink">Not legal advice.</span> Ordnung is a reminder and letter-template tool, not a lawyer. Dates follow
          tested rules, but when a lot is at stake — residence, court, fines — please get independent advice.
        </span>
      </p>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// 2 · Where do you live?
// ------------------------------------------------------------------------------------------------

/** The chosen card's or pill's mark — the choice never shows by colour alone (WCAG 1.4.1). */
function Chosen({ className }: { className?: string }) {
  return <Check className={cn("shrink-0", className)} strokeWidth={3} aria-hidden />;
}

function ChoicePill({ name, value, checked, onChange, children, lang, dir }: { name: string; value: string; checked: boolean; onChange: () => void; children: ReactNode; lang?: string; dir?: "rtl" }) {
  return (
    <label
      className={cn(
        "relative inline-flex h-10 cursor-pointer items-center gap-1.5 rounded-full border px-4 text-[14px] font-medium transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent bg-accent-soft pl-3 text-accent shadow-[inset_0_0_0_1px_var(--color-accent)]" : "border-line-strong/80 bg-surface text-ink hover:border-line-strong hover:bg-surface-2",
      )}
    >
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} className="sr-only" />
      {checked ? <Chosen className="size-3.5" /> : null}
      <span lang={lang} dir={dir}>
        {children}
      </span>
    </label>
  );
}

export function StepRegion({
  draft,
  onChange,
  headingRef,
  groupRef,
}: {
  draft: OnboardingDraft;
  onChange: (p: Partial<OnboardingDraft>) => void;
  headingRef: Ref<HTMLHeadingElement>;
  /** The state question — "Continue" moves focus here while no state is chosen. */
  groupRef?: Ref<HTMLFieldSetElement>;
}) {
  const id = useId();
  return (
    <div className="space-y-7">
      <StepHeading headingRef={headingRef} eyebrow={stepLabel(1)} description="Public holidays differ between the 16 states, and they move deadlines.">
        {WIZARD_STEPS[1].heading}
      </StepHeading>

      <fieldset ref={groupRef} aria-describedby={`${id}-hint`}>
        <legend className="text-[14px] font-semibold text-ink">Your state (Bundesland)</legend>
        <p id={`${id}-hint`} className="mt-0.5 text-[13px] text-muted">
          Affects public holidays and deadlines.
        </p>
        {/* one column on the smallest phones: two would break the names over three or four lines */}
        <div className="mt-3 grid grid-cols-1 gap-2 min-[360px]:grid-cols-2">
          {BUNDESLAENDER.map((b) => {
            const checked = draft.region === b.code;
            return (
              <label
                key={b.code}
                className={cn(
                  "relative flex min-h-12 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 transition-colors",
                  "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  checked ? "border-accent bg-accent-soft/70 shadow-[inset_0_0_0_1px_var(--color-accent)]" : "border-line bg-surface hover:border-line-strong hover:bg-surface-2/60",
                )}
              >
                <input type="radio" name="region" value={b.code} checked={checked} onChange={() => onChange({ region: b.code })} className="sr-only" />
                <span
                  aria-hidden
                  className={cn(
                    "hidden h-6 w-8 shrink-0 place-items-center rounded-md text-[11px] font-bold tracking-wide sm:grid",
                    checked ? "bg-accent text-on-accent" : "bg-surface-2 text-muted",
                  )}
                >
                  {b.code}
                </span>
                <span className="min-w-0">
                  <span lang="de" className="block text-[13.5px] font-medium leading-tight text-ink hyphens-auto">
                    {b.name}
                  </span>
                  {b.en ? <span className="block text-[12px] leading-tight text-muted">{b.en}</span> : null}
                </span>
                {checked ? (
                  <span className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-accent text-on-accent ring-2 ring-surface">
                    <Chosen className="size-3" />
                  </span>
                ) : null}
              </label>
            );
          })}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-[14px] font-semibold text-ink">Language for explanations</legend>
        <p className="mt-0.5 text-[13px] text-muted">Summaries and translations use this language. Letters you send stay in German.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {LANGUAGES.map((l) => (
            <ChoicePill key={l.code} name="language" value={l.code} checked={draft.language === l.code} onChange={() => onChange({ language: l.code })} lang={l.code} dir={l.dir}>
              {l.label}
            </ChoicePill>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-[14px] font-semibold text-ink">Do you have a student residence permit?</legend>
        <p className="mt-0.5 text-[13px] text-muted">
          Then Ordnung watches your <Glossary term="Aufenthaltstitel" /> and passport dates more closely.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <ChoicePill name="permit" value="yes" checked={draft.isStudentVisa === true} onChange={() => onChange({ isStudentVisa: true })}>
            Yes
          </ChoicePill>
          <ChoicePill name="permit" value="no" checked={draft.isStudentVisa === false} onChange={() => onChange({ isStudentVisa: false })}>
            No
          </ChoicePill>
        </div>
      </fieldset>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// 3 · Name & address
// ------------------------------------------------------------------------------------------------

export function StepAddress({ draft, onChange, headingRef }: { draft: OnboardingDraft; onChange: (p: Partial<OnboardingDraft>) => void; headingRef: Ref<HTMLHeadingElement> }) {
  const line = returnLine(draft.name, draft.address);
  return (
    <div className="space-y-6">
      <StepHeading headingRef={headingRef} eyebrow={stepLabel(2)} description="Used as the sender on letters Ordnung drafts for you. You can skip this and add it later in Settings.">
        {WIZARD_STEPS[2].heading}
      </StepHeading>
      <div className="grid gap-4">
        <Field label="Your name" optional>
          <Input value={draft.name} onChange={(e) => onChange({ name: e.target.value })} autoComplete="name" placeholder="Sam Rivera" />
        </Field>
        <Field label="Postal address" optional hint="Street and number, then postcode and city — as on your letters.">
          {/* grows with the address (four lines where the browser can't), so no line hides above the fold */}
          <Textarea
            value={draft.address}
            onChange={(e) => onChange({ address: e.target.value })}
            onBlur={(e) => {
              e.currentTarget.scrollTop = 0;
            }}
            autoComplete="street-address"
            rows={4}
            placeholder={"Musterweg 12\n12345 Musterstadt"}
            className="max-h-48 [field-sizing:content]"
          />
        </Field>
      </div>
      <figure className="overflow-hidden rounded-xl border border-line bg-surface-2/50 p-4" aria-label="Preview of your letterhead">
        <figcaption className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
          <PenLine className="size-3.5" aria-hidden /> How it looks on your letters
        </figcaption>
        <div className="mt-3 rounded-lg border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)]">
          {/* at most two lines (the whole line on hover; it is typed in full above) */}
          <div className="border-b border-line pb-1">
            <p title={line || undefined} className={cn("line-clamp-2 text-[12px] leading-snug tracking-wide [overflow-wrap:anywhere]", line ? "text-ink/75" : "text-muted")}>
              {line || "Your name · Street 1 · 12345 City"}
            </p>
          </div>
          <div className="mt-2.5 space-y-1.5" aria-hidden>
            <div className="h-2 w-28 rounded-full bg-line-strong/70" />
            <div className="h-2 w-36 rounded-full bg-line-strong/70" />
            <div className="h-2 w-24 rounded-full bg-line-strong/70" />
          </div>
        </div>
      </figure>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// 4 · Claude check
// ------------------------------------------------------------------------------------------------

/** "2.1.4 (Claude Code)" → "Claude Code 2.1.4". */
function programVersion(version: string | null | undefined): string | null {
  const v = version?.replace(/\s*\(Claude Code\)\s*$/i, "").trim();
  return v ? `Claude Code ${v}` : null;
}

const VIEW_COPY: Record<ClaudeView, { title: string; text: string }> = {
  ready: { title: "Claude is ready", text: "Signed in and working." },
  unchecked: { title: "Claude is installed", text: "Found on this computer. The sign-in is checked when the first letter is read." },
  signed_out: { title: "Claude is installed, but not signed in", text: "Start it once in your terminal and sign in with your Claude account, then check again." },
  missing: { title: "Claude isn't installed yet", text: "Install Claude Code once in your terminal (it needs Node.js 18 or newer), then sign in." },
  checking: { title: "Looking for Claude on this computer…", text: "This takes a moment." },
  unknown: { title: "Couldn't check for Claude", text: "Ordnung didn't answer the check. Check again — or continue without AI and connect Claude later in Settings." },
};

/** After "Check again": what the check found, when it found the same as before. */
const STILL: Partial<Record<ClaudeView, string>> = {
  missing: "Checked just now — still not found on this computer.",
  signed_out: "Checked just now — still not signed in.",
  unknown: "Checked just now — Ordnung still didn't answer.",
};

export function StepClaude({
  claude,
  view,
  checking,
  onRecheck,
  headingRef,
}: {
  claude: ClaudeStatus | undefined;
  view: ClaudeView;
  checking: boolean;
  onRecheck: () => void;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const [rechecked, setRechecked] = useState(false);
  const good = claudeUsable(view);
  const needsFix = view === "missing" || view === "signed_out";
  const version = good ? programVersion(claude?.version) : null;
  const copy = VIEW_COPY[view];
  const note = rechecked ? (checking ? "Checking again…" : STILL[view]) : undefined;
  return (
    <div className="space-y-6">
      <StepHeading
        headingRef={headingRef}
        eyebrow={stepLabel(3)}
        description="Ordnung reads letters with Claude Code, the Claude program on this computer, using your own Claude account. No extra account, no API key."
      >
        {WIZARD_STEPS[3].heading}
      </StepHeading>

      <div
        role="status"
        className={cn(
          "flex items-start gap-3 rounded-xl border p-4",
          good ? "border-ok/30 bg-ok-soft/70" : view === "checking" ? "border-line bg-surface-2/60" : "border-warn/30 bg-warn-soft/70",
        )}
      >
        {view === "checking" ? (
          <Spinner className="mt-0.5 size-5 shrink-0 text-muted" />
        ) : good ? (
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden />
        ) : (
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("text-[15px] font-semibold", good ? "text-ok-ink" : view === "checking" ? "text-ink" : "text-warn-ink")}>{copy.title}</p>
          <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink/80">{copy.text}</p>
          {version ? <p className="mt-0.5 text-[12.5px] text-ink/65">{version}</p> : null}
          {note ? <p className="mt-1.5 text-[13px] font-medium text-ink/80">{note}</p> : null}
        </div>
      </div>

      {needsFix ? (
        <ol className="space-y-4">
          {view === "missing" ? (
            <li>
              <p className="mb-2 flex items-start gap-2 text-[14px] font-medium text-ink">
                <span className="mt-px grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[12px] font-bold text-on-accent">1</span>
                Install Claude Code
              </p>
              <CopyCommand command={CLAUDE_INSTALL_CMD} label="install Claude Code" />
            </li>
          ) : null}
          <li>
            <p className="mb-2 flex items-start gap-2 text-[14px] font-medium text-ink">
              <span className="mt-px grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[12px] font-bold text-on-accent">{view === "missing" ? 2 : 1}</span>
              Start it once and sign in with your Claude account
            </p>
            <CopyCommand command={CLAUDE_LOGIN_CMD} label="sign in" />
          </li>
        </ol>
      ) : null}

      {needsFix || view === "unknown" ? (
        <>
          <div>
            <Button
              icon={RotateCw}
              onClick={() => {
                setRechecked(true);
                onRecheck();
              }}
              loading={checking}
            >
              Check again
            </Button>
          </div>
          <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted">
            <Terminal className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Without Claude you can still store letters privately, search them and add your own dates. Reading letters and Ideas need Claude — you can
              connect it later in Settings.
            </span>
          </p>
        </>
      ) : null}
    </div>
  );
}
