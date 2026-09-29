/**
 * What a to-do row on the letter page says about its date (UI audit round 1: the scam letter's
 * demand read as an urgent to-do with "transfer by", a €100 fee paid by card at the appointment said
 * "transfer by 13 Oct", a direct debit counted down in red, a salary said "No date"):
 *
 * - `scam`: a demand in a letter with signs of a scam — no countdown, nothing to tick off;
 * - `debit`: collected by the sender ("collected Thu 1 Oct · in 3 days", never louder than amber, as on Today);
 * - `on_site`: paid at the counter or the appointment ("pay on site Wed 14 Oct");
 * - `transfer`: a bank transfer, with "transfer by" when the money needs a day or two;
 * - `event`: appointments, milestones and money coming in ("in 5 days", "2 days ago");
 * - `due`: everything else with a date;
 * - `undated`: no date — money coming in is "expected", something that repeats says only how often.
 */
import type { Item } from "@/api/types";
import { isDirectDebit, isIncomingMoney } from "@/lib/payments";

export type ItemDateRole = "scam" | "debit" | "on_site" | "transfer" | "event" | "due" | "undated";

/** Paid in person — at the appointment, the service desk or a machine, by card or in cash (as `pays_on_site` in `ordnung/payments.py`). */
const ON_SITE =
  /\bon[ -]site\b|\bat the appointment\b|\bat the (?:service )?(?:desk|counter)\b|\bpayment machine\b|\bgirocard\b|\bEC[ -]card\b|\bcash\b|\bvor Ort\b|\bin bar\b|\bbar (?:be)?zahlen\b|\bEC-Karte\b|\bam (?:Kassen|Zahl)automaten\b|\ban der Kasse\b/i;
const TRANSFER = /\btransfer|überweis/i;

/** A payment made in person (card or cash at the appointment, the desk, a machine), not by bank transfer. */
export function paysOnSite(item: Pick<Item, "kind" | "direction" | "title" | "action" | "description">): boolean {
  if (item.kind !== "payment" || item.direction === "in" || isDirectDebit(item)) return false;
  const how = [item.action, item.description].filter(Boolean).join(" ");
  return ON_SITE.test(how) && !TRANSFER.test(item.action ?? "");
}

/** How the row shows an open to-do's date (see the module comment). */
export function itemDateRole(item: Item, opts: { scam?: boolean } = {}): ItemDateRole {
  if (opts.scam) return "scam";
  if (!item.due_date) return "undated";
  if (item.kind === "payment" && !isIncomingMoney(item)) {
    if (isDirectDebit(item)) return "debit";
    if (paysOnSite(item)) return "on_site";
    return "transfer";
  }
  if (item.kind === "appointment" || item.kind === "milestone" || item.kind === "reminder" || isIncomingMoney(item)) return "event";
  return "due";
}

/**
 * What an undated to-do says instead of a date: "collected automatically" for a direct debit,
 * "expected" for money coming in once, nothing else when it repeats (the row says "every month"),
 * else "No date".
 */
export function undatedNote(item: Pick<Item, "kind" | "direction" | "recurrence" | "title" | "action" | "description">): string | null {
  if (isDirectDebit(item)) return "collected automatically";
  if (item.recurrence) return null;
  return isIncomingMoney(item) ? "expected" : "No date";
}
