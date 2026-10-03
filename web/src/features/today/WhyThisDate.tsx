import { Receipt, ReceiptPopover, useReceiptSteps, type ReceiptDate } from "@/components/ui/Receipt";
import { useLetterLanguage } from "@/features/document/WhyThisDate";
import type { ReceiptModel } from "./receipt";

/** The receipt for a to-do or a contract decision on Today (see the shared {@link Receipt}). */
export function ReceiptView({ receipt, title }: { receipt: ReceiptModel; title?: string }) {
  const steps = useReceiptSteps(receipt.steps);
  const dates: ReceiptDate[] = [];
  if (receipt.sendBy) dates.push({ label: receipt.sendByLabel ?? "Send by", date: receipt.sendBy });
  if (receipt.dueDate) dates.push({ label: receipt.sendBy ? "Must arrive by" : receipt.dueLabel, date: receipt.dueDate });
  const ev = !receipt.computed ? receipt.evidence : null;
  const language = useLetterLanguage(ev?.doc_id);
  return (
    <Receipt
      context={title}
      dates={dates}
      summary={receipt.summary}
      confidence={receipt.confidence}
      warnings={receipt.warnings}
      quote={ev ? { text: ev.quote, grounding: ev.grounding, page: ev.page, language } : null}
      steps={steps}
      holidayCalendar={receipt.holidayCalendar}
    />
  );
}

/**
 * "Why this date?" link that opens the receipt popover.
 *
 * @example <WhyThisDate receipt={receiptForItem(item)} context={item.title} />
 */
export function WhyThisDate({ receipt, context, className }: { receipt: ReceiptModel | null; context: string; className?: string }) {
  if (!receipt) return null;
  return <ReceiptPopover content={<ReceiptView receipt={receipt} title={context} />} context={context} placement="bottom-end" className={className} />;
}
