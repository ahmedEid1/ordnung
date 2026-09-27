/**
 * Verdict logic for the Document viewer: which to-do is "the one thing to do", what the main
 * button does, and which items need the person's eyes ("Please check", "When did it arrive?").
 * Pure functions, unit-tested in `verdict.test.ts`.
 */
import type { Document, DocumentDetail, DraftKind, Item, ItemKind, PartyKind, Priority, Suggestion } from "@/api/types";
import { daysUntil, formatDate, formatRelativeDays, type DateInput } from "@/lib/format";
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
 * The period starts when the letter arrived (`receipt` anchor) — or the engine counted it from the
 * arrival because the sender is no authority (`private_sender_arrival`, § 130 BGB), whatever anchor
 * it was read with, or, for a court order, from when it was delivered (§ 180 ZPO) — and we don't know
 * that date yet: the rules engine fell back to the letter date (earliest possible) until the person
 * tells us. The computation decides, not the stored reading: a private sender's period from a date the
 * letter gives (`private_sender_no_delivery`) never asks.
 */
export function needsArrivalDate(i: Item, doc: Pick<Document, "received_date">): boolean {
  if (!isOpenItem(i)) return false;
  const fromArrival = Boolean(i.computation?.rule_ids.includes("private_sender_arrival"));
  const served = Boolean(i.computation?.rule_ids.includes("zpo_180"));
  if (i.date_spec?.anchor !== "receipt" && !fromArrival && !served) return false;
  if (!doc.received_date) return true;
  return Boolean(i.computation?.rule_ids.some((r) => r.includes("fallback")));
}

/**
 * Party kinds a public body may be filed as (`ordnung.rules.delivery.MAY_BE_PUBLIC_KINDS`; a Python
 * test keeps the two equal): a late arrival of their letters never moves a date later, since the
 * letter may be an authority's (`private_sender_late_arrival`). A letter whose own words name an
 * administrative act is treated so too, whatever its kind — only the engine can tell that.
 */
export const MAY_BE_PUBLIC_KINDS: readonly PartyKind[] = ["company", "insurer", "utility", "employer"];

const LATE_ARRIVAL_RULE = "private_sender_late_arrival";

/**
 * What saving the arrival day did, from the items recomputed with it: they count from that day — or,
 * where the letter arrived later than letters usually take and may be an authority's, the engine still
 * counts from the earlier day it would usually count as delivered (`private_sender_late_arrival`, its
 * step's date), and says so in "Why this date?".
 */
export function arrivalSavedNote(arrived: string, items: readonly Item[]): string {
  const from = `Counting from ${formatDate(arrived, { style: "short" })}, when the letter arrived`;
  const capped = items.filter((i) => i.computation?.rule_ids.includes(LATE_ARRIVAL_RULE));
  if (!capped.length) return `${from}.`;
  const step = capped[0]!.computation!.steps.find((s) => s.rule_id === LATE_ARRIVAL_RULE);
  const usual = step?.date ? formatDate(step.date, { style: "short" }) : "an earlier day";
  const why = `the letter arrived later than letters usually take, so to be safe we still count from ${usual}, when it would usually count as delivered. See “Why this date?”.`;
  if (capped.length === items.length) return why.charAt(0).toUpperCase() + why.slice(1);
  const which = capped.length === 1 ? `for “${capped[0]!.title}”` : `for ${capped.length} of these dates`;
  return `${from} — but ${which} ${why}`;
}

/** The law gives these an objection whatever their instructions say (§ 694, § 700 ZPO). */
const COURT_ORDERS = new Set<Document["kind"]>(["court_payment_order", "enforcement_order"]);

/**
 * A court's letter whose period runs from formal delivery (§ 180 ZPO), so the question is "when was it
 * delivered?" (the date on the yellow envelope), never "when did it arrive?" with a Today button: filed
 * as a court order, or any to-do whose receipt cites § 180 ZPO (a Versäumnisurteil's Einspruch, an
 * order filed as another kind) — the same test as {@link needsArrivalDate}.
 */
export function isServed(doc: Pick<Document, "kind">, items: Item[]): boolean {
  return COURT_ORDERS.has(doc.kind) || items.some((i) => Boolean(i.computation?.rule_ids.includes("zpo_180")));
}

/**
 * A court order: its objection deadline is not "only if you disagree" — doing nothing lets the claim
 * be enforced, so the person must pay or object.
 */
export function isCourtOrder(doc: Pick<Document, "kind">): boolean {
  return COURT_ORDERS.has(doc.kind);
}

/**
 * Letters whose law-set deadline is never "only if you disagree": a court order (pay or object, or it
 * is enforced), a dismissal (only a court action in time keeps the person's rights, and the
 * registration as job-seeking is due either way) and a landlord's notice (the home ends: have it
 * checked, and object in time if moving out is a hardship).
 */
const MUST_ACT = new Set<Document["kind"]>([...COURT_ORDERS, "dismissal", "landlord_notice"]);

