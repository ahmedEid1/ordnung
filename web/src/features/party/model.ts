/**
 * People & organisations drawer: which to-dos to list (and which to set apart), how to label their
 * dates, and how to show identifiers so they wrap cleanly.
 */
import type { Document, Item, ItemAside, Party, Recurrence } from "@/api/types";
import { formatDate, type DateInput } from "@/lib/format";
import { isDirectDebit, isIncomingMoney } from "@/lib/payments";

/**
 * The date to act on: the send-by / transfer-by date, else the due date — for a direct debit the
 * day it is collected (there is nothing to send), as on Today.
 */
export function actionDate(item: Pick<Item, "kind" | "send_by" | "due_date" | "title" | "action" | "description">): string | null {
  if (isDirectDebit(item)) return item.due_date ?? null;
  return item.send_by ?? item.due_date ?? null;
}

/**
 * What the date means, in the words Today uses: "Transfer by" (a bank transfer), "Collected" (a
 * direct debit), "Send by", "On" (appointments, money coming in), "Expires", "By" (tasks), "Due".
 */
export function dateRole(item: Pick<Item, "kind" | "direction" | "send_by" | "title" | "action" | "description">): string {
  if (item.kind === "payment" && item.direction !== "in") return isDirectDebit(item) ? "Collected" : item.send_by ? "Transfer by" : "Pay by";
  if (item.send_by) return "Send by";
  switch (item.kind) {
    case "payment":
    case "appointment":
    case "milestone":
    case "reminder":
      return "On";
    case "expiry":
      return "Expires";
    case "task":
      return "By";
    default:
      return "Due";
  }
}

/** Countdown mode: past appointments, milestones and money coming in are "3 days ago", not "overdue". */
export function countdownMode(item: Pick<Item, "kind" | "direction">): "due" | "event" {
  return item.kind === "appointment" || item.kind === "milestone" || item.kind === "reminder" || isIncomingMoney(item) ? "event" : "due";
}

/** "Every month", "Every 3 months", "Every year" (null for one-off items). */
export function repeatsLabel(r: Recurrence | null | undefined): string | null {
  if (!r) return null;
  const unit = { days: "day", weeks: "week", months: "month", years: "year" }[r.unit];
  return r.interval === 1 ? `Every ${unit}` : `Every ${r.interval} ${unit}s`;
}

export interface PartyTodos {
  /** Open to-dos to act on: dated ones soonest first, then repeating ones, then the undated. */
  open: Item[];
  /** Open to-dos that are not one to act on (a reminder took over, history, scam signs), with why. */
  aside: { item: Item; aside: ItemAside }[];
}

function rank(item: Item): [number, string] {
  const date = actionDate(item);
  if (date) return [0, date];
  return [item.recurrence ? 1 : 2, ""];
}

/** Split a party's items into the to-dos to list and the ones to set apart (see `PartyDetail.set_aside`). */
export function partyTodos(items: readonly Item[], setAside: readonly ItemAside[] = []): PartyTodos {
  const why = new Map(setAside.map((a) => [a.item_id, a]));
  const open = items.filter((i) => i.status === "open");
  return {
    open: open
      .filter((i) => !why.has(i.id))
      .sort((a, b) => {
        const [ra, da] = rank(a);
        const [rb, db] = rank(b);
        return ra - rb || da.localeCompare(db) || a.title.localeCompare(b.title);
      }),
    aside: open.flatMap((item) => {
      const aside = why.get(item.id);
      return aside ? [{ item, aside }] : [];
    }),
  };
}

/** One sentence on why a to-do is set apart ("Replaced by the payment reminder of Thu 10 Sep …"). */
export function asideNote(aside: ItemAside, documents: readonly Pick<Document, "id" | "doc_date" | "received_date">[], today: DateInput): string {
  switch (aside.reason) {
    case "replaced": {
      const reminder = documents.find((d) => d.id === aside.replaced_by);
      const date = reminder?.doc_date ?? reminder?.received_date;
      const of = date ? `the payment reminder of ${formatDate(date, { style: "short", today })}` : "a later payment reminder";
      return `Replaced by ${of} — pay that one, not both.`;
    }
    case "history":
      return "Already in the past when the letter was added — kept for your records.";
    case "suspicious":
      return "From a letter with signs of a scam — don't pay or reply before you've checked it.";
  }
}

/**
 * Whether a party seems to sit outside Germany (no Bundesland, and an address without a German
 * five-digit postcode) — then German public holidays say nothing about their deadlines.
 */
export function looksAbroad(party: Pick<Party, "region" | "address">): boolean {
  if (party.region) return false;
  const address = party.address?.trim();
  return Boolean(address) && !/(^|\D)\d{5}(\D|$)/.test(address!);
}

/**
 * How an identifier reads: `code` (customer numbers, IBANs, file numbers — no lowercase letters)
 * or `text` (a court register entry, "Amtsgericht Musterstadt HRB 4711").
 */
export function identifierStyle(value: string): "code" | "text" {
  return /[a-zäöüß]/.test(value) ? "text" : "code";
}

const NBSP = "\u00a0";

/** Digit groups stay on one line ("Postfach 10 01 00", "Ref. K 2231 0917"); words still wrap. */
export function keepNumbersTogether(text: string): string {
  return text.replace(/(\d) (?=\d)/g, `$1${NBSP}`);
}

/**
 * An identifier as shown, so lines only break where a person would: an IBAN between its groups of
 * four ("DE44 5001 0517 …"), a code never ("K 2231 0917" stays whole), a register entry between
 * words but never inside "HRB 48213". Rendered with `break-words`, a part too long for the line
 * still wraps rather than overflow.
 */
export function identifierDisplay(value: string, kind: "iban" | "code" | "text"): string {
  const v = value.trim();
  if (kind === "iban") return v.replace(/\s+/g, "").replace(/(.{4})(?!$)/g, "$1 ");
  if (kind === "code") return v.replace(/\s+/g, NBSP);
  // register abbreviations stay with their number: "HRB 48213", "GnR 123", "VR 2011"
  return v.replace(/\s+/g, " ").replace(/\b(HRA|HRB|GnR|GsR|PR|VR)\s(\d)/g, `$1${NBSP}$2`);
}
