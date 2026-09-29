/**
 * How a payment is made — so the UI never says "Pay" or "send it by post" for money the sender
 * collects itself (SEPA direct debit, Lastschrift), and says "transfer by" for bank transfers —
 * and the reference to type into a transfer. Mirrors `ordnung/payments.py`.
 */
import type { Item } from "@/api/types";

/**
 * A direct debit in a to-do's words (German and English). "Einziehen" and "Einzug" are left out: in a
 * tenancy they are moving in ("sobald Sie eingezogen sind"); so are a mandate's reference and the
 * creditor's ID, which a letter asking for a transfer after the mandate ended prints too.
 */
const DEBIT_WORDS = /direct debit|debited|collected automatically|sufficient funds|lastschrift|bankeinzug|abbuch|abgebucht|kontodeckung/i;
const TRANSFER_WORDS = /\btransfer|überweis/i;
const DEBIT_NOUN = "(?:lastschrift|abbuchung|einzug|debit|payment|zahlung)";
const FAILED_VERB = "(?:zurückgegeben|zurückgebucht|zurückgerufen|fehlgeschlagen|returned|bounced|failed)";
/**
 * A debit that failed — the bank returned it, or it couldn't be collected — in one clause. "Returned"
 * without a debit beside it is anything returned ("the router must be returned").
 */
const FAILED_DEBIT = new RegExp(
  "rücklastschrift|mangels\\s+deckung|nicht\\s+gedeckt" +
    "|nicht\\b[\\s\\S]{0,40}?(?:eingelöst|eingezogen|abgebucht|einziehen|abbuchen|ausgeführt|durchgeführt)" +
    "|(?:abbuchung|lastschrift|einzug)[\\s\\S]{0,40}?nicht\\s+möglich" +
    "|could\\s+not\\s+be\\s+(?:collected|debited)" +
    `|${DEBIT_NOUN}[\\s\\S]{0,60}?${FAILED_VERB}|${FAILED_VERB}[\\s\\S]{0,60}?${DEBIT_NOUN}`,
  "i",
);
/**
 * A clause that only warns of a failed debit — a condition, or what one costs ("Bei Rücklastschrift
 * berechnen wir 3,00 € Gebühr", "a returned debit costs €3") — says none failed.
 */
const WARNING =
  /^\s*bei(?![\p{L}\p{N}_])|(?<![\p{L}\p{N}_])(?:falls|sollten?|wenn|sofern|im\s+falle?|für\s+jede[\p{L}]*|if|in\s+case|should|each|every)(?![\p{L}\p{N}_])|kost(?:et|en)(?![\p{L}\p{N}_])|(?<![\p{L}\p{N}_])costs?(?![\p{L}\p{N}_])/iu;
/** Where a clause ends: not at a comma or full stop inside a number or a date ("29,90", "15.10."). */
const CLAUSE_END = /[;:!?]|(?<!\d),|,(?!\d)|(?<!\d)\.(?!\d)/;
/** A label a letter prints before its reference ("Kassenzeichen: …"), followed by a colon or a space. */
const REFERENCE_LABEL =
  /^(?:kassenzeichen|aktenzeichen|az\.?|buchungszeichen|verwendungszweck|zahlungsreferenz|referenz(?:nummer)?|reference|ref\.?|vorgang(?:snummer)?|beitragsnummer|(?:rechnungs|kunden|vertrags|mitglieds|vorgangs)-?(?:nummer|nr\.?)|rechnung(?:\s+nr\.?)?|(?:invoice|customer)(?:\s+(?:no\.?|number))?)(?:\s*[:#]\s*|\s+)/i;

/**
 * The words say a direct debit failed (a Rücklastschrift, "could not be debited") as a fact, not as a
 * warning: the person pays now.
 */
export function debitFailed(text: string): boolean {
  return text.split(CLAUSE_END).some((clause) => FAILED_DEBIT.test(clause) && !WARNING.test(clause));
}

/**
 * The sender collects this payment itself (direct debit): nothing to transfer — unless one of its
 * words (title, action, description) says the debit failed, or its action asks for a transfer.
 */
export function isDirectDebit(item: Pick<Item, "kind" | "title" | "action" | "description">): boolean {
  if (item.kind !== "payment") return false;
  const parts = [item.title, item.action, item.description].filter((part): part is string => Boolean(part));
  return (
    parts.some((part) => DEBIT_WORDS.test(part)) &&
    !parts.some((part) => debitFailed(part)) &&
    !TRANSFER_WORDS.test(item.action ?? "")
  );
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
