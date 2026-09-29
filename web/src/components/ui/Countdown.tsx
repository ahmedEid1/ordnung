import { cn } from "@/lib/utils";
import { formatDate, formatRelativeDays, formatTime, urgencyOf, urgencyTone, type RelativeMode } from "@/lib/format";
import { useToday } from "@/lib/today";

export interface CountdownProps {
  /** ISO date the countdown targets. */
  date: string;
  /**
   * `due` (default): past → "2 days overdue". `event` (appointments, money coming in): past →
   * "2 days ago", and it never turns red (capped at amber).
   */
  mode?: RelativeMode;
  /** Prefix such as "send by" → "send by Thu 8 Oct · in 10 days". Implies showing the date. */
  prefix?: string;
  /** Also show the absolute date ("Thu 8 Oct · in 10 days"). */
  showDate?: boolean;
  /** Optional time ("10:30") appended to the date. */
  time?: string | null;
  /** `text` (inline, wraps after the "·" when the line is full) or `pill` (one line). */
  variant?: "text" | "pill";
  /**
   * The loudest colour: `"warn"` for dates that need nothing sent — direct debits (the bank
   * collects them) and appointments. Default: `"warn"` in `event` mode, none otherwise.
   */
  cap?: "warn";
  /** Dates more than 30 days out in ink instead of muted (card rows where the date is the content). */
  inkLater?: boolean;
  className?: string;
}

/**
 * Relative countdown coloured by the app's one urgency scale (`urgencyTone`: red up to
 * tomorrow, amber within a week, ink within 30 days, muted later) — "today", "tomorrow",
 * "in 5 days", "2 days overdue" — computed against the app's today (demo-safe). Renders a
 * `<time>` element.
 *
 * In the `text` variant the prefix, the date and the relative part each stay whole and the line
 * breaks between them ("send by Thu 8 Oct ·⏎in 10 days"), so it never pushes a card or the page
 * wider than the screen.
 *
 * @example <Countdown date="2026-10-08" prefix="send by" />  → "send by Thu 8 Oct · in 10 days"
 */
export function Countdown({ date, mode = "due", prefix, showDate, time, variant = "text", cap, inkLater, className }: CountdownProps) {
  const today = useToday();
  const tone = urgencyTone(urgencyOf(date, today, mode), { cap: cap ?? (mode === "event" ? "warn" : undefined), inkLater });
  const rel = formatRelativeDays(date, today, mode);
  const abs = `${formatDate(date, { style: "short", today })}${time ? `, ${formatTime(time)}` : ""}`;
  const showAbs = showDate || Boolean(prefix);
  const pill = variant === "pill";
  return (
    <time
      dateTime={date}
      title={abs}
      data-urgency={tone.level}
      className={cn(
        "tabular-nums",
        tone.text,
        pill
          ? // the spans are flex items here: the gap stands in for the spaces between them
            cn("inline-flex items-center gap-x-1 whitespace-nowrap rounded-full px-2 py-[3px] text-xs font-medium leading-4", tone.soft)
          : "font-medium",
        !showAbs && "whitespace-nowrap",
        className,
      )}
    >
      {showAbs ? (
        <>
          {prefix ? <span className="whitespace-nowrap">{prefix}</span> : null}
          {prefix ? " " : null}
          <span className="whitespace-nowrap">
            {abs}
            {/* the dot stays with the date; the line may break after it */}
            <span className={cn(!pill && "font-normal")}>{"\u00a0·"}</span>
          </span>{" "}
          <span className={cn("whitespace-nowrap", !pill && "font-normal")}>{rel}</span>
        </>
      ) : (
        rel
      )}
    </time>
  );
}
