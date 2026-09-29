import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type Ref, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, Compass, Minus, X } from "lucide-react";
import { useMailTray } from "@/api/hooks";
import { useEvents } from "@/api/sse";
import { Button, IconButton } from "@/components/ui/Button";
import { getOverlayRoot } from "@/components/ui/internal";
import { TOAST_LIFT_VAR, toast } from "@/components/ui/Toast";
import { useIsTabletUp, useLocalStorage, useMediaQuery } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { MORE_TO_TRY, TOUR_DOCK_ID, TOUR_STEPS, onStepRoute, stepCopy, type TourFacts, type TourStep } from "./steps";
import type { TourEvent } from "./tourMachine";
import { onTourRestart, useTourController } from "./useTourController";
import { spotlitElement, useSpotlight, type SpotRect } from "./useSpotlight";
import { useNewMailIdeas } from "./newMail";

const TOTAL = TOUR_STEPS.length;

/**
 * CSS variable (on `<html>`), phones: how far the tour (its bar, pill or open card) reaches above
 * the tab bar — its height plus the 12 px between them. The page pads its end, focus scrolling
 * and bottom-pinned controls by it (index.css `.room-for-overlays`, `scroll-padding-bottom`).
 */
export const TOUR_BAR_VAR = "--ordnung-tour-bar";
/**
 * CSS variable (on `<html>`), tablets and up: how far the floating tour card, bar or pill reaches up
 * from the bottom of the screen (its height plus its 20 px margin). Unset while it is docked.
 */
export const TOUR_CLEARANCE_VAR = "--ordnung-tour-clearance";
/** The space between the phone tab bar and the tour bar above it (`bottom-[4.75rem]` over `h-16`). */
const BAR_GAP = 12;

/** The dock's own padding (`py-3`): the card docks only when it fits inside it. */
const DOCK_PADDING = 24;
/** The minimised pill (`h-9`). */
const PILL_HEIGHT = 36;
/**
 * Room for the whole card floating over the page. Below it (phones, tablets, short laptops) the
 * tour is a slim bar that opens into the card on request.
 */
const ROOMY = "(min-width: 1024px) and (min-height: 800px)";
/** Steps whose page was already scrolled to its highlighted element in this session. */
const SCROLLED_KEY = "ordnung.tour.scrolled";

/** "Demo tour · 2 of 4" — the one way the tour says where you are. */
const where = (index: number) => `Demo tour · ${index + 1} of ${TOTAL}`;

