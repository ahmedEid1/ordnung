import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, ChevronUp, Compass, Minus, X } from "lucide-react";
import { useEvents } from "@/api/sse";
import { Button, IconButton } from "@/components/ui/Button";
import { getOverlayRoot } from "@/components/ui/internal";
import { TOAST_LIFT_VAR, toast } from "@/components/ui/Toast";
import { useIsTabletUp, useLocalStorage } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { TOUR_DOCK_ID, TOUR_STEPS, onStepRoute, type TourStep } from "./steps";
import type { TourEvent } from "./tourMachine";
import { useTourController } from "./useTourController";
import { useSpotlight, type SpotRect } from "./useSpotlight";
import { useNewMailIdeas } from "./newMail";

/** The dock must be at least this tall to hold the card; otherwise it floats bottom-right. */
const MIN_DOCK_HEIGHT = 250;

/** Soft ring + gentle pulse around the element the current step talks about. */
function Spotlight({ rect, target }: { rect: SpotRect; target: string }) {
  const reduce = useReducedMotion();
  const pad = 6;
  return (
    <motion.div
      aria-hidden
      data-testid="tour-spotlight"
      data-target={target}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      className="pointer-events-none fixed z-[25] rounded-[18px] ring-2 ring-accent/70"
      style={{
        top: rect.top - pad,
        left: rect.left - pad,
        width: rect.width + pad * 2,
        height: rect.height + pad * 2,
        boxShadow: "0 0 0 6px color-mix(in srgb, var(--color-accent) 14%, transparent)",
      }}
    >
      {!reduce ? (
        <motion.span
          className="absolute inset-0 rounded-[inherit] ring-2 ring-accent/50"
          animate={{ opacity: [0.7, 0], scale: [1, 1.025] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
        />
      ) : null}
    </motion.div>
  );
}

/** Width of the toast column on tablets and up (toasts 380 px, upload cards 400 px) + its margin. */
const TOAST_COLUMN = 400 + 20;

/**
 * While the tour card (or its pill) shares the bottom edge with the toast column — always on phones,
 * on tablets where it floats bottom-right — lift the toasts and upload progress above it
 * (`TOAST_LIFT_VAR`) so they never cover each other. A card docked in the sidebar shares nothing.
 */
function useLiftToasts(ref: RefObject<HTMLElement | null>, active: boolean, key: unknown) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const el = ref.current;
    if (!active || !el) {
      root.style.removeProperty(TOAST_LIFT_VAR);
      return;
    }
    const update = () => {
      const r = el.getBoundingClientRect();
      const phone = !window.matchMedia?.("(min-width: 768px)").matches;
      const shares = phone || r.right + 8 > window.innerWidth - TOAST_COLUMN;
      root.style.setProperty(TOAST_LIFT_VAR, shares && r.height ? `${Math.ceil(r.height) + 8}px` : "0px");
    };
    update();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    ro?.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", update);
      root.style.removeProperty(TOAST_LIFT_VAR);
    };
  }, [ref, active, key]);
}

/** The sidebar dock (rendered by the expanded desktop sidebar), when it has room for the card. */
function useDock(): HTMLElement | null {
  const [dock, setDock] = useState<HTMLElement | null>(null);
  const [roomy, setRoomy] = useState(false);
  useEffect(() => {
    const find = () => setDock(document.getElementById(TOUR_DOCK_ID));
    find();
    const mo = new MutationObserver(find);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);
  useEffect(() => {
    if (!dock) return;
    const measure = () => setRoomy(dock.clientHeight >= MIN_DOCK_HEIGHT);
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(dock);
    window.addEventListener("resize", measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [dock]);
  return dock && roomy ? dock : null;
}

/** A popover ("Why this date?", Pay…) is open somewhere. */
function usePopoverOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const root = getOverlayRoot();
    const check = () => setOpen(Boolean(root.querySelector("[data-popover]")));
    check();
    const mo = new MutationObserver(check);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);
  return open;
}

/** A letter is being read right now (its stepper needs the space). */
function useReadingLetter(): boolean {
  const { jobs } = useEvents();
  return Object.values(jobs).some((j) => j.status === "queued" || j.status === "running" || j.status === "waiting");
}

/**
 * Moves the tour from "You have new mail" to "An idea just arrived" when a letter from the tray
 * brought a real Idea (a price increase, a scam warning…) — not when reading a letter only bumped
 * housekeeping Ideas such as "Add your 27 dates to your calendar". Ideas already there when the step
 * began don't count, so going back to step 1 doesn't bounce forward again.
 */
function useIdeaArrival(active: boolean, onArrive: () => void) {
  const { ideas, ready } = useNewMailIdeas(active);
  const baseline = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!active) {
      baseline.current = null;
      return;
    }
    if (!ready) return; // the baseline is what was there once everything had loaded
    const ids = ideas.map((s) => s.id);
    if (baseline.current === null) {
      baseline.current = new Set(ids);
      return;
    }
    if (ids.some((id) => !baseline.current!.has(id))) onArrive();
  }, [active, ready, ideas, onArrive]);
}

