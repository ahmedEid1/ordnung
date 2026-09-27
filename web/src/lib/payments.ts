/**
 * How a payment is made — so the UI never says "Pay" or "send it by post" for money the sender
 * collects itself (SEPA direct debit, Lastschrift), and says "transfer by" for bank transfers —
 * and the reference to type into a transfer. Mirrors `ordnung/payments.py`.
 */
import type { Item } from "@/api/types";

/** A direct debit in a to-do's words (German and English). "Einzug" alone is moving in. */
const DEBIT_WORDS =
  /direct debit|debited|collected automatically|sufficient funds|lastschrift|bankeinzug|abbuch|abgebucht|eingezogen|einzieh|mandatsreferenz|gläubiger-?id|kontodeckung/i;
const TRANSFER_WORDS = /\btransfer|überweis/i;
/** A label a letter prints before its reference ("Kassenzeichen: …"), followed by a colon or a space. */
const REFERENCE_LABEL =
  /^(?:kassenzeichen|aktenzeichen|az\.?|buchungszeichen|verwendungszweck|zahlungsreferenz|referenz(?:nummer)?|reference|ref\.?|vorgang(?:snummer)?|beitragsnummer|(?:rechnungs|kunden|vertrags|mitglieds|vorgangs)-?(?:nummer|nr\.?)|rechnung(?:\s+nr\.?)?|(?:invoice|customer)(?:\s+(?:no\.?|number))?)(?:\s*[:#]\s*|\s+)/i;

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

/**
 * The reference to type into a transfer — the letter's without a leading label word
 * ("Kassenzeichen: 5126 0184 5122" → "5126 0184 5122"), unchanged when no digit would be left.
 * The same value the GiroCode carries.
 */
export function paymentReference(reference: string): string {
  let value = reference.trim();
  for (let match = REFERENCE_LABEL.exec(value); match; match = REFERENCE_LABEL.exec(value)) {
    const rest = value.slice(match[0].length).trim();
    if (!/\d/.test(rest)) break;
    value = rest;
  }
  return value;
}
