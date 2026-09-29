import { cn } from "@/lib/utils";
import { formatIntervalSuffix, formatMoney } from "@/lib/format";
import type { CostInterval } from "@/api/types";

export interface MoneyProps {
  amount: number | null | undefined;
  currency?: string | null;
  /**
   * Appends "/month", "/year"… as its own quieter part, one small gap after the amount. In a
   * tight spot it moves below the amount instead of pushing the layout wider.
   */
  interval?: CostInterval | null;
  /** Classes for the interval suffix — e.g. its size next to a large display amount. */
  intervalClassName?: string;
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
 * A money amount ("€184.30", "€34.99/month") in tabular figures. The amount itself never wraps;
 * the interval suffix may wrap below it.
 *
 * @example <Money amount={34.99} interval="monthly" />
 * @example <Money amount={59.9} interval="yearly" className="display text-[24px]" intervalClassName="font-sans text-sm" />
 */
export function Money({ amount, currency, interval, intervalClassName, signed, tone = "default", decimals, className }: MoneyProps) {
  const suffix = interval && interval !== "once" ? formatIntervalSuffix(interval) : "";
  return (
    <span className={cn("font-medium tabular-nums", tones[tone], className)}>
      <span className="whitespace-nowrap">{formatMoney(amount, { currency, signed, decimals })}</span>
      {suffix ? (
        <>
          <wbr />
          <span data-part="interval" className={cn("ml-0.5 whitespace-nowrap font-normal text-muted", intervalClassName)}>
            {suffix}
          </span>
        </>
      ) : null}
    </span>
  );
}
