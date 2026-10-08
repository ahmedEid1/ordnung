import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/api/hooks";
import type { Party } from "@/api/types";
import { Receipt, ReceiptPopover, useReceiptSteps, type ReceiptDate } from "@/components/ui/Receipt";
import { SenderLandNote, senderLandUnknown, useLetterLanguage } from "@/features/document/WhyThisDate";
import type { ReceiptModel } from "./receipt";

/** Whose date it is, from Today's list of parties (nothing is fetched). */
function useParty(id: string | null): Party | null {
  const qc = useQueryClient();
  if (!id) return null;
  return qc.getQueryData<Party[]>(qk.parties.list())?.find((p) => p.id === id) ?? null;
}

/**
 * The receipt for a to-do or a contract decision on Today (see the shared {@link Receipt}). A date counted without
 * the sender's state says so, with the way to choose it — as on the letter's page. `close` closes the popover first.
 */
export function ReceiptView({ receipt, title, close }: { receipt: ReceiptModel; title?: string; close?: () => void }) {
  const steps = useReceiptSteps(receipt.steps);
  const dates: ReceiptDate[] = [];
  if (receipt.sendBy) dates.push({ label: receipt.sendByLabel ?? "Send by", date: receipt.sendBy });
  if (receipt.dueDate) dates.push({ label: receipt.sendBy ? "Must arrive by" : receipt.dueLabel, date: receipt.dueDate });
  const ev = !receipt.computed ? receipt.evidence : null;
  const language = useLetterLanguage(ev?.doc_id);
  const landless = senderLandUnknown(receipt, useParty(receipt.partyId));
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
    >
      {landless ? <SenderLandNote party={landless} close={close} /> : null}
    </Receipt>
  );
}

/**
 * "Why this date?" link that opens the receipt popover.
 *
 * @example <WhyThisDate receipt={receiptForItem(item)} context={item.title} />
 */
export function WhyThisDate({ receipt, context, className }: { receipt: ReceiptModel | null; context: string; className?: string }) {
  if (!receipt) return null;
  return (
    <ReceiptPopover
      content={(close) => <ReceiptView receipt={receipt} title={context} close={close} />}
      context={context}
      placement="bottom-end"
      className={className}
    />
  );
}
