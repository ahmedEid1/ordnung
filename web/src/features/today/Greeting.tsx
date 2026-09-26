import { Link } from "react-router";
import { motion } from "motion/react";
import { format, parseISO } from "date-fns";
import type { MoneySummary } from "@/api/types";
import { formatTotals, type Totals } from "@/lib/format";
import { fadeUp } from "./motion";
import { greetingFor } from "./selection";

function Stat({ label, value, suffix, to }: { label: string; value: string; suffix?: string; to: string }) {
  return (
    <Link
      to={to}
      className="group flex min-w-0 flex-col rounded-xl px-3 py-2 outline-none transition-colors hover:bg-surface-2/70 focus-visible:ring-2 focus-visible:ring-accent sm:items-end"
    >
      <span className="text-[12px] font-medium text-muted">{label}</span>
      <span className="display whitespace-nowrap text-[22px] font-semibold leading-tight tabular-nums text-ink">
        {value}
        {suffix ? <span className="ml-0.5 font-sans text-[13px] font-normal text-muted">{suffix}</span> : null}
      </span>
    </Link>
  );
}

/**
 * "Good morning, Sam" in Fraunces with the app's date (demo-safe) and two quiet money figures.
 * The greeting follows the local time of day.
 */
export function Greeting({
  name,
  today,
  money,
  toPay,
  hour,
}: {
  name: string;
  today: string;
  money: MoneySummary | undefined;
  /** Outgoing payments in the next 30 days, per currency (see `toPayTotals`). */
  toPay: Totals;
  hour: number;
}) {
  const greeting = greetingFor(hour);
  return (
    <motion.header variants={fadeUp} className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="text-[13.5px] font-medium text-muted">
          <time dateTime={today}>{format(parseISO(today), "EEEE, d MMMM")}</time>
        </p>
        <h1 className="display mt-1 text-[34px] font-semibold leading-[1.08] text-ink sm:text-[44px]">
          {greeting}
          {name ? `, ${name}` : ""}
        </h1>
      </div>
      {money ? (
        <div className="-mx-3 flex gap-1 sm:mx-0 sm:-mr-3">
          <Stat label="To pay · next 30 days" value={formatTotals(toPay, { decimals: "auto" })} to="/timeline" />
          <Stat
            label="Fixed costs"
            value={formatTotals({ ...money.fixed_costs_monthly_other_currencies, EUR: money.fixed_costs_monthly }, { decimals: "auto" })}
            suffix="/month"
            to="/contracts"
          />
        </div>
      ) : null}
    </motion.header>
  );
}
