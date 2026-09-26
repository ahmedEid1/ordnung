/** Fixed costs at a glance: per month (sum of every active contract), per year, count, next decision. */
import type { ReactNode } from "react";
import type { Contract } from "@/api/types";
import { formatDate, formatTotals } from "@/lib/format";
import { cn, plural } from "@/lib/utils";
import type { FixedCosts } from "./model";

function Stat({ label, value, note, className }: { label: string; value: ReactNode; note?: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 bg-surface px-4 py-4 sm:px-5", className)}>
      <dt className="text-[12.5px] font-medium text-muted">{label}</dt>
      <dd className="mt-1">
        <span className="display block truncate text-[26px] font-semibold leading-tight text-ink sm:text-[30px]">{value}</span>
        {note ? <span className="mt-0.5 block text-[12.5px] leading-snug text-muted">{note}</span> : null}
      </dd>
    </div>
  );
}

export function CostSummary({
  costs,
  active,
  inactive,
  next,
  today,
}: {
  costs: FixedCosts;
  active: number;
  inactive: number;
  next: Contract | null;
  today: string;
}) {
  return (
    <dl className="card mb-8 grid grid-cols-2 gap-px overflow-hidden bg-line lg:grid-cols-4">
      <Stat
        label="Fixed costs per month"
        value={
          <>
            {formatTotals(costs.monthlyTotals, { decimals: "auto" })}
            <span className="ml-1 font-sans text-[14px] font-normal text-muted">/month</span>
          </>
        }
        note={costs.unknown ? `${plural(costs.counted, "contract")} · ${costs.unknown} without a known cost` : `from ${plural(costs.counted, "contract")}`}
      />
      <Stat
        label="Per year"
        value={formatTotals(costs.yearlyTotals, { decimals: costs.yearly >= 100 ? 0 : 2 })}
        note="yearly and quarterly fees included"
      />
      <Stat label="Active contracts" value={active} note={inactive ? `${inactive} cancelled or ended` : "none cancelled or ended"} />
      <Stat
        label="Next decision · post by"
        value={next?.computed?.send_by ? formatDate(next.computed.send_by, { style: "short", today }) : "None soon"}
        note={next ? next.name : "no notice window closes in the next 60 days"}
      />
    </dl>
  );
}