interface CardProps {
  step: TourStep;
  stepIndex: number;
  here: boolean;
  compact?: boolean;
  headingRef: RefObject<HTMLHeadingElement | null>;
  go: (ev: TourEvent) => void;
  onShow: () => void;
  onMinimise: () => void;
  onSkip: () => void;
}

/** The step's title, text, dots and buttons (floating card and sidebar dock). */
function CardContent({ step, stepIndex, here, compact, headingRef, go, onShow, onMinimise, onSkip }: CardProps) {
  const last = stepIndex === TOUR_STEPS.length - 1;
  const primary = here ? (
    <Button size="sm" variant="primary" iconRight={last ? Check : ArrowRight} onClick={() => go({ type: "next" })} className={cn(compact && "w-full")}>
      {last ? "Finish" : "Next"}
    </Button>
  ) : (
    <Button size="sm" variant="primary" iconRight={ArrowRight} onClick={onShow} className={cn(compact && "w-full")}>
      {step.showLabel}
    </Button>
  );
  const dots = (
    <ol className="-ml-1.5 flex flex-1 items-center" aria-label={`Step ${stepIndex + 1} of ${TOUR_STEPS.length}`}>
      {TOUR_STEPS.map((s, i) => (
        <li key={s.id}>
          {/* a small dot, but a 24 px target (WCAG 2.5.8) */}
          <button
            type="button"
            onClick={() => go({ type: "goto", step: i })}
            aria-label={`Step ${i + 1}: ${s.title}`}
            aria-current={i === stepIndex ? "step" : undefined}
            className="grid h-6 min-w-6 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <span
              aria-hidden
              className={cn(
                "block h-1.5 rounded-full transition-all duration-300 motion-reduce:transition-none",
                i === stepIndex ? "w-5 bg-accent" : i < stepIndex ? "w-1.5 bg-accent/50" : "w-1.5 bg-line-strong",
              )}
            />
          </button>
        </li>
      ))}
    </ol>
  );
  return (
    <>
      <div className="flex items-center gap-2">
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent-soft text-accent">
          <Compass className="size-3.5" aria-hidden />
        </span>
        <p className="min-w-0 flex-1 truncate text-[11.5px] font-semibold uppercase tracking-[0.08em] text-accent">
          {compact ? "Tour" : "Demo tour"}{" "}
          <span className="font-medium text-muted tabular-nums">
            · {stepIndex + 1}
            {compact ? "/" : " of "}
            {TOUR_STEPS.length}
          </span>
        </p>
        <IconButton icon={Minus} label="Minimise the tour" size="sm" onClick={onMinimise} />
        <IconButton icon={X} label="Skip the tour" size="sm" onClick={onSkip} className="-mr-1.5" />
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={step.id}
          initial={{ opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -8 }}
          transition={{ duration: 0.18 }}
          aria-live="polite"
        >
          <h2
            ref={headingRef}
            tabIndex={-1}
            className={cn("display mt-2 font-semibold leading-snug outline-none", compact ? "text-[17px]" : "text-[19px]")}
          >
            {step.title}
          </h2>
          <p className={cn("mt-1 leading-relaxed text-muted", compact ? "text-[12.5px]" : "text-[13.5px]")}>{step.body}</p>
        </motion.div>
      </AnimatePresence>

      {compact ? (
        <>
          <div className="mt-3">{primary}</div>
          <div className="mt-2 flex items-center gap-1">
            {dots}
            {stepIndex > 0 ? <IconButton icon={ArrowLeft} label="Previous step" size="sm" onClick={() => go({ type: "back" })} /> : null}
          </div>
        </>
      ) : (
        <div className="mt-4 flex items-center gap-2">
          {dots}
          {stepIndex > 0 ? <IconButton icon={ArrowLeft} label="Previous step" size="sm" onClick={() => go({ type: "back" })} /> : null}
          {primary}
        </div>
      )}
      {!here ? (
        <button
          type="button"
          onClick={() => go({ type: "next" })}
          className="mt-2 text-[12px] font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          {last ? "Finish the tour" : "Skip this step"}
        </button>
      ) : null}
    </>
  );
}

