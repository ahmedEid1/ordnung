import { ArrowUpRight } from "lucide-react";
import { TOUR_TARGETS } from "@/features/tour/steps";
import { cn } from "@/lib/utils";
import { useDemoQuestions, useHealth } from "@/api/hooks";
import { SUGGESTED_QUESTIONS, withIcons } from "./suggestions";

/** Question chips: a 2-column grid of cards (empty state) or a compact row. */
export function SuggestedQuestions({
  onPick,
  disabled,
  variant = "grid",
  exclude = [],
  className,
}: {
  onPick: (question: string) => void;
  disabled?: boolean;
  variant?: "grid" | "row";
  exclude?: string[];
  className?: string;
}) {
  const demo = Boolean(useHealth().data?.demo);
  const served = useDemoQuestions(demo);
  // the demo's chips are the backend's recorded questions, word for word
  const all = demo && served.data?.length ? withIcons(served.data) : SUGGESTED_QUESTIONS;
  const list = all.filter((s) => !exclude.includes(s.question));
  if (!list.length) return null;
  return (
    <ul
      aria-label="Suggested questions"
      data-tour={TOUR_TARGETS.askChips}
      className={cn(variant === "grid" ? "grid gap-2.5 sm:grid-cols-2" : "flex flex-wrap gap-2", className)}
    >
      {list.map(({ question, icon: Icon }) => (
        <li key={question} className={variant === "row" ? "max-w-full" : undefined}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(question)}
            className={cn(
              "group flex w-full items-start gap-3 text-left transition-[border-color,background-color,box-shadow,transform] disabled:pointer-events-none disabled:opacity-50",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              variant === "grid"
                ? "h-full rounded-xl border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)] hover:-translate-y-px hover:border-accent/40 hover:shadow-[var(--shadow-pop)] motion-reduce:hover:translate-y-0"
                : "max-w-full items-center rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] hover:border-accent/40 hover:bg-accent-soft/50",
            )}
          >
            {variant === "grid" ? (
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                <Icon className="size-4" aria-hidden />
              </span>
            ) : (
              <Icon className="size-3.5 shrink-0 text-accent" aria-hidden />
            )}
            <span className={cn("min-w-0 flex-1 text-ink", variant === "grid" ? "pt-1 text-[14px] font-medium leading-snug" : "truncate")}>
              {question}
            </span>
            {variant === "grid" ? (
              <ArrowUpRight className="mt-1.5 size-4 shrink-0 text-faint transition-colors group-hover:text-accent" aria-hidden />
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
