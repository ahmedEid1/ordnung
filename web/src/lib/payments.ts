/**
 * How a payment is made — so the UI never says "Pay" or "send it by post" for money the sender
 * collects itself (SEPA direct debit, Lastschrift), and says "transfer by" for bank transfers.
 * Mirrors `ordnung/payments.py`.
 */
import type { Item } from "@/api/types";

const DEBIT_WORDS = /direct debit|lastschrift|abbuchung|abgebucht|sufficient funds|kontodeckung|collected automatically/i;
const TRANSFER_WORDS = /\btransfer|überweis/i;

/** The sender collects this payment itself (direct debit): nothing to transfer. */
export function isDirectDebit(item: Pick<Item, "kind" | "title" | "action" | "description">): boolean {
  if (item.kind !== "payment") return false;
  const text = [item.title, item.action, item.description].filter(Boolean).join(" ");
  return DEBIT_WORDS.test(text) && !TRANSFER_WORDS.test(item.action ?? "");
}

/** Money coming to the person (a refund, a salary, a grant). */
export function isIncomingMoney(item: Pick<Item, "kind" | "direction">): boolean {
  return item.kind === "payment" && item.direction === "in";
}

/** Money the person has to send (a transfer), as opposed to a direct debit or money coming in. */
export function isTransfer(item: Pick<Item, "kind" | "direction" | "title" | "action" | "description">): boolean {
  return item.kind === "payment" && item.direction !== "in" && !isDirectDebit(item);
}
