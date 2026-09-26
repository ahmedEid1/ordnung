import { CircleCheck, TriangleAlert } from "lucide-react";
import type { DraftCheck } from "@/api/types";
import { cn } from "@/lib/utils";
import { sortChecks } from "./logic";

/**
 * The checks run on a draft (reference included, dates stated, addresses complete, no
 * placeholders, only known § citations, no invented numbers, allowed way of sending).
 */
export function ChecksPanel({ checks, stale }: { checks: DraftCheck[]; stale?: boolean }) {
  if (!checks.length) return <p className="text-base text-muted">No checks for this letter yet.</p>;
  const failed = checks.filter((c) => !c.ok).length;
  return (
    <div>
      <p
        className={cn(
          "mb-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12.5px] font-semibold",
          failed ? "bg-warn-soft text-warn-ink" : "bg-ok-soft text-ok-ink",
        )}
      >
        {failed ? <TriangleAlert className="size-3.5" aria-hidden /> : <CircleCheck className="size-3.5" aria-hidden />}
        {failed ? `${failed} ${failed === 1 ? "thing needs" : "things need"} a look` : `All ${checks.length} checks passed`}
      </p>
      <ul className="space-y-2.5">
        {sortChecks(checks).map((c) => (
          <li key={c.id} className="flex gap-2.5 text-[13.5px] leading-5">
            {c.ok ? (
              <CircleCheck className="mt-px size-4 shrink-0 text-ok" aria-label="Passed" role="img" />
            ) : (
              <TriangleAlert className="mt-px size-4 shrink-0 text-warn" aria-label="Please check" role="img" />
            )}
            <span className="min-w-0">
              <span className={c.ok ? "text-ink/85" : "font-medium text-ink"}>{c.label}</span>
              {c.detail ? <span className={cn("block text-[12.5px]", c.ok ? "text-muted" : "text-warn-ink")}>{c.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      {stale ? <p className="mt-3 text-[12.5px] leading-5 text-muted">Checks run again when you save your changes.</p> : null}
    </div>
  );
}
