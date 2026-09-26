import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useCompleteOnboarding, useHealth, useProfile } from "@/api/hooks";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Logo } from "@/components/shell/Logo";
import { Button } from "@/components/ui/Button";
import { Toaster } from "@/components/ui/Toast";
import { ProgressDots } from "./ProgressDots";
import { StepDone } from "./StepDone";
import { StepAddress, StepClaude, StepRegion, StepWelcome } from "./Steps";
import { DONE_STEP, WIZARD_STEPS, buildOnboardingRequest, canContinue, claudeState, initialDraft, type OnboardingDraft } from "./wizard";

/**
 * First-run wizard (SPEC §14.9): welcome + privacy → where you live (state, language, student
 * permit) → name & address (skippable) → Claude check (copyable fixes, "Continue without AI") →
 * `POST /api/onboarding` → drop zone for the first letters or "Explore the demo instead".
 */
export function OnboardingWizard() {
  const health = useHealth();
  const profile = useProfile();
  const complete = useCompleteOnboarding();
  const [step, setStep] = useState(0);
  const [edits, setEdits] = useState<Partial<OnboardingDraft>>({});
  const [skippedAi, setSkippedAi] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  const base = useMemo(() => initialDraft(profile.data), [profile.data]);
  const draft: OnboardingDraft = { ...base, ...edits };
  const change = (p: Partial<OnboardingDraft>) => setEdits((e) => ({ ...e, ...p }));
  const claude = health.data?.claude;
  const aiReady = ["ready", "unchecked"].includes(claudeState(claude));

  // Move focus to the new step's heading (screen readers announce it); not on first load.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headingRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [step]);

  const finish = (skipAi: boolean) => {
    complete.mutate(buildOnboardingRequest(draft, { skipAi }), {
      onSuccess: () => {
        setSkippedAi(skipAi);
        setStep(DONE_STEP);
      },
    });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canContinue(step, draft)) return;
    if (step === 3) {
      if (aiReady) finish(false);
      return;
    }
    setStep((s) => Math.min(s + 1, 3));
  };

  const firstName = draft.name.trim().split(/\s+/)[0] ?? "";

  return (
    <div className="relative min-h-dvh overflow-x-hidden bg-canvas">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(60%_100%_at_50%_0%,var(--color-accent-soft),transparent)] opacity-80 dark:opacity-50"
      />
      <header className="relative mx-auto flex w-full max-w-2xl items-center justify-between px-4 pb-4 pt-6 sm:px-6">
        <Logo />
        <ProgressDots steps={WIZARD_STEPS} current={step} />
      </header>

      <main className="relative mx-auto w-full max-w-2xl px-4 pb-16 sm:px-6">
        <form onSubmit={onSubmit} className="card p-5 sm:p-9" noValidate>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -12 }}
              transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            >
              {step === 0 ? <StepWelcome headingRef={headingRef} /> : null}
              {step === 1 ? <StepRegion draft={draft} onChange={change} headingRef={headingRef} /> : null}
              {step === 2 ? <StepAddress draft={draft} onChange={change} headingRef={headingRef} /> : null}
              {step === 3 ? (
                <StepClaude claude={claude} checking={health.isFetching} onRecheck={() => void health.refetch()} headingRef={headingRef} />
              ) : null}
              {step === DONE_STEP ? (
                <AddLettersProvider>
                  <StepDone firstName={firstName} skippedAi={skippedAi} headingRef={headingRef} />
                </AddLettersProvider>
              ) : null}
            </motion.div>
          </AnimatePresence>

          {step < DONE_STEP ? (
            <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-line pt-5">
              {step > 0 ? (
                <Button variant="ghost" icon={ArrowLeft} onClick={() => setStep((s) => s - 1)}>
                  Back
                </Button>
              ) : null}
              <div className="flex-1" />
              {step === 1 && !canContinue(1, draft) ? <p className="w-full text-right text-[12.5px] text-muted sm:w-auto">Choose your state to continue.</p> : null}
              {step === 2 ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    change({ name: "", address: "" });
                    setStep(3);
                  }}
                >
                  Skip for now
                </Button>
              ) : null}
              {step === 3 && !aiReady ? (
                <Button variant="secondary" onClick={() => finish(true)} loading={complete.isPending && complete.variables?.skip_ai === true}>
                  Continue without AI
                </Button>
              ) : null}
              {step < 3 ? (
                <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} disabled={!canContinue(step, draft)}>
                  {step === 0 ? "Get started" : "Continue"}
                </Button>
              ) : aiReady ? (
                <Button type="submit" variant="primary" size="lg" icon={Check} loading={complete.isPending}>
                  Finish setup
                </Button>
              ) : null}
            </div>
          ) : null}
        </form>
        <p className="mt-6 text-center text-[12.5px] text-muted">Ordnung runs on this computer. Nothing leaves it without your Claude account.</p>
      </main>
      <Toaster />
    </div>
  );
}
