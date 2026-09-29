import { useLayoutEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface StepperStep {
  id: string;
  label: string;
  /** A shorter label for tight rows ("Dates" for "Computing dates"). */
  short?: string;
}

export interface StepperProps {
  steps: readonly StepperStep[];
  /** Index of the active step; `steps.length` means everything is done. */
  current: number;
  /** `error` marks the current step as failed. */
  status?: "active" | "error";
  size?: "sm" | "md";
  /**
   * Which labels to show: all (centred under each dot), current (one line below) or none. `all`
   * falls back to the short labels, then to `fallback`, when the labels would run into each other.
   */
  labels?: "all" | "current" | "none";
  /**
   * What `labels="all"` becomes when even the short labels don't fit (default `current`). `stagger`:
   * the short labels over two lines, every other one on the second (steps a person jumps between keep
   * a name under each dot), and `current` when even that doesn't fit.
   */
  fallback?: "current" | "none" | "stagger";
  /** Announce step changes politely to screen readers. */
  live?: boolean;
  /** Accessible name, e.g. "Reading Nebenkostenabrechnung.pdf". */
  label?: string;
  /**
   * The ids of the steps that count as done, for steps taken in any order (a review the person can
   * jump around in): only these get a tick. Default: every step before the current one.
   */
  doneIds?: ReadonlySet<string>;
  /**
   * Steps the person can jump to (a review taken in any order): each dot and its label become a button
   * that calls this with the step's index; the current one carries `aria-current="step"`.
   */
  onPick?: (index: number) => void;
  className?: string;
}

type StepState = "done" | "current" | "error" | "todo";

/** A label's colour by its step's state. */
const LABEL_TONE: Record<StepState, string> = { current: "text-ink", error: "text-danger-ink", done: "text-ink/70", todo: "text-muted" };

/** Space kept between two neighbouring labels. */
const LABEL_GAP = 6;

/**
 * Do labels of these widths fit centred under equal columns `col` px wide? Each label may borrow
 * the room its neighbours leave, but two neighbours never touch and the outer ones stay inside.
 */
export function labelsFit(col: number, widths: readonly number[], gap = LABEL_GAP): boolean {
  if (!widths.length) return true;
  if (widths[0]! > col || widths[widths.length - 1]! > col) return false;
  return widths.every((w, i) => i === 0 || (widths[i - 1]! + w) / 2 + gap <= col);
}

/**
 * Do labels of these widths fit on two alternating lines (every other one on the second)? Neighbours
 * on a line are two columns apart; each label stays inside the row.
 */
export function staggeredLabelsFit(col: number, widths: readonly number[], gap = LABEL_GAP): boolean {
  const n = widths.length;
  return widths.every((w, i) => w / 2 <= Math.min(i + 0.5, n - i - 0.5) * col && (i < 2 || (widths[i - 2]! + w) / 2 + gap <= 2 * col));
}

/** Which labels a row of `width` px can show: the full ones, the short ones, the short ones over two
 * lines (only when `stagger`), or none. */
export function chooseStepLabels(width: number, full: readonly number[], short: readonly number[], stagger = false): "full" | "short" | "stagger" | null {
  const col = width / Math.max(1, full.length);
  if (labelsFit(col, full)) return "full";
  if (labelsFit(col, short)) return "short";
  if (stagger && staggeredLabelsFit(col, short)) return "stagger";
  return null;
}

/** Widths of `texts` in the font of `el` (a hidden probe inside it, removed straight away). */
function textWidths(texts: readonly string[], el: HTMLElement): number[] {
  const probe = document.createElement("span");
  probe.style.cssText = "position:absolute;left:0;top:0;visibility:hidden;white-space:nowrap";
  el.appendChild(probe);
  const widths = texts.map((t) => {
    probe.textContent = t;
    return probe.getBoundingClientRect().width;
  });
  probe.remove();
  return widths;
}

/**
 * The label mode that fits the stepper's own width (a card on a phone, the 400 px upload card, a
 * wide page): measured, not guessed from the viewport.
 */
function useFittingLabels(steps: readonly StepperStep[], wanted: boolean, stagger: boolean) {
  const ref = useRef<HTMLOListElement>(null);
  const [fit, setFit] = useState<"full" | "short" | "stagger" | null>("full");
  const key = steps.map((s) => `${s.label}|${s.short ?? ""}`).join("/");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!wanted || !el) return;
    const measure = () => {
      const width = el.clientWidth;
      if (!width) return; // not laid out (hidden, or jsdom)
      const full = textWidths(steps.map((s) => s.label), el);
      const short = textWidths(steps.map((s) => s.short ?? s.label), el);
      setFit(chooseStepLabels(width, full, short, stagger));
    };
    const raf = requestAnimationFrame(measure);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    // the web font changes every width once it has loaded
    void document.fonts?.ready.then(measure);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
    };
    // `key` stands for the labels (the array itself may be a new one each render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted, key, stagger]);
  return { ref, fit: wanted ? fit : null };
}

/**
 * Horizontal animated progress stepper (upload pipeline: Reading → Understanding → Checking →
 * Computing dates → Filing): one continuous track through equal-width columns, a dot per step and
 * 12 px labels. The labels measure themselves: when they would run into each other the short
 * labels are used, and when even those don't fit, one line under the track names the current step
 * (or nothing, with `fallback="none"`; or the short labels over two lines first, with
 * `fallback="stagger"`). Respects reduced motion via the global MotionConfig.
 */
