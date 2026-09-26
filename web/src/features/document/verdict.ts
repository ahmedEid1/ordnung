/**
 * Verdict logic for the Document viewer: which to-do is "the one thing to do", what the main
 * button does, and which items need the person's eyes ("Please check", "When did it arrive?").
 * Pure functions, unit-tested in `verdict.test.ts`.
 */
import type { Document, DocumentDetail, DraftKind, Item, ItemKind, Priority, Suggestion } from "@/api/types";
import { daysUntil, formatRelativeDays, type DateInput } from "@/lib/format";
import { isDirectDebit, isIncomingMoney } from "@/lib/payments";

const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, normal: 2, low: 3 };
const KIND_RANK: Record<ItemKind, number> = { deadline: 0, payment: 1, appointment: 2, expiry: 3, task: 4, reminder: 5, milestone: 6 };

/** Still something to act on (missed and snoozed items count — they are not closed). */
export function isOpenItem(i: Item): boolean {
  return i.status === "open" || i.status === "missed" || i.status === "snoozed";
}

/** The date that matters first: "send by" when the post needs time, else the due date. */
export function actionDate(i: Item): string | null {
  return i.send_by ?? i.due_date;
}

/**
 * Order to-dos by how much they matter now: open first, then priority, one-off before recurring
 * (the rent is not "the thing to do" about a letter), dated before undated, earliest first,
 * then by kind (deadline > payment > appointment > …), then title for stability.
 */
export function compareItems(a: Item, b: Item): number {
  const open = Number(isOpenItem(b)) - Number(isOpenItem(a));
  if (open) return open;
  const pr = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
  if (pr) return pr;
  const rec = Number(Boolean(a.recurrence)) - Number(Boolean(b.recurrence));
  if (rec) return rec;
  const da = actionDate(a);
  const db = actionDate(b);
  if (da && !db) return -1;
  if (!da && db) return 1;
  if (da && db && da !== db) return da < db ? -1 : 1;
  const kr = (KIND_RANK[a.kind] ?? 9) - (KIND_RANK[b.kind] ?? 9);
  if (kr) return kr;
  return a.title.localeCompare(b.title);
}

/**
 * The primary to-do of a letter (drives the verdict card). Null when nothing is open. Money coming
 * in (a tax refund) is never "what you need to do" — see {@link incomingMoney}.
 */
export function selectPrimaryItem(items: Item[]): Item | null {
  const open = items.filter((i) => isOpenItem(i) && !isIncomingMoney(i));
  if (!open.length) return null;
  return [...open].sort(compareItems)[0] ?? null;
}

/** An open payment coming to the person with this letter (a refund), if any. */
export function incomingMoney(items: Item[]): Item | null {
  return items.find((i) => isOpenItem(i) && isIncomingMoney(i) && i.amount != null) ?? null;
}

/** An objection deadline: only matters if the person disagrees with the decision. */
export function isOptionalObjection(i: Pick<Item, "date_spec">): boolean {
  return i.date_spec?.nature === "objection";
}

/** Ideas that are a decision about the letter's contract: keep it, or cancel it in time. */
const DECISION_RULES = new Set(["price_increase_right", "contract_cancel_window"]);

/** The open "cancel or keep?" Idea of this letter (a price increase's special right, a notice window). */
export function decisionSuggestion(detail: Pick<DocumentDetail, "suggestions">): Suggestion | null {
  return (
    detail.suggestions.find(
      (s) =>
        DECISION_RULES.has(s.rule_id ?? "") &&
        (s.status === "new" || s.status === "snoozed" || s.status === "accepted") &&
        s.action?.type === "draft" &&
        s.action.draft_kind === "cancellation",
    ) ?? null
  );
}

/**
 * Whether the verdict leads with the decision rather than the primary to-do: always, unless a
 * one-off to-do has to be done before the decision's date. A recurring fee or a direct debit is
 * never "the thing to do" about a price increase.
 */
export function leadsWithDecision(decision: Suggestion | null, primary: Item | null): boolean {
  if (!decision) return false;
  if (!primary || !isOpenItem(primary) || primary.recurrence || isDirectDebit(primary)) return true;
  const mine = actionDate(primary);
  return !mine || !decision.due_date || decision.due_date <= mine;
}

/** To-dos sorted for the list (open by importance, then closed ones). */
export function sortItems(items: Item[]): Item[] {
  return [...items].filter((i) => i.status !== "dismissed").sort(compareItems);
}

/** The active scam warning (an Idea of kind "scam") for this letter, if any. */
export function scamSuggestion(detail: Pick<DocumentDetail, "suggestions">): Suggestion | null {
  return detail.suggestions.find((s) => s.kind === "scam" && s.status !== "dismissed" && s.status !== "expired") ?? null;
}

/**
 * "Please check": the quote behind this to-do could not be found in the letter, or the date /
 * amount doesn't match its quote (SPEC §8 verify, §21 spec_consistency).
 */
