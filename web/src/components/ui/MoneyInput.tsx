import type { ComponentProps } from "react";
import { Input } from "@/components/ui/Field";
import { formatMoney } from "@/lib/format";
import { parseMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

/**
 * An amount in euros, typed German or English style ("1.500", "29,90", "1,234.50"): a € prefix and a
 * "0,00" placeholder. Inside a {@link Field}, the label's id and descriptions reach the input itself.
 */
export function MoneyInput({ className, ...rest }: ComponentProps<"input">) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted" aria-hidden>
        €
      </span>
      <Input inputMode="decimal" placeholder="0,00" autoComplete="off" {...rest} className={cn("pl-7 tabular-nums", className)} />
    </div>
  );
}

/** How an amount was read ("= 1.500,00 €") when it had a separator to misread; else nothing. */
export function moneyReadBack(value: string): string | undefined {
  if (!value.trim() || !/[.,]/.test(value)) return undefined;
  const amount = parseMoney(value);
  return amount !== null ? `= ${formatMoney(amount)}` : undefined;
}
