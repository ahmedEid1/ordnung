import { ArrowUpRight } from "lucide-react";
import { TOUR_TARGETS } from "@/features/tour/steps";
import { cn } from "@/lib/utils";
import { useDemoQuestions, useHealth, useProfile } from "@/api/hooks";
import { useToday } from "@/lib/today";
import { SUGGESTED_QUESTIONS, suggestedQuestions, withIcons } from "./suggestions";

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
  const profile = useProfile();
  const today = useToday();
  // the demo's chips are the backend's recorded questions, word for word — none once the letters or to-dos
  // changed and the recordings no longer fit (the Ask page says how to start over); anyone else's fit their situation
  const all = demo
    ? served.data
      ? withIcons(served.data)
      : SUGGESTED_QUESTIONS
    : suggestedQuestions({ today, studentVisa: Boolean(profile.data?.is_student_visa) });
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
            // a row chip wraps rather than cut the question off (UI audit round 1: "…and by whe…"); the
            // title holds the whole of a question that is longer still
            title={variant === "row" ? question : undefined}
            className={cn(
              "group flex w-full items-start gap-3 text-left transition-[border-color,background-color,box-shadow,transform] disabled:pointer-events-none disabled:opacity-50",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              variant === "grid"
                ? "h-full rounded-xl border border-line bg-surface px-4 py-3.5 shadow-[var(--shadow-card)] hover:-translate-y-px hover:border-accent/40 hover:shadow-[var(--shadow-pop)] motion-reduce:hover:translate-y-0"
                : "max-w-full gap-2 rounded-[18px] border border-line bg-surface px-3 py-1.5 text-[13px] leading-5 hover:border-accent/40 hover:bg-accent-soft/50",
            )}
          >
            {variant === "grid" ? (
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                <Icon className="size-4" aria-hidden />
              </span>
            ) : (
              <Icon className="mt-[3px] size-3.5 shrink-0 text-accent" aria-hidden />
            )}
            <span className={cn("min-w-0 flex-1 text-ink", variant === "grid" ? "pt-1 text-[14px] font-medium leading-snug" : "line-clamp-3 [overflow-wrap:anywhere]")}>
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