export function mustAct(doc: Pick<Document, "kind">): boolean {
  return MUST_ACT.has(doc.kind);
}

/**
 * The person has dealt with the letter: it has to-dos, and they closed every one (done or dismissed) —
 * objected, went to court, registered. For a letter without a "get advice" card (an authority's decision).
 */
export function isSettled(items: Item[]): boolean {
  return !items.some(isOpenItem) && items.some((i) => i.status === "done" || i.status === "dismissed");
}

/**
 * Whether the letter is filed, never "get advice now" again: a high-stakes letter as its card says — the
 * server decides from the to-dos that carry its legal deadline (`advice.handled`: paying the arrears a
 * notice without notice period demands never settles it) — any other one once every to-do is closed.
 */
export function isLetterSettled(detail: Pick<DocumentDetail, "advice" | "items">): boolean {
  return detail.advice ? detail.advice.handled : isSettled(detail.items);
}

/** Why a payment may not be owed yet (see {@link notOwedReason}). */
export type NotOwed = "late_statement" | "consent" | "if_agreed";

/** A rent increase's consent decision (§ 558b BGB): the law's to-do, or the letter's own date for it — never a payment. */
function isConsentDecision(i: Item): boolean {
  return i.kind !== "payment" && Boolean(i.computation?.rule_ids.includes("bgb_558b"));
}

/**
 * The person has decided about a rent increase: it has a consent decision to-do, and they closed every one
 * (done or dismissed). Its new rent is then no longer "decide before you pay" — but closing the to-do only
 * says they decided, not which way (dismissing it is the natural way to say "I won't agree"), so the new
 * rent is owed only if they agreed ({@link notOwedReason}: `if_agreed`).
 */
export function consentDecided(items: Item[]): boolean {
  const decisions = items.filter(isConsentDecision);
  return decisions.length > 0 && !decisions.some(isOpenItem);
}

/**
 * Why money the person would pay may not be owed, or null: the back-payment of an operating-cost statement
 * that came after its twelve-month deadline (§ 556 Abs. 3 BGB; the server cites `bgb_556_3`, and the card
 * is urgent — so even an undated one is caught; never a credit or the new monthly prepayment), or a rent
 * increase's new rent, only owed once the person agrees (§ 558b Abs. 1 BGB; the server cites `bgb_558b`):
 * "decide first" until they closed the decision to-do among the letter's `items` ({@link consentDecided}),
 * then "only if you agreed" — Ordnung doesn't know which way they decided, and paying the higher rent can
 * count as agreeing, so it never leads with "Pay" for it.
 * It stays open (nothing is dismissed for the person), but "Pay" is no longer the main button.
 */
export function notOwedReason(i: Item, advice: DocumentDetail["advice"], items: Item[] = []): NotOwed | null {
  if (i.kind !== "payment" || i.direction === "in") return null;
  const cites = (rule: string) => Boolean(i.computation?.rule_ids.includes(rule));
  if (cites("bgb_558b") || advice?.kind === "rent_increase") return consentDecided(items) ? "if_agreed" : "consent";
  if (i.recurrence) return null;
  return cites("bgb_556_3") || (advice?.kind === "operating_costs" && advice.urgent) ? "late_statement" : null;
}

export function mayNotBeOwed(i: Item, advice: DocumentDetail["advice"], items: Item[] = []): boolean {
  return notOwedReason(i, advice, items) !== null;
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
 * objection (type comes from the Rechtsbehelfsbelehrung, never a guess), unless the person has dealt
 * with the letter ({@link isLetterSettled}) · a notice deadline on a
 * contract → draft the cancellation · a payment → Pay (not when it may not be owed, see
 * {@link mayNotBeOwed}) · a dated to-do → Add to calendar · otherwise Mark done.
 */
export function chooseMainAction(detail: DocumentDetail, primary: Item | null): MainAction {
  const scam = scamSuggestion(detail);
  if (scam) {
    const real = scam.refs.find((r) => r.type === "document" && r.id !== detail.document.id);
    return { type: "scam", realDocId: real?.id ?? null };
  }
  const remedy = detail.document.remedy?.type;
  const courtOrder = isCourtOrder(detail.document);
  // once the person dealt with the letter (objected, or paid), it is settled: no objection to draft
  const stillOpen = primary ? isOpenItem(primary) : !isLetterSettled(detail);
  if ((remedy === "einspruch" || remedy === "widerspruch" || courtOrder) && stillOpen) {
    return { type: "draft", draftKind: "objection", label: "Draft objection", item: primary };
  }
  if (!primary || !isOpenItem(primary)) return { type: "none" };
  if (primary.date_spec?.nature === "notice" && primary.contract_id) {
    return { type: "draft", draftKind: "cancellation", label: "Draft cancellation", item: primary };
  }
  if (
    primary.kind === "payment" &&
    primary.direction !== "in" &&
    primary.amount != null &&
    !isDirectDebit(primary) &&
    !mayNotBeOwed(primary, detail.advice, detail.items)
  )
    return { type: "pay", item: primary };
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
