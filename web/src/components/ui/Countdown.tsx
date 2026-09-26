import { cn } from "@/lib/utils";
import { formatDate, formatRelativeDays, formatTime, urgencyOf, type RelativeMode, type Urgency } from "@/lib/format";
import { useToday } from "@/lib/today";

const urgencyText: Record<Urgency, string> = {
  overdue: "text-danger-ink",
  today: "text-danger-ink",
  soon: "text-danger-ink",
  week: "text-warn-ink",
  month: "text-ink",
  later: "text-muted",
  past: "text-muted",
};

const urgencyPill: Record<Urgency, string> = {
  overdue: "bg-danger-soft text-danger-ink",
  today: "bg-danger-soft text-danger-ink",
  soon: "bg-danger-soft text-danger-ink",
  week: "bg-warn-soft text-warn-ink",
  month: "bg-surface-2 text-ink",
  later: "bg-surface-2 text-muted",
  past: "bg-surface-2 text-muted",
};

export interface CountdownProps {
  /** ISO date the countdown targets. */
  date: string;
  /** `due` (default): past → "2 days overdue". `event`: past → "2 days ago". */
  mode?: RelativeMode;
  /** Prefix such as "send by" → "send by Thu 8 Oct · in 10 days". Implies showing the date. */
  prefix?: string;
  /** Also show the absolute date ("Thu 8 Oct · in 10 days"). */
  showDate?: boolean;
  /** Optional time ("10:30") appended to the date. */
  time?: string | null;
  /** `text` (inline) or `pill`. */
  variant?: "text" | "pill";
  className?: string;
}

/**
 * Relative countdown coloured by urgency — "today", "tomorrow", "in 5 days", "2 days overdue" —
 * computed against the app's today (demo-safe). Renders a `<time>` element.
 *
 * @example <Countdown date="2026-10-08" prefix="send by" />  → "send by Thu 8 Oct · in 10 days"
 */
export function Countdown({ date, mode = "due", prefix, showDate, time, variant = "text", className }: CountdownProps) {
  const today = useToday();
  const u = urgencyOf(date, today, mode);
  const rel = formatRelativeDays(date, today, mode);
  const abs = `${formatDate(date, { style: "short", today })}${time ? `, ${formatTime(time)}` : ""}`;
  const showAbs = showDate || Boolean(prefix);
  return (
    <time
      dateTime={date}
      title={abs}
      className={cn(
        "whitespace-nowrap tabular-nums",
        variant === "pill"
          ? cn("inline-flex items-center rounded-full px-2 py-[3px] text-[12px] font-medium leading-4", urgencyPill[u])
          : "font-medium",
        variant === "text" && urgencyText[u],
        className,
      )}
    >
      {showAbs ? (
        <>
          {prefix ? `${prefix} ` : ""}
          {abs}
          {/* NBSP: a leading normal space would be dropped inside the inline-flex pill */}
          <span className={cn(variant === "text" && "font-normal")}>{" · "}{rel}</span>
        </>
      ) : (
        rel
      )}
    </time>
  );
}
