/**
 * "Why these dates?" for a contract, in the shared {@link Receipt}: the key dates, the engine's
 * plain-words summary, notes (form requirements…) and the notice rule used, how sure we are (and
 * why), then "Show the rules" with every step and its legal citation. Always ends with the
 * point-of-use disclaimer (SPEC §21).
 */
import { Info, Scale } from "lucide-react";
import type { Contract } from "@/api/types";
import { ADVICE_LINKS } from "@/components/ui/Disclaimer";
import { Receipt, ReceiptPopover, useReceiptSteps, type ReceiptDate } from "@/components/ui/Receipt";
import { CONTRACT_REGIME_COPY, copyFor } from "@/lib/copy";
import { formatInlineText } from "@/lib/format";
import { CONTINUES_MONTHLY, endsAtTheFifteenth, isFixedTerm, isRollingContract } from "./model";

function contractDates(contract: Contract): ReceiptDate[] {
  const comp = contract.computed;
  if (!comp) return [];
  const dates: ReceiptDate[] = [];
  // the same words as the card: "Send by", "Must arrive by", "Then monthly from"
  if (comp.send_by) dates.push({ label: "Send by", date: comp.send_by });
  if (comp.cancel_by) dates.push({ label: "Must arrive by", date: comp.cancel_by });
  if (comp.safe_date && comp.safe_date !== comp.cancel_by) dates.push({ label: "Safe date (a working day)", date: comp.safe_date });
  if (comp.current_term_end) dates.push({ label: isFixedTerm(contract) ? "Ends" : "Current term ends", date: comp.current_term_end });
  if (comp.next_renewal) {
    const monthly = CONTINUES_MONTHLY.has(comp.regime) || !contract.renewal_term_months;
    dates.push({ label: monthly ? "Then monthly from" : "Renews on", date: comp.next_renewal });
  }
  if (comp.earliest_exit && comp.earliest_exit !== comp.current_term_end) dates.push({ label: "Earliest possible end", date: comp.earliest_exit });
  return dates;
}

export function ContractWhyView({ contract }: { contract: Contract }) {
  const comp = contract.computed;
  const steps = useReceiptSteps(comp?.steps ?? []);
  if (!comp) return null;
  const regime = copyFor(CONTRACT_REGIME_COPY, comp.regime);
  const advice = contract.category === "rent" ? ADVICE_LINKS.rent : contract.category === "employment" ? undefined : ADVICE_LINKS.consumer;
  const rolling = isRollingContract(contract);

  return (
    <Receipt
      heading="Why these dates?"
      context={contract.name}
      dates={contractDates(contract)}
      summary={comp.summary}
      confidence={comp.confidence}
      // "use the fastest channel today" is no advice for a contract you can cancel next month too
      warnings={rolling ? comp.warnings.filter((w) => !/sending time has passed/i.test(w)) : comp.warnings}
      steps={steps}
      advice={advice}
    >
      {rolling ? (
        <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-sm leading-5 text-ink/85">
          {endsAtTheFifteenth(contract)
            ? "You can give notice any time. Miss this date and it ends at a later 15th or month's end — nothing is locked in."
            : "You can cancel this any month. Miss this date and it simply ends a month later — nothing is locked in."}
        </p>
      ) : null}
      {comp.notes.length ? (
        <ul className="space-y-1.5">
          {comp.notes.map((n) => (
            <li key={n} className="flex gap-2 text-sm leading-5 text-ink/90">
              <Info className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
              {formatInlineText(n)}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="flex items-start gap-2 text-xs leading-5 text-muted">
        <Scale className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>
          Rule used: <span className="font-medium text-ink/85">{regime.label}</span>
          {"citation" in regime && comp.regime !== "as_written" ? ` · ${formatInlineText(String(regime.citation))}` : ""}
        </span>
      </p>
    </Receipt>
  );
}

/** "Why these dates?" link that opens {@link ContractWhyView} in a popover. */
export function ContractWhy({ contract, className }: { contract: Contract; className?: string }) {
  if (!contract.computed) return null;
  return <ReceiptPopover title="Why these dates?" context={contract.name} content={<ContractWhyView contract={contract} />} className={className} />;
}
