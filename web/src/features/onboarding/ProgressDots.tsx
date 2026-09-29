import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * "● ● ○ ○" progress for the setup steps, with the current step's name for screen readers; after
 * the last step a "✓ Done" pill.
 */
export function ProgressDots({ steps, current }: { steps: readonly { id: string; label: string }[]; current: number }) {
  if (current >= steps.length) {
    return (
      <p className="inline-flex h-7 items-center gap-1.5 rounded-full bg-accent-soft px-3 text-[12.5px] font-semibold text-accent">
        <Check className="size-3.5" aria-hidden />
        <span aria-hidden>Done</span>
        <span className="sr-only">Setup: all {steps.length} steps done</span>
      </p>
    );
  }
  return (
    <ol className="flex items-center gap-2" aria-label={`Setup, step ${current + 1} of ${steps.length}`}>
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={s.id} aria-current={state === "current" ? "step" : undefined} className="flex items-center">
            <span
              className={cn(
                "h-2 rounded-full transition-all duration-300 motion-reduce:transition-none",
                state === "current" ? "w-7 bg-accent" : state === "done" ? "w-2 bg-accent/55" : "w-2 bg-line-strong",
              )}
              aria-hidden
            />
            <span className="sr-only">
              {s.label}: {state === "done" ? "done" : state === "current" ? "current step" : "not yet"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
