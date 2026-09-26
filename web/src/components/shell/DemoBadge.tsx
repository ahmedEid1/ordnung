import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { useHealth } from "@/api/hooks";
import { Tooltip } from "@/components/ui/Tooltip";

/**
 * "Demo · 28 Sep 2026" — shown when the backend simulates a date (demo mode). Explains that the
 * data is Sam Rivera's sample life and the date is simulated.
 */
export function DemoBadge({ compact, className }: { compact?: boolean; className?: string }) {
  const { data } = useHealth();
  if (!data?.simulated_today && !data?.demo) return null;
  const date = data.simulated_today ?? data.today;
  const label = `Demo · ${formatDate(date, { style: "medium" })}`;
  const tip = "You're exploring Sam Rivera's sample life. Every letter is fictional and today's date is simulated, so deadlines look the same whenever you visit.";
  return (
    <Tooltip content={tip} side={compact ? "right" : "top"}>
      <span
        tabIndex={0}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-marker-strong/40 bg-marker/35 font-medium text-ink dark:border-marker-strong/30 dark:bg-marker/25",
          compact ? "size-9 justify-center" : "h-7 px-2.5 text-[12px]",
          className,
        )}
      >
        <FlaskConical className="size-3.5 shrink-0 text-warn-ink" aria-hidden />
        {/* compact: icon only, the label stays readable for screen readers (a span can't take aria-label) */}
        <span className={compact ? "sr-only" : "whitespace-nowrap tabular-nums"}>{label}</span>
      </span>
    </Tooltip>
  );
}
