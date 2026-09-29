/**
 * Batch-import recap ("I read 12 letters: 5 deadlines, 3 contracts, 312 €/month fixed costs,
 * 2 need you now, 1 possible scam") computed from the document details of the batch. Pure.
 *
 * "Need you now" are the letters Ordnung asks you to check (or couldn't read) — exactly the ones
 * the Inbox's "Please check" filter lists, where the recap's tile leads. Letters with something
 * due within two weeks are counted on their own ("2 due within 2 weeks", {@link dueSoon}).
 */
import type { Contract, DocumentDetail, Item } from "@/api/types";
import { daysUntil, formatMoney, monthlyAmount } from "@/lib/format";
import { plural } from "@/lib/utils";

export interface BatchRecap {
  letters: number;
  deadlines: number;
  contracts: number;
  /** recurring costs per month found in these letters (contracts + recurring payments) */
  fixedCostsMonthly: number;
  /** letters to check or that couldn't be read — the Inbox's "Please check" */
  needYou: number;
  /** letters with an open date within {@link DUE_SOON_DAYS} days (or overdue) */
  dueSoon: number;
  scams: number;
  scamDocId: string | null;
  needYouDocIds: string[];
  dueSoonDocIds: string[];
}

/** Something due within this many days is shown on its letter in the recap. */
export const DUE_SOON_DAYS = 14;
const isOpen = (i: Item) => i.status === "open" || i.status === "missed";

/** The earliest open date of a letter (send-by, else due) when it is at most {@link DUE_SOON_DAYS} away (or past). */
export function dueSoon(d: DocumentDetail, today: string): string | null {
  const dates = d.items
    .filter(isOpen)
    .map((i) => i.send_by ?? i.due_date)
    .filter((x): x is string => Boolean(x))
    .sort();
  const first = dates[0];
  return first && daysUntil(first, today) <= DUE_SOON_DAYS ? first : null;
}

function monthlyFromItem(i: Item): number | null {
  if (!i.recurrence || i.amount == null || i.direction === "in") return null;
  const per = i.recurrence.interval || 1;
  switch (i.recurrence.unit) {
    case "months":
      return i.amount / per;
    case "years":
      return i.amount / (12 * per);
    case "weeks":
      return (i.amount * 52) / (12 * per);
    case "days":
      return (i.amount * 365) / (12 * per);
  }
}

export function summarizeBatch(details: DocumentDetail[], today: string): BatchRecap {
  const contracts = new Map<string, Contract>();
  let deadlines = 0;
  let scams = 0;
  let scamDocId: string | null = null;
  const needYouDocIds: string[] = [];
  const dueSoonDocIds: string[] = [];
  const recurring = new Map<string, number>(); // cost source → monthly amount

  for (const d of details) {
    const doc = d.document;
    for (const c of d.contracts) contracts.set(c.id, c);
    const open = d.items.filter(isOpen);
    deadlines += open.filter((i) => i.kind === "deadline").length;
    const scam = d.suggestions.find((s) => s.kind === "scam" && s.status !== "dismissed" && s.status !== "expired");
    if (scam) {
      scams += 1;
      scamDocId ??= doc.id;
    }
    if (doc.status === "needs_review" || doc.status === "failed") needYouDocIds.push(doc.id);
    if (dueSoon(d, today)) dueSoonDocIds.push(doc.id);
    for (const i of open) {
      const m = monthlyFromItem(i);
      if (m != null) recurring.set(i.contract_id ? `c:${i.contract_id}` : `i:${i.id}`, m);
    }
  }
  for (const c of contracts.values()) {
    const m = c.status === "active" ? monthlyAmount(c.cost_amount, c.cost_interval) : null;
    if (m != null && !recurring.has(`c:${c.id}`)) recurring.set(`c:${c.id}`, m);
  }
  const fixed = [...recurring.values()].reduce((a, b) => a + b, 0);

  return {
    letters: details.length,
    deadlines,
    contracts: contracts.size,
    fixedCostsMonthly: Math.round(fixed * 100) / 100,
    needYou: needYouDocIds.length,
    dueSoon: dueSoonDocIds.length,
    scams,
    scamDocId,
    needYouDocIds,
    dueSoonDocIds,
  };
}

/** The findings of a recap as short phrases ("2 deadlines", "€55.00/month fixed costs", …). */
export function recapFindings(r: BatchRecap): string[] {
  const parts: string[] = [];
  if (r.deadlines) parts.push(plural(r.deadlines, "deadline"));
  if (r.contracts) parts.push(plural(r.contracts, "contract"));
  if (r.fixedCostsMonthly > 0) parts.push(`${formatMoney(r.fixedCostsMonthly, { decimals: "auto" })}/month fixed costs`);
  if (r.needYou) parts.push(`${r.needYou} ${r.needYou === 1 ? "needs" : "need"} you now`);
  if (r.dueSoon) parts.push(`${r.dueSoon} due within 2 weeks`);
  if (r.scams) parts.push(`${r.scams} possible ${r.scams === 1 ? "scam" : "scams"}`);
  return parts;
}

/** "I read 3 letters: 1 deadline, €55.00/month fixed costs, 1 needs you now, 1 possible scam." */
export function recapSentence(r: BatchRecap): string {
  const parts = recapFindings(r);
  const head = `I read ${plural(r.letters, "letter")}`;
  return parts.length ? `${head}: ${parts.join(", ")}.` : `${head}. Nothing needs you right now.`;
}

/** "I read 3 letters", "I read 2 of 3 letters" (one couldn't be read), "I couldn't read 2 letters". */
export function recapTitle(total: number, failed: number): string {
  if (!failed) return `I read ${plural(total, "letter")}`;
  if (failed >= total) return `I couldn't read ${total === 1 ? "the letter" : `${total} letters`}`;
  return `I read ${total - failed} of ${plural(total, "letter")}`;
}
