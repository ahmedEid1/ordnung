import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useCompleteOnboarding, useHealth, useProfile } from "@/api/hooks";
import { BootScreen } from "@/app/screens";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Logo } from "@/components/shell/Logo";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Toaster } from "@/components/ui/Toast";
import { ProgressDots } from "./ProgressDots";
import { StepDone } from "./StepDone";
import { StepAddress, StepClaude, StepRegion, StepWelcome } from "./Steps";
import {
  DONE_STEP,
  WIZARD_STEPS,
  addressEmpty,
  buildOnboardingRequest,
  canContinue,
  claudeUsable,
  claudeView,
  initialDraft,
  wizardTitle,
  type OnboardingDraft,
} from "./wizard";

/**
 * First-run wizard (SPEC §14.9): welcome + privacy → where you live (state, language, student
 * permit) → name & address (skippable) → Claude check (copyable fixes, "Continue without AI") →
 * `POST /api/onboarding` → drop zone for the first letters or "Explore the demo instead".
 *
 * Opened again by someone who is set up already, step 1 reads "Change your setup" and the logo
 * and "Back to Ordnung" lead back into the app. Every step names itself in the tab title, and its
 * heading takes the focus once it is on screen.
 */
export function OnboardingWizard() {
  const health = useHealth();
  const profile = useProfile();
  const complete = useCompleteOnboarding();
  const [step, setStep] = useState(0);
  const [edits, setEdits] = useState<Partial<OnboardingDraft>>({});
  const [skippedAi, setSkippedAi] = useState(false);
  const regionRef = useRef<HTMLFieldSetElement>(null);
  const hintId = useId();

  const base = useMemo(() => initialDraft(profile.data), [profile.data]);
  const draft: OnboardingDraft = { ...base, ...edits };
  const change = (p: Partial<OnboardingDraft>) => setEdits((e) => ({ ...e, ...p }));
  const claude = health.data?.claude;
  const view = claudeView(claude, { pending: health.isPending, failed: health.isError });
  const aiReady = claudeUsable(view);
  const onboarded = profile.data?.onboarded === true;
  const revisit = onboarded && step < DONE_STEP;

  useEffect(() => {
    document.title = wizardTitle(step, { revisit });
  }, [step, revisit]);

  // A new step's heading takes the focus (screen readers announce it) once it is mounted — after
  // the previous step has faded out — and the page starts at the top again. Not on first load.
  const moved = useRef(false);
  const headingRef = useCallback((el: HTMLHeadingElement | null) => {
    if (!el || !moved.current) return;
    el.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, []);

  // the answers so far decide step 1 ("Welcome" or "Change your setup") and pre-fill the steps
  if (profile.isPending) return <BootScreen />;

  const go = (next: number) => {
    moved.current = true;
    complete.reset();
    setStep(next);
  };

  const finish = (skipAi: boolean) => {
    complete.mutate(buildOnboardingRequest(draft, { skipAi }), {
      onSuccess: () => {
        setSkippedAi(skipAi);
        go(DONE_STEP);
      },
    });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (complete.isPending) return;
    if (!canContinue(step, draft)) {
      // "Continue" stays reachable while no state is chosen: it leads to the question instead
      if (step === 1) regionRef.current?.querySelector<HTMLInputElement>("input[type=radio]")?.focus();
      return;
    }
    if (step === 3) finish(!aiReady);
    else go(Math.min(step + 1, 3));
  };

  const firstName = draft.name.trim().split(/\s+/)[0] ?? "";
  const blocked = !canContinue(step, draft);

  let main: ReactNode = null;
  if (step === 0) {
    main = (
      <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} className="w-full sm:w-auto">
        Get started
      </Button>
    );
  } else if (step === 1 || step === 2) {
    const skip = step === 2 && addressEmpty(draft);
    main = (
      <Button
        type="submit"
        variant={skip ? "secondary" : "primary"}
        size="lg"
        iconRight={ArrowRight}
        className="w-full sm:w-auto"
        aria-disabled={blocked || undefined}
        aria-describedby={blocked ? hintId : undefined}
      >
        {skip ? "Skip for now" : "Continue"}
      </Button>
    );
  } else if (step === 3) {
    main = aiReady ? (
      <Button type="submit" variant="primary" size="lg" icon={Check} loading={complete.isPending} className="w-full sm:w-auto">
        Finish setup
      </Button>
    ) : (
      <Button type="submit" variant="secondary" size="lg" loading={complete.isPending} className="w-full sm:w-auto">
        Continue without AI
      </Button>
    );
  }

  const back =
    step > 0 ? (
      <Button variant="ghost" icon={ArrowLeft} onClick={() => go(step - 1)}>
        Back
      </Button>
    ) : revisit ? (
      <Link to="/" replace className={buttonVariants({ variant: "ghost" })}>
        <ArrowLeft aria-hidden />
        Back to Ordnung
      </Link>
    ) : null;

  return (
    <div className="relative flex min-h-dvh flex-col overflow-x-hidden bg-canvas">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(60%_100%_at_50%_0%,var(--color-accent-soft),transparent)] opacity-80 dark:opacity-50"
      />
      <header className="relative mx-auto flex w-full max-w-2xl items-center justify-between gap-4 px-4 pb-4 pt-6 sm:px-6">
        {onboarded ? (
          <Link to="/" replace aria-label="Back to Ordnung" className="rounded-lg">
            <Logo />
          </Link>
        ) : (
          <Logo />
        )}
        <ProgressDots steps={WIZARD_STEPS} current={step} />
      </header>

      <main className="relative mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-16 sm:px-6">
        {/* centred in a tall window (auto margins never push it above the top) */}
        <div className="sm:my-auto">
          <form onSubmit={onSubmit} className="card p-5 sm:p-9" noValidate>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={step}
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -12 }}
                transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
              >
                {step === 0 ? <StepWelcome headingRef={headingRef} revisit={revisit} /> : null}
                {step === 1 ? <StepRegion draft={draft} onChange={change} headingRef={headingRef} groupRef={regionRef} /> : null}
                {step === 2 ? <StepAddress draft={draft} onChange={change} headingRef={headingRef} /> : null}
                {step === 3 ? <StepClaude claude={claude} view={view} checking={health.isFetching} onRecheck={() => void health.refetch()} headingRef={headingRef} /> : null}
                {step === DONE_STEP ? (
                  <AddLettersProvider>
                    <StepDone firstName={firstName} skippedAi={skippedAi} headingRef={headingRef} />
                  </AddLettersProvider>
                ) : null}
              </motion.div>
            </AnimatePresence>

            {step < DONE_STEP ? (
              <div className="mt-8 border-t border-line pt-5">
                {step === 3 && complete.isError ? (
                  <Callout tone="danger" alert title="Couldn't finish setting up" className="mb-5">
                    {complete.error.message} Your answers are still here — try again.
                  </Callout>
                ) : null}
                {/* phones: the main button full width on top, Back under it; wider: Back left, main button right */}
                <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:gap-4">
                  {back ? <div className="flex sm:mr-auto">{back}</div> : null}
                  {step === 1 && blocked ? (
                    <p id={hintId} className="order-1 text-center text-[13px] text-muted sm:order-none sm:text-right">
                      Choose your state to continue.
                    </p>
                  ) : null}
                  <div className={back ? "flex" : "flex sm:ml-auto"}>{main}</div>
                </div>
              </div>
            ) : null}
          </form>
          <p className="mt-6 text-pretty text-center text-[12.5px] text-muted">Ordnung runs on this computer. Nothing leaves it without your Claude account.</p>
        </div>
      </main>
      <Toaster />
    </div>
  );
}
