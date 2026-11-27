/**
 * Fixed costs at a glance: per month (sum of every active contract), per year, count, next
 * decision. Four across only when the content column has room for four (a container query, not
 * the window's width — the sidebar takes its share); two by two otherwise. Nothing is cut off:
 * the figures scale with the column, and a long total wraps between its parts.
 */
import { Fragment, type ReactNode } from "react";
import type { Contract } from "@/api/types";
import { formatDate, formatTotals, protectRefs, type Totals } from "@/lib/format";
import { cn, plural } from "@/lib/utils";
import type { FixedCosts } from "./model";

/** The container that {@link CostSummary} and its loading skeleton lay out in. */
export const SUMMARY_GRID = "grid grid-cols-2 @4xl:grid-cols-4";

function Stat({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    // a subgrid of the list's rows: the figures of a row line up even when one label wraps
    <div className="row-span-2 grid min-w-0 grid-rows-subgrid gap-y-1 bg-surface px-4 py-4 sm:px-5">
      <dt className="text-[12.5px] font-medium leading-snug text-muted">{label}</dt>
      <dd className="min-w-0">
        <span className="display block text-[clamp(1.25rem,6.5cqi,1.875rem)] font-semibold leading-tight text-ink" data-part="value">
          {value}
        </span>
        {note ? <span className="mt-0.5 block text-[12.5px] leading-snug text-muted">{note}</span> : null}
      </dd>
    </div>
  );
}

/** "€982.33" or "€150 + US$50.00": each amount stays whole, the line may break between them. */
function Amounts({ totals, decimals }: { totals: Totals; decimals: number | "auto" }) {
  const parts = formatTotals(totals, { decimals }).split(" + ");
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i ? " + " : null}
          <span className="whitespace-nowrap tabular-nums">{p}</span>
        </Fragment>
      ))}
    </>
  );
}

/** A quieter part of a figure ("/month", "≈") in the body font. */
function Quiet({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("whitespace-nowrap font-sans text-[14px] font-normal text-muted", className)}>{children}</span>;
}

function costsNote(costs: FixedCosts): string {
  const parts = [`from ${plural(costs.counted, "contract")}`];
  if (costs.unknown) parts.push(`${costs.unknown} without a known cost`);
  // "from 8 contracts" next to "9 active contracts": say which one isn't in the sum
  if (costs.jobs) parts.push(costs.jobs === 1 ? "your job isn't a cost" : "your jobs aren't costs");
  // the dot stays with the part before it: a wrapped line never starts with "·"
  return parts.join(" · ");
}

/** Words the stand-in takes its height from, unseen: the labels, a figure and notes as long as the summary's. */
const STAND_IN: [label: string, note: string][] = [
  ["Fixed costs", "from 10 contracts"],
  ["Per year", "yearly and quarterly fees included"],
  ["Active contracts", "none cancelled or ended"],
];
const NEXT_NOTE = { decision: "Send by then to leave your contract", none: "no notice window closes in the next 60 days" };

/** Words laid out as the summary lays out its own, drawn as bars: each line of them is a bar of its length. */
function Ghost({ className, children }: { className: string; children: string }) {
  return (
    <span className={cn("block text-transparent select-none", className)}>
      <span className="animate-pulse rounded-md bg-surface-3/80 [box-decoration-break:clone] motion-reduce:animate-none">{children}</span>
    </span>
  );
}

/**
 * The summary while the contracts load, at the summary's own height (its labels, a figure and notes of the same
 * length, unseen), so the page below it doesn't move when the figures come. `decision`: this browser last saw one,
 * whose note ("Send by then to leave …") is shorter than "no notice window closes …".
 */
export function CostSummaryLoading({ decision }: { decision: boolean }) {
  const stats: [string, string][] = [...STAND_IN, ["Next decision", decision ? NEXT_NOTE.decision : NEXT_NOTE.none]];
  return (
    <div className="@container mb-8" aria-hidden data-testid="cost-summary-loading">
      <div className={cn("card gap-px overflow-hidden bg-line", SUMMARY_GRID)}>
        {stats.map(([label, note]) => (
          <div key={label} className="row-span-2 grid min-w-0 grid-rows-subgrid gap-y-1 bg-surface px-4 py-4 sm:px-5">
            <Ghost className="text-[12.5px] font-medium leading-snug">{label}</Ghost>
            <div className="min-w-0">
              <Ghost className="display text-[clamp(1.25rem,6.5cqi,1.875rem)] font-semibold leading-tight">€00.00</Ghost>
              <Ghost className="mt-0.5 text-[12.5px] leading-snug">{note}</Ghost>
            </div>
          </div>
        ))}
      </div>
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
  // the year in whole euros: say it is rounded, next to the month's cents
  const yearDecimals = costs.yearly >= 100 ? 0 : 2;
  const yearRounded = yearDecimals === 0 && Object.values(costs.yearlyTotals).some((v) => !Number.isInteger(v));
  const sendBy = next?.computed?.send_by ?? null;
  return (
    <div className="@container mb-8">
      <dl className={cn("card gap-px overflow-hidden bg-line", SUMMARY_GRID)}>
        <Stat
          label="Fixed costs"
          value={
            <>
              <Amounts totals={costs.monthlyTotals} decimals="auto" />
              <wbr />
              <Quiet className="ml-0.5">/month</Quiet>
            </>
          }
          note={costsNote(costs)}
        />
        <Stat
          label="Per year"
          value={
            <>
              {yearRounded ? <Quiet className="text-[0.7em]">{"≈ "}</Quiet> : null}
              <Amounts totals={costs.yearlyTotals} decimals={yearDecimals} />
            </>
          }
          note="yearly and quarterly fees included"
        />
        <Stat label="Active contracts" value={active} note={inactive ? `${inactive} cancelled or ended` : "none cancelled or ended"} />
        <Stat
          label="Next decision"
          value={sendBy ? formatDate(sendBy, { style: "short", today }) : "None soon"}
          note={next && sendBy ? `Send by then to leave ${protectRefs(next.name)}` : "no notice window closes in the next 60 days"}
        />
      </dl>
    </div>
  );
}
