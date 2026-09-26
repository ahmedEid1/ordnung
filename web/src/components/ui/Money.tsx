import { cn } from "@/lib/utils";
import { formatIntervalSuffix, formatMoney } from "@/lib/format";
import type { CostInterval } from "@/api/types";

export interface MoneyProps {
  amount: number | null | undefined;
  currency?: string | null;
  /** Appends "/month", "/year"… */
  interval?: CostInterval | null;
  /** Prefix "+" for positive values (e.g. price increases: "+€84.00/year"). */
  signed?: boolean;
  /** Colour: `out` (money you pay, default ink), `in` (money you get, green), `muted`. */
  tone?: "default" | "in" | "out" | "muted" | "danger";
  decimals?: number | "auto";
  className?: string;
}

const tones = {
  default: "text-ink",
  out: "text-ink",
  in: "text-ok-ink",
  muted: "text-muted",
  danger: "text-danger-ink",
};

/**
 * A money amount ("€184.30", "€34.99/month"), tabular figures, never wraps.
 *
 * @example <Money amount={34.99} interval="monthly" />
 */
export function Money({ amount, currency, interval, signed, tone = "default", decimals, className }: MoneyProps) {
  return (
    <span className={cn("whitespace-nowrap font-medium tabular-nums", tones[tone], className)}>
      {formatMoney(amount, { currency, signed, decimals })}
      {interval && interval !== "once" ? <span className="font-normal text-muted">{formatIntervalSuffix(interval)}</span> : null}
    </span>
  );
}