function readScrolled(): string[] {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(SCROLLED_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeScrolled(ids: string[]) {
  try {
    sessionStorage.setItem(SCROLLED_KEY, JSON.stringify(ids));
  } catch {
    /* storage unavailable: the page may scroll again, nothing worse */
  }
}

/**
 * Soft ring around the element the current step talks about: two gentle pulses, then still (WCAG
 * 2.2.2 — nothing moves on its own for longer than 5 s). Drawn under the sticky bars, the Ask
 * composer (z-10) and every overlay: it marks the page, it never covers a control.
 */
function Spotlight({ rect, target }: { rect: SpotRect; target: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      aria-hidden
      data-testid="tour-spotlight"
      data-target={target}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      className="pointer-events-none fixed z-[5] rounded-[calc(var(--radius-card)+8px)] ring-2 ring-accent/70"
      style={{
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        boxShadow: "0 0 0 6px color-mix(in srgb, var(--color-accent) 14%, transparent)",
      }}
    >
      {!reduce ? (
        <motion.span
          data-testid="tour-spotlight-pulse"
          className="absolute inset-0 rounded-[inherit] ring-2 ring-accent/50"
          initial={{ opacity: 0 }}
          animate={{ opacity: [0.7, 0], scale: [1, 1.025] }}
          transition={{ duration: 1.8, repeat: 1, ease: "easeOut" }}
        />
      ) : null}
    </motion.div>
  );
}

/** Width of the toast column on tablets and up (toasts and upload cards, 400 px) + its margin. */
const TOAST_COLUMN = 400 + 20;

/**
 * While the tour floats over the page (not docked in the sidebar), tell the page how much of its
 * bottom edge it covers: {@link TOUR_BAR_VAR} on phones, {@link TOUR_CLEARANCE_VAR} from tablets
 * up. Where it shares the bottom edge with the toast column (always on phones, on tablets where it
 * floats bottom-right) it also lifts the toasts and upload progress above itself
 * (`TOAST_LIFT_VAR`), so they never cover each other. Everything is cleared when it docks or goes.
 */
function useBottomRoom(ref: RefObject<HTMLElement | null>, active: boolean, key: unknown) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const clearRoom = () => {
      root.style.removeProperty(TOUR_BAR_VAR);
      root.style.removeProperty(TOUR_CLEARANCE_VAR);
    };
    const el = ref.current;
    if (!active || !el) {
      root.style.removeProperty(TOAST_LIFT_VAR);
      clearRoom();
      return;
    }
    const update = () => {
      const r = el.getBoundingClientRect();
      const height = Math.ceil(r.height);
      const phone = !window.matchMedia?.("(min-width: 768px)").matches;
      const shares = phone || r.right + 8 > window.innerWidth - TOAST_COLUMN;
      root.style.setProperty(TOAST_LIFT_VAR, shares && height ? `${height + 8}px` : "0px");
      if (!height) return clearRoom();
      if (phone) {
        root.style.setProperty(TOUR_BAR_VAR, `${height + BAR_GAP}px`);
        root.style.removeProperty(TOUR_CLEARANCE_VAR);
      } else {
        // its fixed `bottom` offset, not the rectangle's top (the entrance animation moves that)
        const offset = parseFloat(window.getComputedStyle(el).bottom) || 0;
        root.style.setProperty(TOUR_CLEARANCE_VAR, `${height + Math.max(0, offset)}px`);
        root.style.removeProperty(TOUR_BAR_VAR);
      }
    };
    update();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    ro?.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", update);
      root.style.removeProperty(TOAST_LIFT_VAR);
      clearRoom();
    };
  }, [ref, active, key]);
}

/**
 * The sidebar dock (rendered by the expanded desktop sidebar), and how tall it is. Layout effects:
 * where the card goes is settled before the first paint.
 */
