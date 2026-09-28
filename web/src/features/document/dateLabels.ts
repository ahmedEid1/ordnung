/**
 * What a date the rules engine computed is called, by the nature of the deadline (a DateSpec's
 * `nature`), in the Today page's words: an appointment is "On", a payment "Pay by" (its send-by date
 * "Transfer by"), an objection, declaration or notice "Must arrive by" (its send-by date "Send by"),
 * anything else — a passport's expiry, a date the letter just names — "Date". Next to a send-by date,
 * the date is the one by which it must arrive. Money coming in or collected by direct debit is sent by
 * nobody, as on the Today page: its send-by date keeps "Send by".
 */
import type { DateNature } from "@/api/types";

const DUE_LABEL: Record<DateNature, string> = {
  appointment: "On",
  payment: "Pay by",
  objection: "Must arrive by",
  declaration: "Must arrive by",
  notice: "Must arrive by",
  other: "Date",
};

/** The due date's label ("Must arrive by" when the nature is unknown). */
export function dueDateLabel(nature: string | null | undefined, hasSendBy: boolean): string {
  if (hasSendBy) return "Must arrive by";
  return (nature && DUE_LABEL[nature as DateNature]) || "Must arrive by";
}

/** The send-by date's label: a transfer's is when it leaves your account. `transfer` says whether the
 * to-do is one (`isTransfer`: not money coming in, not a direct debit); without it, a payment is. */
export function sendByLabel(nature: string | null | undefined, transfer?: boolean): string {
  return (transfer ?? nature === "payment") ? "Transfer by" : "Send by";
}