export function needsCheck(i: Item): boolean {
  if (!isOpenItem(i) || i.grounding === "user") return false;
  if (i.grounding === "unverified") return true;
  return i.evidence.some((e) => e.grounding === "unverified" || !e.value_consistent);
}

/**
 * The period starts when the letter arrived (`receipt` anchor) and we don't know that date yet —
 * the rules engine fell back to the letter date (earliest possible) until the person tells us.
 */
export function needsArrivalDate(i: Item, doc: Pick<Document, "received_date">): boolean {
  if (!isOpenItem(i) || i.date_spec?.anchor !== "receipt") return false;
  if (!doc.received_date) return true;
  return Boolean(i.computation?.rule_ids.some((r) => r.includes("fallback")));
}

/** The law gives these an objection whatever their instructions say (§ 694, § 700 ZPO). */
const COURT_ORDERS = new Set<Document["kind"]>(["court_payment_order", "enforcement_order"]);

/**
 * A court order: its objection deadline is not "only if you disagree" — doing nothing lets the claim
 * be enforced, so the person must pay or object.
 */
export function isCourtOrder(doc: Pick<Document, "kind">): boolean {
  return COURT_ORDERS.has(doc.kind);
}

/**
 * Letters whose law-set deadline is never "only if you disagree": a court order (pay or object, or it
 * is enforced) and a dismissal (only a court action in time keeps the person's rights, and the
 * registration as job-seeking is due either way).
 */
const MUST_ACT = new Set<Document["kind"]>([...COURT_ORDERS, "dismissal"]);

export function mustAct(doc: Pick<Document, "kind">): boolean {
  return MUST_ACT.has(doc.kind);
}

/** The other open deadlines the law sets for this letter (a dismissal's registration), earliest first. */
export function otherLawDeadlines(items: Item[], primary: Item | null): Item[] {
  return items.filter((i) => i.origin === "rule" && isOpenItem(i) && i.id !== primary?.id && i.due_date).sort(compareItems);
}

export type MainAction =
  | { type: "draft"; draftKind: Extract<DraftKind, "objection" | "cancellation">; label: string; item: Item | null }
  | { type: "pay"; item: Item }
  | { type: "calendar"; item: Item }
  | { type: "done"; item: Item }
  | { type: "scam"; realDocId: string | null }
  | { type: "decide"; suggestion: Suggestion }
  | { type: "none" };

/**
 * The one main button of the verdict card:
 * scam → never "Pay" (offer to compare with a real letter) · Einspruch/Widerspruch → draft the
 * objection (type comes from the Rechtsbehelfsbelehrung, never a guess) · a notice deadline on a
 * contract → draft the cancellation · a payment → Pay · a dated to-do → Add to calendar ·
 * otherwise Mark done.
 */
export function chooseMainAction(detail: DocumentDetail, primary: Item | null): MainAction {
  const scam = scamSuggestion(detail);
  if (scam) {
    const real = scam.refs.find((r) => r.type === "document" && r.id !== detail.document.id);
    return { type: "scam", realDocId: real?.id ?? null };
  }
  const remedy = detail.document.remedy?.type;
  const courtOrder = isCourtOrder(detail.document);
  if ((remedy === "einspruch" || remedy === "widerspruch" || courtOrder) && (!primary || isOpenItem(primary))) {
    return { type: "draft", draftKind: "objection", label: "Draft objection", item: primary };
  }
  if (!primary || !isOpenItem(primary)) return { type: "none" };
  if (primary.date_spec?.nature === "notice" && primary.contract_id) {
    return { type: "draft", draftKind: "cancellation", label: "Draft cancellation", item: primary };
  }
  if (primary.kind === "payment" && primary.direction !== "in" && primary.amount != null && !isDirectDebit(primary)) return { type: "pay", item: primary };
  if (primary.due_date) return { type: "calendar", item: primary };
  return { type: "done", item: primary };
}

/** Open to-dos that deleting the letter would remove, counted per kind ("1 deadline, 2 payments"). */
export function openItemCounts(items: Item[]): { kind: ItemKind; count: number }[] {
  const counts = new Map<ItemKind, number>();
  for (const i of items) if (isOpenItem(i)) counts.set(i.kind, (counts.get(i.kind) ?? 0) + 1);
  return [...counts.entries()].map(([kind, count]) => ({ kind, count })).sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind]);
}

/**
 * Countdown for the verdict's big date, precise in days up to three months ("in 23 days" rather
 * than "in 3 weeks"): the exact number matters when a deadline is legal.
 */
export function dayCountdown(date: string, today: DateInput, mode: "due" | "event" = "due"): string {
  const n = daysUntil(date, today);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n < 0) return mode === "due" ? (n === -1 ? "1 day overdue" : `${-n} days overdue`) : formatRelativeDays(date, today, "event");
  if (n <= 90) return `in ${n} days`;
  return formatRelativeDays(date, today, mode);
}