function useDock(): { dock: HTMLElement | null; room: number } {
  const [dock, setDock] = useState<HTMLElement | null>(null);
  const [room, setRoom] = useState(0);
  useLayoutEffect(() => {
    const find = () => setDock(document.getElementById(TOUR_DOCK_ID));
    find();
    const mo = new MutationObserver(find);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);
  useLayoutEffect(() => {
    if (!dock) return;
    const measure = () => setRoom(dock.clientHeight);
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(dock);
    window.addEventListener("resize", measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [dock]);
  return { dock, room: dock ? room : 0 };
}

/**
 * The docked card's height per step (text and buttons differ), measured while it is docked, and
 * the last one measured (the guess for a step not docked yet).
 */
function useDockedHeights(card: HTMLElement | null, key: string): { byKey: Record<string, number>; last: number } {
  const [heights, setHeights] = useState<{ byKey: Record<string, number>; last: number }>({ byKey: {}, last: 0 });
  useLayoutEffect(() => {
    if (!card) return;
    const measure = () => {
      const h = Math.ceil(card.getBoundingClientRect().height);
      if (!h) return;
      setHeights((m) => (m.byKey[key] === h && m.last === h ? m : { byKey: { ...m.byKey, [key]: h }, last: h }));
    };
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(card);
    return () => ro?.disconnect();
  }, [card, key]);
  return heights;
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
 * Moves the tour from "You have new mail" to the Idea step when a letter from the tray brought a
 * real Idea (a price increase, a scam warning…) — not when reading a letter only bumped
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

/** What the demo's data says for the step texts (see `stepCopy`). */
function useTourFacts(enabled: boolean): TourFacts {
  const tray = useMailTray(enabled);
  const { ideas, ready } = useNewMailIdeas(enabled);
  return {
    tray: tray.data ? { unread: tray.data.filter((m) => !m.opened).length, total: tray.data.length } : undefined,
    ideaFromMail: ready ? ideas.length > 0 : undefined,
  };
}

interface CardProps {
  step: TourStep;
  steps: readonly TourStep[];
  stepIndex: number;
  here: boolean;
  /** The narrow card docked in the sidebar. */
  compact?: boolean;
  headingRef: Ref<HTMLHeadingElement>;
  go: (ev: TourEvent) => void;
  onShow: () => void;
  onMinimise: () => void;
  onEnd: () => void;
}

/** The step's title, text, dots and buttons (floating card and sidebar dock). */
function CardContent({ step, steps, stepIndex, here, compact, headingRef, go, onShow, onMinimise, onEnd }: CardProps) {
  const last = stepIndex === TOTAL - 1;
  // on its page, or its point made elsewhere (a letter was read): "Next" leads
  const primary = here || step.onward ? (
    <Button size="sm" variant="primary" iconRight={last ? Check : ArrowRight} onClick={() => go({ type: "next" })} className={cn(compact && "min-w-0 flex-1")}>
      {last ? "Finish" : "Next"}
    </Button>
  ) : (
    <Button size="sm" variant="primary" iconRight={ArrowRight} onClick={onShow} className={cn(compact && "min-w-0 flex-1")}>
      {step.showLabel}
    </Button>
  );
  const skip = !here ? (
    <button
      type="button"
      onClick={() => (step.onward ? onShow() : go({ type: "next" }))}
      className={cn(
        "-mr-1.5 inline-flex shrink-0 items-center rounded-md px-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface-3/70 hover:text-ink first:-ml-1.5",
        compact ? "h-6" : "h-7",
      )}
    >
      {step.onward ? step.showLabel : last ? "Finish the tour" : "Skip this step"}
    </button>
  ) : null;
  // the narrow docked card has no room for Back beside "Show me the Ideas": there the dots go back
  const back =
    stepIndex > 0 && (here || !compact) ? (
      <IconButton icon={ArrowLeft} label="Previous step" size="sm" variant={compact ? "secondary" : "ghost"} onClick={() => go({ type: "back" })} />
    ) : null;
  const dots = (
    <ol className="-ml-1.5 flex items-center" aria-label={`Steps (${stepIndex + 1} of ${TOTAL})`}>
      {steps.map((s, i) => {
        const name = `Step ${i + 1}: ${s.title}`;
        return (
          <li key={s.id}>
            {/* a small dot, but a 24 px target (WCAG 2.5.8); 3:1 against the card (1.4.11) */}
            <button
              type="button"
              onClick={() => go({ type: "goto", step: i })}
              aria-label={name}
              title={name}
              aria-current={i === stepIndex ? "step" : undefined}
              className="group grid h-6 min-w-6 place-items-center rounded-full outline-none transition-colors hover:bg-surface-3/70 focus-visible:ring-2 focus-visible:ring-accent"
            >
              <span
                aria-hidden
                className={cn(
                  "block h-1.5 rounded-full transition-all duration-300 motion-reduce:transition-none",
                  i === stepIndex ? "w-5 bg-accent" : i < stepIndex ? "w-1.5 bg-accent/75 group-hover:bg-accent" : "w-1.5 bg-muted/70 group-hover:bg-ink/80",
                )}
              />
            </button>
          </li>
        );
      })}
    </ol>
  );
  return (
    <>
      <div className={cn("flex items-center", compact ? "gap-1" : "gap-2")}>
        {!compact ? (
          <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent-soft text-accent">
            <Compass className="size-3.5" aria-hidden />
          </span>
        ) : null}
        <p className="eyebrow min-w-0 flex-1 whitespace-nowrap text-accent">
          Demo tour <span className="font-medium text-muted tabular-nums">· {stepIndex + 1} of {TOTAL}</span>
        </p>
        {/* 24 px targets in the narrow docked card, so "Demo tour · 2 of 4" keeps its room */}
        <div className={cn("-my-1 flex shrink-0 items-center gap-0.5", compact ? "-mr-1" : "-mr-2")}>
          <IconButton icon={Minus} label="Minimise the tour" size="sm" onClick={onMinimise} className={cn(compact && "size-6")} />
          <IconButton icon={X} label="End the tour" size="sm" onClick={onEnd} className={cn(compact && "size-6")} />
        </div>
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={step.id} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.18 }}>
          <h2 ref={headingRef} tabIndex={-1} className={cn("display mt-2 font-semibold leading-snug outline-none", compact ? "text-lg" : "text-[19px]")}>
            {step.title}
          </h2>
          <p className={cn("mt-1 text-muted", compact ? "text-sm leading-normal" : "text-base leading-relaxed")}>{step.body}</p>
          {last && compact ? (
            // the narrow docked card: one sentence of inline links (each hint is the link's title), so it still fits the sidebar at 1280×800
            <p className="mt-2 text-xs leading-4 text-muted">
              More to try:{" "}
              {MORE_TO_TRY.map((m, i) => (
                <Fragment key={m.label}>
                  {i > 0 ? ", " : null}
                  <Link to={m.to} title={m.hint} className="font-semibold text-accent underline-offset-2 hover:underline">
                    {m.label}
                  </Link>
                </Fragment>
              ))}
              .
            </p>
          ) : last ? (
            <div className="mt-2.5">
              <p className="eyebrow text-muted">More to try</p>
              <ul aria-label="More to try" className="mt-1 space-y-0.5 text-sm">
                {MORE_TO_TRY.map((m) => (
                  <li key={m.label} className="leading-snug">
                    <Link to={m.to} className="inline-flex min-h-6 items-center font-semibold text-accent underline-offset-2 hover:underline">
                      {m.label}
                    </Link>
                    <span className="text-muted"> — {m.hint}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </motion.div>
      </AnimatePresence>

      {compact ? (
        <>
          <div className="mt-2.5 flex items-center justify-between gap-2">
            {dots}
            {skip}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            {back}
            {primary}
          </div>
        </>
      ) : (
        <>
          <div className="mt-4 flex items-center gap-2">
            <div className="min-w-0 flex-1">{dots}</div>
            {back}
            {primary}
          </div>
          {skip ? <div className="mt-2">{skip}</div> : null}
        </>
      )}
    </>
  );
}

/** The compass mark and "Demo tour · 2 of 4" of the pill (docked or floating). */
function PillLabel({ stepIndex }: { stepIndex: number }) {
  return (
    <>
      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
        <Compass className="size-3.5" aria-hidden />
      </span>
      <span className="truncate">{where(stepIndex)}</span>
    </>
  );
}

/**
 * Stacking: the floating card (z-45) floats over the page and the tab bar but under dialogs,
 * drawers (z-50) and popovers (z-60); toasts (z-80) are lifted above it (see `useBottomRoom`).
 *
 * The demo tour (demo mode only): four skippable steps — New mail → Ideas → Ask → Timeline. "Show
 * me" navigates to the step's page; the element gets a subtle spotlight (`data-tour` attribute, see
 * `steps.ts`), scrolled into view once per step. Where it sits, so it never covers what it talks
 * about:
 * - laptops with the sidebar open: docked in the sidebar's free space (`#tour-dock`) when the
 *   whole card fits there;
 * - a wide and tall screen otherwise (collapsed sidebar): a card at the bottom right — for a step
 *   whose highlighted element it would cover, the slim bar instead;
 * - phones, tablets and short laptops: a slim bar (above the tab bar on phones, bottom right from
 *   tablets up); tap it for the whole card.
 * While floating it tells the page how much it covers (`TOUR_BAR_VAR`, `TOUR_CLEARANCE_VAR`), so
 * the page's end, focused controls and popovers stay clear of it. While a letter is being read or a
 * popover is open, a floating card shrinks to its pill. The person's own "minimise" is remembered.
 *
 * Keyboard: the floating forms sit right after the sidebar (before the page); every action leaves
 * focus somewhere useful — the new step's title, the pill or bar after Minimise (or Escape), the
 * page after End or Finish. Step changes the person didn't make with the card are announced.
 * Mounted once by the app shell.
 */
export function DemoTour() {
  const { state, visible, send } = useTourController();
  const location = useLocation();
  const navigate = useNavigate();
  const tabletUp = useIsTabletUp();
  const roomy = useMediaQuery(ROOMY);
  const { dock, room } = useDock();
  const [minimised, setMinimised] = useLocalStorage("ordnung.tour.minimised", false);
  /** Phones, tablets and short screens: the bar opened into the whole card. */
  const [expanded, setExpanded] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const cardRef = useRef<HTMLElement | null>(null);
  const [dockedCard, setDockedCard] = useState<HTMLElement | null>(null);
  const reading = useReadingLetter();
  const popover = usePopoverOpen();
  const facts = useTourFacts(visible);

  const stepIndex = state?.step ?? 0;
  const steps = TOUR_STEPS.map((s) => stepCopy(s, facts));
  const step = steps[stepIndex]!;
  const here = visible && onStepRoute(step, location.pathname);

  // Docked only when the whole card (or the pill) fits in the dock's free space.
  const heightKey = `${step.id}:${here ? "here" : "away"}`;
  const heights = useDockedHeights(dockedCard, heightKey);
  const need = minimised ? PILL_HEIGHT : (heights.byKey[heightKey] ?? heights.last);
  const docked = tabletUp && dock !== null && room - DOCK_PADDING >= need;
  // The step whose highlighted element the floating card turned out to cover: for that step it
  // steps aside to the slim bar (until the person opens it again).
  const [coveredStep, setCoveredStep] = useState<string | null>(null);
  const compactForm = !docked && (!roomy || coveredStep === step.id);
  const busy = !docked && (reading || popover);
  const pill = minimised || (busy && !(compactForm && expanded));
  const bar = compactForm && !expanded && !pill;
  const floatingCard = !docked && !pill && !bar;

  const rect = useSpotlight(step.target, here && !pill, {
    scroll: () => !readScrolled().includes(step.id),
    onScrolled: () => writeScrolled([...new Set([...readScrolled(), step.id])]),
  });

  useBottomRoom(cardRef, visible && Boolean(state) && !docked, `${minimised}:${busy}:${bar}:${expanded}:${stepIndex}:${tabletUp}:${roomy}`);

  const stepAside = useCallback((id: string) => setCoveredStep(id), []);
  useLayoutEffect(() => {
    // (re-checked whenever the ring moves; the element (or its part) itself, not the ring kept clear of the card)
    if (!floatingCard || compactForm || !rect) return;
    const c = cardRef.current?.getBoundingClientRect();
    const t = spotlitElement(step.target)?.getBoundingClientRect();
    if (!c?.height || !t?.height) return;
    const across = Math.min(c.right, t.right) - Math.max(c.left, t.left);
    const down = Math.min(c.bottom, t.bottom) - Math.max(c.top, t.top);
    if (across > 8 && down > 8) stepAside(step.id);
  }, [floatingCard, compactForm, rect, step.id, step.target, stepAside]);

  const onArrive = useCallback(() => send({ type: "idea-arrived" }), [send]);
  useIdeaArrival(visible && stepIndex === 0, onArrive);

  // ---- focus -------------------------------------------------------------------------------------
  // After an action that swaps what is on screen (a new step's text, the card for its pill or bar),
  // the next tour control to appear takes focus: the new title, the pill or the bar.
  const focusUntil = useRef(0);
  const requestFocus = () => {
    focusUntil.current = Date.now() + 1500;
  };
  const takeFocus = useCallback((el: HTMLElement | null) => {
    if (!el || focusUntil.current < Date.now()) return;
    focusUntil.current = 0;
    el.focus({ preventScroll: true });
  }, []);
  const focusPage = () => document.getElementById("main")?.focus({ preventScroll: true });
  const setCard = useCallback((el: HTMLElement | null) => {
    cardRef.current = el;
  }, []);
  const setPill = useCallback(
    (el: HTMLElement | null) => {
      cardRef.current = el;
      takeFocus(el);
    },
    [takeFocus],
  );

  // Restarted (the Demo badge, a toast): open the whole card again, focus its title, and let every
  // step scroll to its element once more.
  useEffect(
    () =>
      onTourRestart(() => {
        focusUntil.current = Date.now() + 1500;
        setMinimised(false);
        setExpanded(true);
        writeScrolled([]);
      }),
    [setMinimised],
  );

  // Step changes the person didn't make with the card's buttons (a letter brought an Idea, the bar,
  // another tab) are read out; after the card's own buttons the new title takes focus instead.
  const shown = useRef<{ visible: boolean; step: number } | null>(null);
  const announce = useCallback((text: string) => setAnnouncement(text), []);
  useEffect(() => {
    if (!state) return;
    const before = shown.current;
    shown.current = { visible, step: stepIndex };
    if (!visible || !before || (before.visible && before.step === stepIndex)) return;
    if (focusUntil.current >= Date.now()) return;
    announce(`${before.visible ? "" : "Demo tour restarted. "}${where(stepIndex)}: ${step.title}`);
  }, [state, visible, stepIndex, step.title, announce]);

  if (!visible || !state) return null;

  // ---- actions -----------------------------------------------------------------------------------
  const finish = () => {
    send({ type: "finish" });
    focusPage();
    toast({
      title: "That's the tour",
      description: "Everything here is Sam's sample life — open any letter, draft a reply or ask a question. Nothing is sent anywhere.",
      action: { label: "Restart the tour", onClick: () => send({ type: "restart" }) },
    });
  };
  const end = () => {
    const at = stepIndex;
    send({ type: "skip" });
    focusPage();
    toast({
      title: "Tour hidden",
      // Settings exists at every width (the top bar's Demo badge doesn't fit below 360 px)
      description: "You can restart it any time in Settings → Data.",
      // back where it was
      undo: () => send({ type: "restart", step: at }),
    });
  };
  /** Next, Back or a dot on the card: the new step's title takes focus. */
  const go = (ev: TourEvent) => {
    if (ev.type === "next" && stepIndex === TOTAL - 1) return finish();
    requestFocus();
    send(ev);
  };
  const show = () => {
    // "Show me" always brings the element into view, even when this step scrolled there before
    writeScrolled(readScrolled().filter((id) => id !== step.id));
    navigate(step.route);
  };
  const minimise = () => {
    requestFocus();
    if (compactForm) setExpanded(false);
    else setMinimised(true);
  };
  const resume = () => {
    requestFocus();
    setMinimised(false);
    if (compactForm) setExpanded(true);
  };
  const onCardKey = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    e.preventDefault();
    minimise();
  };

  const live = (
    <p className="sr-only" role="status" aria-live="polite">
      {announcement}
    </p>
  );
  const spotlight = <AnimatePresence>{rect ? <Spotlight key={step.id} rect={rect} target={step.target} /> : null}</AnimatePresence>;
  const overlay = createPortal(
    <>
      {live}
      {spotlight}
    </>,
    getOverlayRoot(),
  );
  const content = (compact: boolean) => (
    <CardContent
      step={step}
      steps={steps}
      stepIndex={stepIndex}
      here={here}
      compact={compact}
      headingRef={takeFocus}
      go={go}
      onShow={show}
      onMinimise={minimise}
      onEnd={end}
    />
  );
  // starts with what the pill shows (WCAG 2.5.3), then what it does
  const pillLabel = `${where(stepIndex)} — resume: ${step.title}`;

  if (docked && dock) {
    return (
      <>
        {overlay}
        {createPortal(
          minimised ? (
            <button
              ref={takeFocus}
              type="button"
              onClick={resume}
              aria-expanded={false}
              aria-label={pillLabel}
              className="inline-flex h-9 w-full shrink-0 items-center gap-2 rounded-full border border-line bg-surface pl-1.5 pr-3.5 text-sm font-medium text-ink shadow-[var(--shadow-card)] transition-colors hover:bg-surface-2"
            >
              <PillLabel stepIndex={stepIndex} />
            </button>
          ) : (
            <motion.section
              ref={setDockedCard}
              aria-label="Demo tour"
              data-docked=""
              onKeyDown={onCardKey}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="shrink-0 rounded-[var(--radius-card)] border border-line bg-surface p-3 text-ink shadow-[var(--shadow-card)]"
            >
              {content(true)}
            </motion.section>
          ),
          dock,
        )}
      </>
    );
  }

  if (pill) {
    return (
      <>
        {overlay}
        <motion.button
          ref={setPill}
          type="button"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={resume}
          aria-expanded={false}
          aria-label={pillLabel}
          className="fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom))] left-3 z-[45] inline-flex h-9 max-w-[calc(100vw-1.5rem)] items-center gap-2 rounded-full border border-line bg-surface pl-1.5 pr-3.5 text-sm font-medium text-ink shadow-[var(--shadow-pop)] transition-colors hover:bg-surface-2 md:bottom-5 md:left-auto md:right-5"
        >
          <PillLabel stepIndex={stepIndex} />
        </motion.button>
      </>
    );
  }

  if (bar) {
    const last = stepIndex === TOTAL - 1;
    const label = here ? (last ? "Finish" : "Next") : "Show me";
    return (
      <>
        {overlay}
        <motion.section
          ref={setCard}
          aria-label="Demo tour"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed inset-x-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-[45] flex items-center gap-1.5 rounded-full border border-line bg-surface p-1.5 text-ink shadow-[var(--shadow-pop)] md:inset-x-auto md:bottom-5 md:right-5 md:w-[22rem]"
        >
          <button
            ref={takeFocus}
            type="button"
            onClick={resume}
            aria-expanded={false}
            // starts with what the bar shows (WCAG 2.5.3), then what it does
            aria-label={`${where(stepIndex)}: ${step.title} — show the whole step`}
            className="flex min-w-0 flex-1 items-center gap-2.5 rounded-full py-0.5 pl-0.5 pr-2 text-left outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
              <Compass className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="eyebrow block truncate leading-4 text-accent">
                Demo tour <span className="font-medium text-muted tabular-nums">· {stepIndex + 1} of {TOTAL}</span>
              </span>
              <span className="block truncate text-base font-medium leading-5 text-ink">{step.title}</span>
            </span>
          </button>
          <Button
            size="sm"
            variant="primary"
            iconRight={here && last ? Check : ArrowRight}
            onClick={here ? () => (last ? finish() : send({ type: "next" })) : show}
            // under 360 px the title needs the room: the arrow alone (its name stays)
            className="rounded-full max-[359px]:w-8 max-[359px]:gap-0 max-[359px]:px-0"
          >
            <span className="max-[359px]:sr-only">{label}</span>
          </Button>
        </motion.section>
      </>
    );
  }

  return (
    <>
      {overlay}
      <motion.section
        ref={setCard}
        aria-label="Demo tour"
        onKeyDown={onCardKey}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 380, damping: 34 }}
        className={cn(
          "fixed z-[45] overflow-y-auto overscroll-contain rounded-[var(--radius-card)] border border-line bg-surface p-4 text-ink shadow-[var(--shadow-pop)] scrollbar-thin",
          "inset-x-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] max-h-[calc(100dvh-9rem-env(safe-area-inset-bottom))]",
          "md:inset-x-auto md:bottom-5 md:right-5 md:max-h-[calc(100dvh-5.5rem)] md:w-[22rem]",
        )}
      >
        {content(false)}
      </motion.section>
    </>
  );
}
