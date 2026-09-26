/**
 * Batch-import recap ("I read 12 letters: 5 deadlines, 3 contracts, 312 €/month fixed costs,
 * 2 need you now, 1 possible scam") computed from the document details of the batch. Pure.
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
  /** letters that need the person soon (Please check, or something due within 14 days) */
  needYou: number;
  scams: number;
  scamDocId: string | null;
  needYouDocIds: string[];
}

const NEED_YOU_DAYS = 14;
const isOpen = (i: Item) => i.status === "open" || i.status === "missed";

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
    const soon = open.some((i) => {
      const date = i.send_by ?? i.due_date;
      return date ? daysUntil(date, today) <= NEED_YOU_DAYS : false;
    });
    if (doc.status === "needs_review" || doc.status === "failed" || soon) needYouDocIds.push(doc.id);
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
    scams,
    scamDocId,
    needYouDocIds,
  };
}

/** The findings of a recap as short phrases ("2 deadlines", "55,00 €/month fixed costs", …). */
export function recapFindings(r: BatchRecap): string[] {
  const parts: string[] = [];
  if (r.deadlines) parts.push(plural(r.deadlines, "deadline"));
  if (r.contracts) parts.push(plural(r.contracts, "contract"));
  if (r.fixedCostsMonthly > 0) parts.push(`${formatMoney(r.fixedCostsMonthly, { decimals: "auto" })}/month fixed costs`);
  if (r.needYou) parts.push(`${r.needYou} ${r.needYou === 1 ? "needs" : "need"} you now`);
  if (r.scams) parts.push(`${r.scams} possible ${r.scams === 1 ? "scam" : "scams"}`);
  return parts;
}

/** "I read 3 letters: 1 deadline, 55 €/month fixed costs, 1 needs you now, 1 possible scam." */
export function recapSentence(r: BatchRecap): string {
  const parts = recapFindings(r);
  const head = `I read ${plural(r.letters, "letter")}`;
  return parts.length ? `${head}: ${parts.join(", ")}.` : `${head}. Nothing needs you right now.`;
}
