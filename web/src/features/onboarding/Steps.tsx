import { useId, type ReactNode, type Ref } from "react";
import {
  BellRing,
  CircleCheck,
  CircleAlert,
  FileSearch,
  Lock,
  PenLine,
  RotateCw,
  Scale,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import type { ClaudeStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { cn } from "@/lib/utils";
import { CopyCommand } from "./CopyCommand";
import { BUNDESLAENDER, CLAUDE_INSTALL_CMD, CLAUDE_LOGIN_CMD, LANGUAGES, PRIVACY_STATEMENT } from "./options";
import { claudeState, returnLine, type OnboardingDraft } from "./wizard";

/** Step heading: receives focus when the step changes (announced by screen readers). */
export function StepHeading({ children, eyebrow, headingRef, description }: { children: ReactNode; eyebrow?: string; headingRef: Ref<HTMLHeadingElement>; description?: ReactNode }) {
  return (
    <div>
      {eyebrow ? <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">{eyebrow}</p> : null}
      <h1 ref={headingRef} tabIndex={-1} className="display mt-1.5 text-[28px] font-semibold leading-tight text-ink outline-none sm:text-[32px]">
        {children}
      </h1>
      {description ? <p className="mt-2 text-[15px] leading-relaxed text-muted">{description}</p> : null}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
// 1 · Welcome
// ------------------------------------------------------------------------------------------------

const PROMISES: { icon: LucideIcon; title: string; text: ReactNode }[] = [
  { icon: FileSearch, title: "Reads your letters", text: "PDFs and phone photos in German — explained simply in your language." },
  { icon: Scale, title: "Computes every deadline", text: "With tested legal rules, not guesses — and shows you why." },
  { icon: BellRing, title: "Reminds, suggests, drafts", text: "It never sends, cancels or pays anything on its own." },
];

export function StepWelcome({ headingRef }: { headingRef: Ref<HTMLHeadingElement> }) {
  return (
    <div className="space-y-6">
      <StepHeading headingRef={headingRef} eyebrow="Step 1 of 4" description="Your private secretary for letters, bills and deadlines. Let's set it up — it takes about a minute.">
        Welcome to Ordnung
      </StepHeading>
      <ul className="grid gap-3 sm:grid-cols-3">
        {PROMISES.map((p) => (
          <li key={p.title} className="rounded-xl border border-line bg-surface-2/50 p-3.5">
            <p.icon className="size-[18px] text-accent" aria-hidden />
            <p className="mt-2 text-[14px] font-semibold text-ink">{p.title}</p>
            <p className="mt-0.5 text-[13px] leading-snug text-muted">{p.text}</p>
          </li>
        ))}
      </ul>
      <section aria-labelledby="privacy-title" className="rounded-xl border border-accent/20 bg-accent-soft/60 p-4">
        <h2 id="privacy-title" className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Lock className="size-4 text-accent" aria-hidden /> Your privacy
        </h2>
        <p className="mt-1.5 text-[14px] leading-relaxed text-ink/85">
          {PRIVACY_STATEMENT.split("claude CLI").map((part, i) =>
            i === 0 ? (
              part
            ) : (
              <span key={i}>
                <code className="rounded bg-surface px-1 py-px font-mono text-[12.5px] text-ink">claude</code> CLI{part}
              </span>
            ),
          )}
        </p>
      </section>
      <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted">
        <Scale className="mt-0.5 size-4 shrink-0" aria-hidden />
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

function ChoicePill({ name, value, checked, onChange, children, lang, dir }: { name: string; value: string; checked: boolean; onChange: () => void; children: ReactNode; lang?: string; dir?: "rtl" }) {
  return (
    <label
      className={cn(
        "relative inline-flex h-10 cursor-pointer items-center rounded-full border px-4 text-[14px] font-medium transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent bg-accent-soft text-accent" : "border-line-strong/80 bg-surface text-ink hover:border-line-strong hover:bg-surface-2",
      )}
    >
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} className="sr-only" />
      <span lang={lang} dir={dir}>
        {children}
      </span>
    </label>
  );
}

export function StepRegion({ draft, onChange, headingRef }: { draft: OnboardingDraft; onChange: (p: Partial<OnboardingDraft>) => void; headingRef: Ref<HTMLHeadingElement> }) {
  const id = useId();
  return (
    <div className="space-y-7">
      <StepHeading headingRef={headingRef} eyebrow="Step 2 of 4" description="Public holidays differ between the 16 states, and they move deadlines.">
        Where do you live?
      </StepHeading>

      <fieldset>
        <legend className="text-[14px] font-semibold text-ink">Your state (Bundesland)</legend>
        <p id={`${id}-hint`} className="mt-0.5 text-[13px] text-muted">
          Affects public holidays and deadlines.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2" aria-describedby={`${id}-hint`}>
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
      <StepHeading headingRef={headingRef} eyebrow="Step 3 of 4" description="Used as the sender on letters Ordnung drafts for you. You can skip this and add it later in Settings.">
        Your name and address
      </StepHeading>
      <div className="grid gap-4">
        <Field label="Your name" optional>
          <Input value={draft.name} onChange={(e) => onChange({ name: e.target.value })} autoComplete="name" placeholder="Sam Rivera" />
        </Field>
        <Field label="Postal address" optional hint="Street and number, then postcode and city — as on your letters.">
          <Textarea
            value={draft.address}
            onChange={(e) => onChange({ address: e.target.value })}
            autoComplete="street-address"
            rows={3}
            placeholder={"Musterweg 12\n12345 Musterstadt"}
            className="min-h-0"
          />
        </Field>
      </div>
      <figure className="overflow-hidden rounded-xl border border-line bg-surface-2/50 p-4" aria-label="Preview of your letterhead">
        <figcaption className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
          <PenLine className="size-3.5" aria-hidden /> How it looks on your letters
        </figcaption>
        <div className="mt-3 rounded-lg border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)]">
          <p className={cn("truncate border-b border-line pb-1 text-[10.5px] tracking-wide", line ? "text-ink/70" : "text-faint")}>
            {line || "Your name · Street 1 · 12345 City"}
          </p>
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

export function StepClaude({
  claude,
  checking,
  onRecheck,
  headingRef,
}: {
  claude: ClaudeStatus | undefined;
  checking: boolean;
  onRecheck: () => void;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const state = claudeState(claude);
  return (
    <div className="space-y-6">
      <StepHeading
        headingRef={headingRef}
        eyebrow="Step 4 of 4"
        description="Ordnung reads letters with the Claude app on this computer, using your own Claude account. No extra account, no API key."
      >
        Is Claude ready?
      </StepHeading>

      <div
        role="status"
        className={cn(
          "flex items-start gap-3 rounded-xl border p-4",
          state === "ready" || state === "unchecked" ? "border-ok/30 bg-ok-soft/70" : "border-warn/30 bg-warn-soft/70",
        )}
      >
        {state === "ready" || state === "unchecked" ? (
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden />
        ) : (
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("text-[15px] font-semibold", state === "ready" || state === "unchecked" ? "text-ok-ink" : "text-warn-ink")}>
            {state === "ready"
              ? "Claude is ready"
              : state === "unchecked"
                ? "Claude is installed"
                : state === "signed_out"
                  ? "Claude is installed, but not signed in"
                  : "Claude isn't installed yet"}
          </p>
          <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink/80">
            {state === "ready"
              ? [claude?.version, claude?.detail].filter(Boolean).join(" · ") || "Signed in and working."
              : state === "unchecked"
                ? `${claude?.version ?? "Found on this computer"}. The sign-in is checked when the first letter is read.`
                : state === "signed_out"
                  ? claude?.detail ?? "Sign in once in your terminal, then check again."
                  : "Install it once in your terminal (it needs Node.js 18 or newer), then sign in."}
          </p>
        </div>
      </div>

      {state === "missing" || state === "signed_out" ? (
        <ol className="space-y-4">
          {state === "missing" ? (
            <li>
              <p className="mb-2 flex items-center gap-2 text-[14px] font-medium text-ink">
                <span className="grid size-5 place-items-center rounded-full bg-accent text-[11px] font-bold text-on-accent">1</span>
                Install Claude Code
              </p>
              <CopyCommand command={CLAUDE_INSTALL_CMD} label="install Claude Code" />
            </li>
          ) : null}
          <li>
            <p className="mb-2 flex items-center gap-2 text-[14px] font-medium text-ink">
              <span className="grid size-5 place-items-center rounded-full bg-accent text-[11px] font-bold text-on-accent">{state === "missing" ? 2 : 1}</span>
              Start it once and sign in with your Claude account
            </p>
            <CopyCommand command={CLAUDE_LOGIN_CMD} label="sign in" />
          </li>
          <li>
            <Button icon={RotateCw} onClick={onRecheck} loading={checking}>
              Check again
            </Button>
          </li>
        </ol>
      ) : null}

      {state === "missing" || state === "signed_out" ? (
      <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted">
        <Terminal className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          Without Claude you can still store letters privately, search them and add your own dates. Reading letters and Ideas need Claude — you can
          connect it later in Settings.
        </span>
      </p>
      ) : null}
    </div>
  );
}

