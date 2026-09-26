import { motion } from "motion/react";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface StepperStep {
  id: string;
  label: string;
}

export interface StepperProps {
  steps: readonly StepperStep[];
  /** Index of the active step; `steps.length` means everything is done. */
  current: number;
  /** `error` marks the current step as failed. */
  status?: "active" | "error";
  size?: "sm" | "md";
  /** Which labels to show: all (centred under each dot), current (one line below) or none. */
  labels?: "all" | "current" | "none";
  /** Announce step changes politely to screen readers. */
  live?: boolean;
  /** Accessible name, e.g. "Reading Nebenkostenabrechnung.pdf". */
  label?: string;
  className?: string;
}

type StepState = "done" | "current" | "error" | "todo";

function Connector({ filled, hidden }: { filled: boolean; hidden: boolean }) {
  return (
    <span aria-hidden className={cn("relative h-0.5 flex-1 overflow-hidden rounded-full", hidden ? "invisible" : "bg-line")}>
      <motion.span
        className="absolute inset-y-0 left-0 rounded-full bg-accent"
        initial={false}
        animate={{ width: filled ? "100%" : "0%" }}
        transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
      />
    </span>
  );
}

/**
 * Horizontal animated progress stepper (upload pipeline: Reading → Understanding → Checking →
 * Computing dates → Filing). Each step is an equal-width column, so labels never overlap; long
 * labels wrap. Respects reduced motion via the global MotionConfig.
 */
export function Stepper({ steps, current, status = "active", size = "md", labels = "all", live, label, className }: StepperProps) {
  const done = current >= steps.length;
  const dot = size === "sm" ? "size-4" : "size-5";
  const activeLabel = done ? "Done" : steps[current]?.label ?? "";
  const stateOf = (i: number): StepState =>
    i < current ? "done" : i === current && !done ? (status === "error" ? "error" : "current") : "todo";

  return (
    <div className={cn("w-full", className)}>
      <ol aria-label={label ?? "Progress"} className="grid w-full" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s, i) => {
          const state = stateOf(i);
          return (
            <li
              key={s.id}
              className="flex min-w-0 flex-col items-center"
              aria-current={state === "current" ? "step" : undefined}
              aria-label={`${s.label}: ${state === "done" ? "done" : state === "current" ? "in progress" : state === "error" ? "failed" : "not started"}`}
            >
              <div className="flex w-full items-center">
                <Connector filled={i <= current && i > 0} hidden={i === 0} />
                <span
                  className={cn(
                    "relative mx-1 grid shrink-0 place-items-center rounded-full transition-colors duration-300",
                    dot,
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
                <Connector filled={i < current} hidden={i === steps.length - 1} />
              </div>
              {labels === "all" ? (
                <span
                  aria-hidden
                  className={cn(
                    "mt-1.5 w-full px-0.5 text-center font-medium leading-tight",
                    size === "sm" ? "text-[10.5px]" : "text-[11.5px]",
                    state === "current" ? "text-ink" : state === "error" ? "text-danger-ink" : state === "done" ? "text-ink/70" : "text-muted",
                  )}
                >
                  {s.label}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      {labels === "current" ? (
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
