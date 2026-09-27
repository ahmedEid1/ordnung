/**
 * "Why this date?" for a letter's to-do — the rules engine's receipt in the shared {@link Receipt}:
 * the key dates, the plain sentence, how sure we are (and why), what the letter says, then "Show
 * the rules" with every step, its citation and the holiday calendar. Always ends with the
 * point-of-use disclaimer (SPEC §21), with independent advice for high-stakes areas.
 */
import type { Area, ComputationReceipt, DateSpec, ItemOrigin } from "@/api/types";
import { ADVICE_LINKS, type AdviceLink } from "@/components/ui/Disclaimer";
import { Receipt, ReceiptPopover, useReceiptSteps, type ReceiptDate } from "@/components/ui/Receipt";

/** Independent advice links for high-stakes areas (tax, residence, rent, fines). */
export function adviceFor(area: Area | null | undefined): AdviceLink[] | undefined {
  switch (area) {
    case "tax":
      return ADVICE_LINKS.tax;
    case "residence":
      return ADVICE_LINKS.residence;
    case "home":
      return ADVICE_LINKS.rent;
    case "mobility":
      return ADVICE_LINKS.fines;
    default:
      return undefined;
  }
}

export interface ReceiptViewProps {
  receipt: ComputationReceipt;
  /** What the letter says (shown as the quote the date came from). */
  spec?: DateSpec | null;
  area?: Area | null;
  /** Start with the rule steps open. */
  defaultShowRules?: boolean;
  /**
   * Where the to-do came from: a deadline the law adds (`rule`) has a spec Ordnung wrote in the law's
   * words — never shown as what the letter says.
   */
  origin?: ItemOrigin | null;
}

export function ReceiptView({ receipt, spec, area, defaultShowRules = false, origin }: ReceiptViewProps) {
  const steps = useReceiptSteps(receipt.steps);
  const dates: ReceiptDate[] = [];
  if (receipt.send_by) dates.push({ label: "Send by", date: receipt.send_by });
  if (receipt.due_date) dates.push({ label: "Must arrive by", date: receipt.due_date });
  if (receipt.safe_date && receipt.safe_date !== receipt.due_date) dates.push({ label: "Safe date (a working day)", date: receipt.safe_date });
  return (
    <Receipt
      dates={dates}
      summary={receipt.summary}
      confidence={receipt.confidence}
      warnings={receipt.warnings}
      quote={spec?.text ? (origin === "rule" ? { text: spec.text, source: "law", citation: spec.legal_basis } : { text: spec.text }) : null}
      steps={steps}
      holidayCalendar={receipt.holiday_calendar}
      defaultShowRules={defaultShowRules}
      advice={adviceFor(area)}
    />
  );
}

/**
 * A "Why this date?" trigger that opens the receipt in a popover.
 *
 * @example <WhyThisDate receipt={item.computation} spec={item.date_spec} />
 */
export function WhyThisDate({
  receipt,
  spec,
  area,
  origin,
  context,
  title,
  className,
}: {
  receipt: ComputationReceipt;
  spec?: DateSpec | null;
  area?: Area | null;
  /** Where the to-do came from (see {@link ReceiptViewProps.origin}). */
  origin?: ItemOrigin | null;
  /** What the date belongs to (the to-do's title), for screen readers. */
  context?: string;
  /** The trigger's words (default "Why this date?"). */
  title?: string;
  className?: string;
}) {
  return (
    <ReceiptPopover
      content={<ReceiptView receipt={receipt} spec={spec} area={area} origin={origin} />}
      context={context}
      title={title}
      className={className}
    />
  );
}