export function Stepper({ steps, current, status = "active", size = "md", labels = "all", fallback = "current", live, label, doneIds, onPick, className }: StepperProps) {
  const n = steps.length;
  const done = current >= n;
  const dot = size === "sm" ? 16 : 20;
  const activeLabel = done ? "Done" : steps[current]?.label ?? "";
  const isDone = (i: number) => (doneIds ? doneIds.has(steps[i]!.id) : i < current);
  const stateOf = (i: number): StepState =>
    i === current && !done ? (status === "error" ? "error" : "current") : isDone(i) || done ? "done" : "todo";
  const { ref, fit } = useFittingLabels(steps, labels === "all", fallback === "stagger");
  const mode = labels === "all" ? (fit ?? (fallback === "stagger" ? "current" : fallback)) : labels;
  // the filled part of the track reaches the current dot
  const filled = n > 1 ? Math.min(Math.max(current, 0), n - 1) / (n - 1) : 0;
  // two lines of labels, each wider than its column: laid over the row (not inside the columns they
  // borrow room from), the columns keep the room they take under the dots
  const stagger = mode === "stagger";

  return (
    <div className={cn("w-full", className)}>
      <div className="relative">
        {n > 1 ? (
          <span
            aria-hidden
            data-testid="stepper-track"
            className="absolute h-0.5 overflow-hidden rounded-full bg-line"
            style={{ top: dot / 2 - 1, left: `${50 / n}%`, right: `${50 / n}%` }}
          >
            <motion.span
              className="absolute inset-y-0 left-0 bg-accent"
              initial={false}
              animate={{ width: `${filled * 100}%` }}
              transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
            />
          </span>
        ) : null}
        <ol ref={ref} aria-label={label ?? "Progress"} className="relative grid w-full text-xs font-medium" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {steps.map((s, i) => {
            const state = stateOf(i);
            const stateWords = state === "done" ? "done" : state === "current" ? "in progress" : state === "error" ? "failed" : "not started";
            const content = (
              <>
                <span
                  className={cn(
                    "relative grid shrink-0 place-items-center rounded-full transition-colors duration-300",
                    size === "sm" ? "size-4" : "size-5",
                    state === "done" && "bg-accent text-on-accent",
                    state === "current" && "bg-accent-soft ring-2 ring-accent",
                    state === "error" && "bg-danger text-white dark:text-canvas",
                    state === "todo" && "bg-surface ring-1 ring-line-strong",
                  )}
                >
                  {state === "done" ? (
                    <motion.span initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="grid place-items-center">
                      <Check className={size === "sm" ? "size-2.5" : "size-3"} strokeWidth={3.5} aria-hidden />
                    </motion.span>
                  ) : null}
                  {state === "error" ? <X className="size-3" strokeWidth={3.5} aria-hidden /> : null}
                  {state === "current" ? (
                    <span className="size-1.5 animate-pulse-soft rounded-full bg-accent motion-reduce:animate-none" aria-hidden />
                  ) : null}
                </span>
                {mode === "full" || mode === "short" ? (
                  <span aria-hidden data-step-label className={cn("mt-1.5 whitespace-nowrap text-center leading-4", LABEL_TONE[state])}>
                    {mode === "short" ? (s.short ?? s.label) : s.label}
                  </span>
                ) : stagger ? (
                  <span aria-hidden className="block h-[2.375rem]" />
                ) : null}
              </>
            );
            if (onPick) {
              return (
                <li key={s.id} className="flex min-w-0 justify-center">
                  <button
                    type="button"
                    onClick={() => onPick(i)}
                    aria-current={state === "current" ? "step" : undefined}
                    aria-label={`${s.label}${state === "done" ? " (looked at)" : ""}`}
                    // a whole column is the target (at least 24 × 24 px, WCAG 2.5.8), the dot inside it
                    className="flex min-h-6 w-full min-w-6 flex-col items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    {content}
                  </button>
                </li>
              );
            }
            return (
              <li
                key={s.id}
                className="flex min-w-0 flex-col items-center"
                aria-current={state === "current" ? "step" : undefined}
                aria-label={`${s.label}: ${stateWords}`}
              >
                {content}
              </li>
            );
          })}
        </ol>
        {stagger ? (
          <div aria-hidden className="pointer-events-none absolute inset-0 text-xs font-medium">
            {steps.map((s, i) => (
              <span
                key={s.id}
                data-step-label
                className={cn("absolute -translate-x-1/2 whitespace-nowrap leading-4", LABEL_TONE[stateOf(i)])}
                // under its dot; every other one a line (16 px) lower than its neighbours
                style={{ left: `${((i + 0.5) / n) * 100}%`, top: dot + 6 + (i % 2) * 16 }}
              >
                {s.short ?? s.label}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {mode === "current" ? (
        <div className={cn("mt-2 text-xs font-medium", status === "error" ? "text-danger-ink" : done ? "text-ok-ink" : "text-muted")}>
          {status === "error" ? `Stopped at: ${activeLabel}` : activeLabel}
          {!done && status !== "error" ? (
            <span className="font-normal text-muted">
              {" "}
              · step {current + 1} of {steps.length}
            </span>
          ) : null}
        </div>
      ) : null}
      {live ? (
        <span className="sr-only" aria-live="polite">
          {done ? "Finished." : status === "error" ? `Stopped at ${activeLabel}.` : `${activeLabel}, step ${current + 1} of ${steps.length}.`}
        </span>
      ) : null}
    </div>
  );
}
