import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** "● ● ○ ○" progress for the setup steps, with the current step's name for screen readers. */
export function ProgressDots({ steps, current }: { steps: readonly { id: string; label: string }[]; current: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label={`Setup, step ${Math.min(current + 1, steps.length)} of ${steps.length}`}>
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={s.id} aria-current={state === "current" ? "step" : undefined} className="flex items-center">
            <span
              className={cn(
                "grid h-2 place-items-center rounded-full transition-all duration-300 motion-reduce:transition-none",
                state === "current" ? "w-7 bg-accent" : state === "done" ? "w-2 bg-accent/55" : "w-2 bg-line-strong",
              )}
              aria-hidden
            />
            <span className="sr-only">
              {s.label}: {state === "done" ? "done" : state === "current" ? "current step" : "not yet"}
            </span>
            {state === "done" && i === steps.length - 1 ? <Check className="ml-1 size-3 text-accent" aria-hidden /> : null}
          </li>
        );
      })}
    </ol>
  );
}
