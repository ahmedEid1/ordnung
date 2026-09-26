import { cn } from "@/lib/utils";
import { formatDate, formatTime, type DateStyle } from "@/lib/format";
import { useToday } from "@/lib/today";

export interface DateTextProps {
  date: string | null | undefined;
  /** "short" (default: "Fri 16 Oct"), "day", "medium", "long", "numeric", "month", "weekday". */
  style?: DateStyle;
  /** Year display: auto (only when not this year), always, never. */
  withYear?: "auto" | "always" | "never";
  time?: string | null;
  className?: string;
  /** Text when the date is missing. */
  fallback?: string;
}

/**
 * A human date in a semantic `<time>` element ("Fri 16 Oct"; the year is added automatically when
 * it differs from the app's today).
 */
export function DateText({ date, style = "short", withYear = "auto", time, className, fallback = "No date" }: DateTextProps) {
  const today = useToday();
  if (!date) return <span className={cn("text-muted", className)}>{fallback}</span>;
  return (
    <time dateTime={time ? `${date}T${formatTime(time)}` : date} className={cn("whitespace-nowrap tabular-nums", className)}>
      {formatDate(date, { style, today, withYear })}
      {time ? `, ${formatTime(time)}` : ""}
    </time>
  );
}