/**
 * Stacking: the floating card (z-45) floats over the page and the tab bar but under dialogs,
 * drawers (z-50) and popovers (z-60); toasts (z-80) are lifted above it (see `useLiftToasts`).
 *
 * The demo tour (demo mode only): four skippable steps — New mail → Idea → Ask → Timeline. "Show
 * me" navigates to the step's page; the element gets a subtle spotlight (`data-tour` attribute, see
 * `steps.ts`). Where it sits, so it never covers what it talks about:
 * - desktop with the sidebar open: docked in the sidebar's free space (`#tour-dock`);
 * - tablets / a collapsed sidebar: a card at the bottom right;
 * - phones: a one-line bar above the tab bar (tap it for the whole card).
 * While a letter is being read or a popover is open, a floating card shrinks to its pill. The
 * person's own "minimise" is remembered. Mounted once by the app shell.
 */
export function DemoTour() {
  const { state, visible, send } = useTourController();
  const location = useLocation();
  const navigate = useNavigate();
  const tabletUp = useIsTabletUp();
  const dock = useDock();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [minimised, setMinimised] = useLocalStorage("ordnung.tour.minimised", false);
  const [phoneOpen, setPhoneOpen] = useState(false);
  const cardRef = useRef<HTMLElement | null>(null);
  const reading = useReadingLetter();
  const popover = usePopoverOpen();

  const stepIndex = state?.step ?? 0;
  const step = TOUR_STEPS[stepIndex]!;
  const here = visible && onStepRoute(step, location.pathname);
  const rect = useSpotlight(step.target, here);
  const docked = Boolean(dock) && tabletUp;
  const busy = !docked && (reading || popover);
  const pill = minimised || (busy && !(phoneOpen && !tabletUp));
  const bar = !tabletUp && !phoneOpen && !pill;

  useLiftToasts(cardRef, visible && Boolean(state) && !docked, `${minimised}:${busy}:${bar}:${phoneOpen}:${stepIndex}:${tabletUp}`);

  const onArrive = useCallback(() => send({ type: "idea-arrived" }), [send]);
  useIdeaArrival(visible && stepIndex === 0, onArrive);

  // Move focus to the new step's title only when the person used the card's own buttons.
  const focusNext = useRef(false);
  useEffect(() => {
    if (focusNext.current) {
      focusNext.current = false;
      headingRef.current?.focus({ preventScroll: true });
    }
  }, [stepIndex]);

  const go = (ev: TourEvent) => {
    focusNext.current = true;
    if (ev.type === "next" && stepIndex === TOUR_STEPS.length - 1) {
      toast({
        title: "That's the tour",
        description: "Everything here is Sam's sample life — open any letter, draft a reply or ask a question. Nothing is sent anywhere.",
      });
    }
    send(ev);
  };

  if (!visible || !state) return null;

  const spotlight = <AnimatePresence>{rect ? <Spotlight key={step.id} rect={rect} target={step.target} /> : null}</AnimatePresence>;
  const setCard = (el: HTMLElement | null) => {
    cardRef.current = el;
  };
  const content = (compact: boolean) => (
    <CardContent
      step={step}
      stepIndex={stepIndex}
      here={here}
      compact={compact}
      headingRef={headingRef}
      go={go}
      onShow={() => navigate(step.route)}
      onMinimise={() => {
        if (!tabletUp) setPhoneOpen(false);
        else setMinimised(true);
      }}
      onSkip={() => send({ type: "skip" })}
    />
  );
  const pillLabel = `Resume the demo tour, step ${stepIndex + 1} of ${TOUR_STEPS.length}: ${step.title}`;

  if (docked && dock) {
    return (
      <>
        {createPortal(spotlight, getOverlayRoot())}
        {createPortal(
          minimised ? (
            <button
              type="button"
              onClick={() => setMinimised(false)}
              className="inline-flex h-9 w-full items-center gap-2 rounded-full border border-line bg-surface pl-2 pr-3.5 text-[13px] font-medium text-ink shadow-[var(--shadow-card)] hover:bg-surface-2"
              aria-label={pillLabel}
            >
              <span className="grid size-6 place-items-center rounded-full bg-accent-soft text-accent">
                <Compass className="size-3.5" aria-hidden />
              </span>
              Demo tour · {stepIndex + 1} of {TOUR_STEPS.length}
            </button>
          ) : (
            <motion.aside
              aria-label="Demo tour"
              data-docked=""
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="rounded-xl border border-line bg-surface p-3.5 text-ink shadow-[var(--shadow-card)]"
            >
              {content(true)}
            </motion.aside>
          ),
          dock,
        )}
      </>
    );
  }

  if (pill) {
    return createPortal(
      <motion.button
        ref={setCard}
        type="button"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        onClick={() => {
          setMinimised(false);
          if (!tabletUp) setPhoneOpen(true);
        }}
        className="fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom))] left-3 z-[45] inline-flex h-9 items-center gap-2 rounded-full border border-line bg-surface pl-2 pr-3.5 text-[13px] font-medium text-ink shadow-[var(--shadow-pop)] hover:bg-surface-2 md:bottom-5 md:left-auto md:right-5"
        aria-label={pillLabel}
      >
        <span className="grid size-6 place-items-center rounded-full bg-accent-soft text-accent">
          <Compass className="size-3.5" aria-hidden />
        </span>
        Demo tour · {stepIndex + 1} of {TOUR_STEPS.length}
      </motion.button>,
      getOverlayRoot(),
    );
  }

  if (bar) {
    const last = stepIndex === TOUR_STEPS.length - 1;
    return createPortal(
      <>
        {spotlight}
        <motion.aside
          ref={setCard}
          aria-label="Demo tour"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed inset-x-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-[45] flex h-12 items-center gap-1.5 rounded-full border border-line bg-surface pl-1.5 pr-1.5 text-ink shadow-[var(--shadow-pop)]"
        >
          <button
            type="button"
            onClick={() => setPhoneOpen(true)}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-full py-1.5 pl-1 pr-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label={`Demo tour, step ${stepIndex + 1} of ${TOUR_STEPS.length}: ${step.title}. Show the whole step`}
          >
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
              <Compass className="size-3.5" aria-hidden />
            </span>
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
              <span className="text-muted tabular-nums">
                {stepIndex + 1}/{TOUR_STEPS.length} ·{" "}
              </span>
              {step.title}
            </span>
            <ChevronUp className="size-4 shrink-0 text-muted" aria-hidden />
          </button>
          {here ? (
            <Button size="sm" variant="primary" iconRight={last ? Check : ArrowRight} onClick={() => go({ type: "next" })} className="rounded-full">
              {last ? "Finish" : "Next"}
            </Button>
          ) : (
            <Button size="sm" variant="primary" iconRight={ArrowRight} onClick={() => navigate(step.route)} className="rounded-full">
              Show me
            </Button>
          )}
        </motion.aside>
      </>,
      getOverlayRoot(),
    );
  }

  return createPortal(
    <>
      {spotlight}
      <motion.aside
        ref={setCard}
        aria-label="Demo tour"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 380, damping: 34 }}
        className={cn(
          "fixed z-[45] rounded-2xl border border-line bg-surface p-4 text-ink shadow-[var(--shadow-pop)]",
          "inset-x-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] md:inset-x-auto md:bottom-5 md:right-5 md:w-[22rem]",
        )}
      >
        {content(false)}
      </motion.aside>
    </>,
    getOverlayRoot(),
  );
}
