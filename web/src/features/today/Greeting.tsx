import { Link } from "react-router";
import { motion } from "motion/react";
import { format, parseISO } from "date-fns";
import type { MoneySummary } from "@/api/types";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatIntervalSuffix, formatTotals, type Totals } from "@/lib/format";
import { fadeUp } from "./motion";
import { greetingFor } from "./selection";

/**
 * One money figure that links to where it comes from. The label never wraps; the amount never
 * breaks, and its "/month" moves below it rather than pushing the row wider (like `Money`).
 */
function Stat({ label, value, interval, to }: { label: string; value: string; interval?: "monthly"; to: string }) {
  const suffix = interval ? formatIntervalSuffix(interval) : "";
  return (
    <Link
      to={to}
      className="group flex flex-col rounded-xl px-2 py-1.5 outline-none transition-colors hover:bg-surface-2/70 focus-visible:ring-2 focus-visible:ring-accent @[52rem]:items-end"
    >
      <span className="whitespace-nowrap text-xs font-medium text-muted transition-colors group-hover:text-ink">{label}</span>
      <span className="display text-[22px] font-semibold leading-tight tabular-nums text-ink">
        <span className="whitespace-nowrap">{value}</span>
        {suffix ? (
          <>
            <wbr />
            <span className="ml-0.5 whitespace-nowrap font-sans text-[13px] font-normal text-muted">{suffix}</span>
          </>
        ) : null}
      </span>
    </Link>
  );
}

function StatSkeleton() {
  return (
    <div className="flex flex-col gap-1.5 px-2 py-1.5 @[52rem]:items-end" aria-hidden>
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-6 w-20" />
    </div>
  );
}

/**
 * "Good morning, Sam" in Fraunces with the app's date (demo-safe) and two quiet money figures
 * beside it when there is room, else under it. The greeting follows the local time of day.
 * `money: undefined` leaves the figures out; `loading` shows their placeholders.
 */
export function Greeting({
  name,
  today,
  money,
  toPay,
  hour,
  loading = false,
}: {
  name: string;
  today: string;
  money?: MoneySummary;
  /** Outgoing payments in the next 30 days, per currency (see `toPayTotals`). */
  toPay?: Totals;
  hour: number;
  loading?: boolean;
}) {
  const greeting = greetingFor(hour);
  return (
    <motion.header variants={fadeUp} className="@container">
      <div className="flex flex-col gap-3 @[52rem]:flex-row @[52rem]:items-end @[52rem]:justify-between @[52rem]:gap-6">
        <div className="min-w-0">
          <p className="text-[13.5px] font-medium text-muted">
            <time dateTime={today}>{format(parseISO(today), "EEEE, d MMMM")}</time>
          </p>
          <h1 className="display mt-1 text-[34px] font-semibold leading-[1.08] text-ink [overflow-wrap:anywhere] sm:text-[44px]">
            {greeting}
            {name ? `, ${name}` : ""}
          </h1>
        </div>
        {loading ? (
          <div className="-mx-2 flex flex-wrap gap-x-2 gap-y-1 @[52rem]:shrink-0">
            <StatSkeleton />
            <StatSkeleton />
          </div>
        ) : money ? (
          <div className="-mx-2 flex flex-wrap gap-x-2 gap-y-1 @[52rem]:shrink-0">
            <Stat label="To pay · next 30 days" value={formatTotals(toPay ?? {}, { decimals: "auto" })} to="/timeline" />
            <Stat
              label="Fixed costs"
              value={formatTotals({ ...money.fixed_costs_monthly_other_currencies, EUR: money.fixed_costs_monthly }, { decimals: "auto" })}
              interval="monthly"
              to="/contracts"
            />
          </div>
        ) : null}
      </div>
    </motion.header>
  );
}
