import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";

export type DateLeafTone = "default" | "muted" | "today" | "danger" | "warn";

export interface DateLeafProps {
  /** ISO date (yyyy-mm-dd). */
  date: string;
  /** `sm` 40 px (dense lists), `md` 44 px (list rows), `lg` 64 px with the month (feature cards). */
  size?: "sm" | "md" | "lg";
  /** `muted` for past dates, `today` outlined in ink, `danger` overdue, `warn` soon. */
  tone?: DateLeafTone;
  /** Hide it from screen readers when the row already says the date. */
  decorative?: boolean;
  className?: string;
}

const sizes = {
  sm: { box: "w-10 rounded-lg py-1", day: "mt-0.5 text-md" },
  md: { box: "w-11 rounded-lg py-1.5", day: "mt-0.5 text-lg" },
  lg: { box: "w-16 rounded-xl py-2", day: "mt-1 text-3xl" },
} as const;

const tones: Record<DateLeafTone, { box: string; weekday: string }> = {
  default: { box: "border-line bg-surface text-ink", weekday: "text-muted" },
  muted: { box: "border-line bg-surface-2/60 text-muted", weekday: "text-muted" },
  today: { box: "border-ink/70 bg-surface text-ink shadow-[inset_0_0_0_1px_var(--color-ink)]", weekday: "text-ink" },
  danger: { box: "border-danger/30 bg-danger-soft text-danger-ink", weekday: "text-danger-ink" },
  warn: { box: "border-warn/30 bg-warn-soft text-warn-ink", weekday: "text-warn-ink" },
};

/**
 * Calendar-leaf date — "THU" over a big "8" (and "OCT" in the large size) — in one look for every
 * list: the weekday is 11 px, never smaller. Screen readers hear the full date ("Thursday 8
 * October") unless the leaf is `decorative`.
 *
 * @example <DateLeaf date="2026-10-08" size="md" tone={overdue ? "danger" : "default"} />
 */
export function DateLeaf({ date, size = "md", tone = "default", decorative, className }: DateLeafProps) {
  const d = parseISO(date);
  const s = sizes[size];
  const t = tones[tone];
  return (
    <time
      dateTime={date}
      aria-hidden={decorative || undefined}
      data-size={size}
      className={cn("flex shrink-0 flex-col items-center border leading-none", s.box, t.box, className)}
    >
      <span aria-hidden className={cn("text-2xs font-semibold uppercase tracking-[0.08em]", t.weekday)}>
        {format(d, "EEE")}
      </span>
      <span aria-hidden className={cn("display font-semibold tabular-nums", s.day)}>
        {format(d, "d")}
      </span>
      {size === "lg" ? (
        <span aria-hidden className="mt-1 text-2xs font-semibold uppercase tracking-[0.08em]">
          {format(d, "MMM")}
        </span>
      ) : null}
      {decorative ? null : <span className="sr-only">{format(d, "EEEE d MMMM")}</span>}
    </time>
  );
}
