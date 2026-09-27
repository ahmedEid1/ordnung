import { FlaskConical, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { useHealth } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Popover } from "@/components/ui/Popover";
import { useTourController } from "@/features/tour/useTourController";

const ABOUT = "You're exploring Sam Rivera's sample life. Every letter is fictional and today's date is simulated, so deadlines look the same whenever you visit.";

/**
 * "Demo · 28 Sep 2026" — shown when the backend simulates a date (demo mode). A button: it opens
 * "About the demo" (a bottom sheet on phones), which explains that the data is Sam Rivera's sample
 * life and the date is simulated, and restarts the guided tour (from its first step — also after
 * it was ended or finished). `compact` shows the flask only.
 */
export function DemoBadge({ compact, className }: { compact?: boolean; className?: string }) {
  const { data } = useHealth();
  const tour = useTourController();
  if (!data?.simulated_today && !data?.demo) return null;
  const date = formatDate(data.simulated_today ?? data.today, { style: "medium" });
  const label = `Demo · ${date}`;
  return (
    <Popover
      label="About the demo"
      placement={compact ? "right" : "top-start"}
      className="w-72"
      content={(close) => (
        <div className="space-y-3">
          <h2 className="flex items-center gap-2 text-md font-semibold text-ink in-sheet:hidden">
            <FlaskConical className="size-4 shrink-0 text-warn-ink" aria-hidden />
            About the demo
          </h2>
          <p className="text-sm leading-relaxed text-ink/85">{ABOUT}</p>
          <p className="text-sm text-muted">
            Today in the demo: <span className="font-medium tabular-nums text-ink">{date}</span>
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2 in-sheet:justify-start">
            {tour.demo && tour.state ? (
              <Button
                size="sm"
                variant="soft"
                icon={RotateCcw}
                onClick={() => {
                  tour.send({ type: "restart" });
                  close();
                }}
              >
                Restart the demo tour
              </Button>
            ) : null}
            <Button size="sm" onClick={close} className="ml-auto in-sheet:hidden">
              Close
            </Button>
          </div>
        </div>
      )}
    >
      <button
        type="button"
        aria-label={`${label} — about the demo`}
        title={compact ? label : undefined}
        className={cn(
          "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full border border-marker-strong/40 bg-marker/35 font-medium text-ink transition-colors hover:bg-marker/55 dark:border-marker-strong/30 dark:bg-marker/25 dark:hover:bg-marker/40",
          compact ? "size-9" : "h-7 px-2.5 text-xs",
          className,
        )}
      >
        <FlaskConical className="size-3.5 shrink-0 text-warn-ink" aria-hidden />
        {compact ? null : (
          <span className="whitespace-nowrap tabular-nums" aria-hidden>
            {label}
          </span>
        )}
      </button>
    </Popover>
  );
}
