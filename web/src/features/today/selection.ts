/**
 * Today page logic — pure functions, no React, fully unit-tested (`selection.test.ts`).
 *
 * - {@link buildCandidates} turns the dashboard (attention + upcoming to-dos & dates, contract
 *   decisions) into uniform "actions" with an action date, a verb and an urgency score.
 * - {@link pickTopThree} chooses the three most urgent actions for "Top 3 this week".
 * - {@link groupByWeek} groups the rest into "Coming up · next 30 days".
 * - {@link selectIdeas}, {@link ideaFigure}, {@link agendaSentence}, {@link greetingFor},
 *   {@link stripGreeting} and {@link allClearTitle} cover the remaining sections.
 *
 * All dates are ISO `YYYY-MM-DD` strings compared against the app's today (never the browser
 * clock), so the demo's simulated date works.
 */
import { addDays, differenceInCalendarDays, format, parseISO, startOfWeek } from "date-fns";
import type {
  Contract,
  Dashboard,
  Document,
  DraftKind,
  Item,
  ItemKind,
  Priority,
  Suggestion,
} from "@/api/types";
import { addToTotals, formatDate, formatMoney, type Totals } from "@/lib/format";
import { offersEndingLetter } from "@/features/contracts/links";
import { cancellationSent, noticeFromYou } from "@/features/contracts/model";
import { isDirectDebit } from "@/lib/payments";

// ------------------------------------------------------------------------------------------------
// Types
// ------------------------------------------------------------------------------------------------

/** The one verb button of an action card. */
export type ActionVerb = "pay" | "draft" | "done" | "check" | "open";

/** What the date of an action means — drives the countdown prefix ("send by", "pay by"…). */
export type DateRole = "send_by" | "arrive_by" | "pay_by" | "transfer_by" | "collected" | "due" | "by" | "on" | "expires" | "decide_by";

/** How a to-do's receipt says the usual time to post has passed (`SENDING_TIME_PASSED` in
 * `ordnung.rules.deadlines`; a backend test reads this file): its send-by is only "today", and a letter
 * posted today may arrive too late — the date that counts is when it must arrive (review round 4 of phase 2). */
export const SENDING_TIME_PASSED = "The usual sending time has passed";

/** Whether the usual time to post an item's letter has passed (its receipt says so). */
export function postTooLate(item: Pick<Item, "send_by" | "due_date" | "computation">): boolean {
  return Boolean(item.send_by && item.due_date && item.computation?.warnings.some((w) => w.startsWith(SENDING_TIME_PASSED)));
}

export interface TodayAction {
  /** `item:<id>` or `contract:<id>` */
  key: string;
  source: "item" | "contract";
  item: Item | null;
  contract: Contract | null;
  title: string;
  /** The day the person must act by: send-by for letters, else the due date. */
  actionDate: string;
  /** The real due date (e.g. must-arrive-by), when different from the action date. */
  dueDate: string | null;
  dateRole: DateRole;
  time: string | null;
  kind: ItemKind | "contract";
  priority: Priority;
  partyId: string | null;
  docId: string | null;
  contractId: string | null;
  amount: number | null;
  currency: string | null;
  /** Something about this date needs the person's eyes ("Please check"). */
  needsCheck: boolean;
  /** One-line reason shown on the card. */
  reason: string | null;
  verb: ActionVerb;
  /** For `draft`: which letter to write. */
  draftKind: DraftKind | null;
  /** Calendar days from today to the action date (negative = overdue). */
  daysLeft: number;
  /** Lower = more urgent. See {@link urgencyScore}. */
  score: number;
}

export interface CandidateContext {
  today: string;
  /** Documents with status "Please check" (their warnings explain why). */
  reviewDocs?: readonly Pick<Document, "id" | "warnings">[];
  /** Letter titles by document id — the last-resort reason ("From “Library: overdue books”"). */
  docTitles?: ReadonlyMap<string, string>;
}

// ------------------------------------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------------------------------------

const PRIORITY_WEIGHT: Record<Priority, number> = { low: 0, normal: 1, high: 2, critical: 3 };

/** Legal deadlines and payments carry consequences (fees, lost rights) — nudge them up a little. */
const KIND_WEIGHT: Record<ItemKind | "contract", number> = {
  deadline: 1,
  payment: 1,
  contract: 1,
  appointment: 0,
  task: 0,
  expiry: 0,
  reminder: 0,
  milestone: 0,
};

export function daysBetween(date: string, today: string): number {
  return differenceInCalendarDays(parseISO(date), parseISO(today));
}

/**
 * Urgency score (lower = more urgent): days left, minus 2 per priority level, minus 3 when the
 * date needs checking (an unconfirmed date is computed as early as possible — act on it), minus 1
 * for deadlines/payments/contract decisions. Mirrors the backend's attention ordering.
 */
export function urgencyScore(a: Pick<TodayAction, "daysLeft" | "priority" | "needsCheck" | "kind">): number {
  return a.daysLeft - 2 * PRIORITY_WEIGHT[a.priority] - (a.needsCheck ? 3 : 0) - KIND_WEIGHT[a.kind];
}

/** Stable comparator: score, then action date, then priority, then larger amount, then title. */
export function compareActions(a: TodayAction, b: TodayAction): number {
  return (
    a.score - b.score ||
    a.actionDate.localeCompare(b.actionDate) ||
    PRIORITY_WEIGHT[b.priority] - PRIORITY_WEIGHT[a.priority] ||
    (b.amount ?? 0) - (a.amount ?? 0) ||
    a.title.localeCompare(b.title)
  );
}

/** Is the item currently open (open, or snoozed until a day that has come)? */
export function isOpen(item: Pick<Item, "status" | "snoozed_until">, today: string): boolean {
  return item.status === "open" || (item.status === "snoozed" && (!item.snoozed_until || item.snoozed_until <= today));
}

/** Which letter an item asks for, if any (cancellation for contract notice dates, objection for remedies). */
export function draftKindFor(item: Item): DraftKind | null {
  const nature = item.date_spec?.nature;
  if (nature === "objection") return "objection";
  if (item.contract_id && (item.kind === "deadline" || nature === "notice")) return "cancellation";
  return null;
}

function needsCheckFor(item: Item, reviewIds: Set<string>): boolean {
  return (
    item.grounding === "unverified" ||
    item.computation?.confidence === "low" ||
    item.evidence.some((e) => e.grounding === "unverified" || !e.value_consistent) ||
    (item.doc_id !== null && reviewIds.has(item.doc_id))
  );
}

function verbFor(item: Item, needsCheck: boolean, draftKind: DraftKind | null): ActionVerb {
  if (needsCheck) return "check";
  if (item.kind === "payment" && item.direction !== "in") return isDirectDebit(item) ? "open" : "pay";
  if (draftKind) return "draft";
  if (item.kind === "task" || item.kind === "reminder") return "done";
  return "open";
}

function roleFor(item: Item): DateRole {
  // money: a transfer has to leave the account in time; a direct debit is collected by the sender
  if (item.kind === "payment" && item.direction !== "in") return isDirectDebit(item) ? "collected" : item.send_by ? "transfer_by" : "pay_by";
  if (postTooLate(item)) return "arrive_by";
  if (item.send_by) return "send_by";
  switch (item.kind) {
    case "payment":
      return item.direction === "in" ? "on" : "pay_by";
    case "appointment":
    case "milestone":
    case "reminder":
      return "on";
    case "expiry":
      return "expires";
    case "task":
      return "by";
    default:
      return "due";
  }
}

function firstSentence(text: string | null | undefined): string | null {
  const t = text?.trim();
  return t ? t : null;
}

function reasonForItem(
  item: Item,
  needsCheck: boolean,
  docWarnings: Map<string, string[]>,
  docTitles: ReadonlyMap<string, string> | undefined,
): string | null {
  if (needsCheck) {
    const w = item.computation?.warnings[0] ?? (item.doc_id ? docWarnings.get(item.doc_id)?.[0] : undefined);
    if (w) return w;
  }
  const title = item.doc_id ? docTitles?.get(item.doc_id) : undefined;
  return (
    firstSentence(item.description) ??
    firstSentence(item.action) ??
    firstSentence(item.consequence) ??
    (title ? `From your letter “${title}”.` : null)
  );
}

// ------------------------------------------------------------------------------------------------
// Candidates
// ------------------------------------------------------------------------------------------------

/** Build an action from a to-do or date. Returns null for closed or undated items. */
export function actionFromItem(item: Item, ctx: CandidateContext): TodayAction | null {
  if (!isOpen(item, ctx.today)) return null;
  // a direct debit happens on its due date — there is no "send by"; nor is there once posting is too late
  const late = item.kind !== "payment" && postTooLate(item);
  const actionDate = isDirectDebit(item) || late ? item.due_date : item.send_by ?? item.due_date;
  if (!actionDate) return null;
  const reviewIds = new Set((ctx.reviewDocs ?? []).map((d) => d.id));
  const docWarnings = new Map((ctx.reviewDocs ?? []).map((d) => [d.id, d.warnings] as const));
  const needsCheck = needsCheckFor(item, reviewIds);
  const draftKind = draftKindFor(item);
  const daysLeft = daysBetween(actionDate, ctx.today);
  const base = {
    key: `item:${item.id}`,
    source: "item" as const,
    item,
    contract: null,
    title: item.title,
    actionDate,
    dueDate: item.send_by && !late && item.due_date && item.due_date !== item.send_by ? item.due_date : null,
    dateRole: roleFor(item),
    time: item.send_by && !late ? null : item.due_time,
    kind: item.kind,
    priority: item.priority,
    partyId: item.party_id,
    docId: item.doc_id,
    contractId: item.contract_id,
    amount: item.amount,
    currency: item.currency,
    needsCheck,
    reason: reasonForItem(item, needsCheck, docWarnings, ctx.docTitles),
    verb: verbFor(item, needsCheck, draftKind),
    draftKind,
    daysLeft,
  };
  return { ...base, score: urgencyScore(base) };
}

/** Build a "decide on this contract" action from a contract with a send-by / cancel-by date. */
export function actionFromContract(contract: Contract, ctx: CandidateContext): TodayAction | null {
  const c = contract.computed;
  if (!offersEndingLetter(contract) || !c) return null; // e.g. the broadcasting fee: nothing to decide
  if (cancellationSent(contract)) return null; // its cancellation was sent: decided (walkthrough of phase 2)
  const actionDate = c.send_by ?? c.cancel_by;
  if (!actionDate) return null;
  const daysLeft = daysBetween(actionDate, ctx.today);
  if (daysLeft < 0) return null; // a passed decision date is not an action any more
  // low confidence asks for a check — not once the person entered the notice period (as on its card)
  const needsCheck = c.confidence === "low" && !noticeFromYou(contract);
  const base = {
    key: `contract:${contract.id}`,
    source: "contract" as const,
    item: null,
    contract,
    title: `Decide on ${contract.name}`,
    actionDate,
    dueDate: c.send_by && c.cancel_by && c.cancel_by !== c.send_by ? c.cancel_by : null,
    dateRole: (c.send_by ? "send_by" : "decide_by") as DateRole,
    time: null,
    kind: "contract" as const,
    priority: (daysLeft <= 14 ? "high" : "normal") as Priority,
    partyId: contract.party_id,
    docId: contract.source_doc_id,
    contractId: contract.id,
    amount: null,
    currency: null,
    needsCheck,
    reason: firstSentence(c.summary) ?? (needsCheck ? c.warnings[0] ?? null : null),
    verb: "draft" as ActionVerb,
    draftKind: "cancellation" as DraftKind,
    daysLeft,
  };
  return { ...base, score: urgencyScore(base) };
}

/**
 * All actions from the dashboard: attention + upcoming to-dos & dates, plus contract decisions
 * that no open to-do already covers (the "cancel phone contract" to-do *is* the decision).
 * De-duplicated and sorted most urgent first.
 */
export function buildCandidates(
  dash: Pick<Dashboard, "attention" | "upcoming" | "decisions">,
  ctx: CandidateContext,
): TodayAction[] {
  const byKey = new Map<string, TodayAction>();
  for (const item of [...dash.attention, ...dash.upcoming]) {
    const a = actionFromItem(item, ctx);
    if (a && !byKey.has(a.key)) byKey.set(a.key, a);
  }
  const coveredContracts = new Set(
    [...byKey.values()].filter((a) => a.item?.contract_id && a.item.kind === "deadline").map((a) => a.item!.contract_id!),
  );
  for (const contract of dash.decisions) {
    if (coveredContracts.has(contract.id)) continue;
    const a = actionFromContract(contract, ctx);
    if (a && !byKey.has(a.key)) byKey.set(a.key, a);
  }
  return [...byKey.values()].sort(compareActions);
}

export interface TopThreeOptions {
  /** How many to pick (default 3). */
  limit?: number;
  /** Only actions due within this many days qualify (default 14; overdue always qualifies). */
  horizonDays?: number;
}

/**
 * The most urgent actions for "Top 3 this week": sorted by urgency, within the horizon, and at most
 * one per person/organisation (the library fee and "return the books" are one errand — the second
 * one stays in "Coming up").
 */
export function pickTopThree(candidates: readonly TodayAction[], opts: TopThreeOptions = {}): TodayAction[] {
  const limit = opts.limit ?? 3;
  const horizon = opts.horizonDays ?? 14;
  const out: TodayAction[] = [];
  const parties = new Set<string>();
  for (const a of [...candidates].sort(compareActions)) {
    if (out.length >= limit) break;
    if (a.daysLeft > horizon) continue;
    if (a.partyId && parties.has(a.partyId)) continue;
    out.push(a);
    if (a.partyId) parties.add(a.partyId);
  }
  return out;
}

/** An action that sends money out (a transfer or a direct debit — both leave the account). */
export function isOutgoingPayment(a: Pick<TodayAction, "kind" | "item" | "amount">): boolean {
  return a.kind === "payment" && a.item?.direction !== "in" && Boolean(a.amount);
}

/**
 * "To pay · next 30 days" per currency: every outgoing payment whose day to act is within `days`
 * days — Top 3 included — plus ones that became overdue in the last month (older ones are history,
 * not a bill).
 */
export function toPayTotals(actions: readonly TodayAction[], days = 30): Totals {
  return actions
    .filter((a) => isOutgoingPayment(a) && a.daysLeft <= days && a.daysLeft >= -30)
    .reduce<Totals>((totals, a) => addToTotals(totals, a.amount ?? 0, a.currency), {});
}

/** The euro part of {@link toPayTotals} (a $50 invoice is not €50 of it). */
export function toPayWithin(actions: readonly TodayAction[], days = 30): number {
  return toPayTotals(actions, days).EUR ?? 0;
}

// ------------------------------------------------------------------------------------------------
// Coming up
// ------------------------------------------------------------------------------------------------

export interface WeekGroup<T> {
  /** "overdue" or the ISO Monday of the week */
  key: string;
  /** "Overdue", "This week", "Next week", "12 – 18 Oct" */
  label: string;
  /** "28 Sep – 4 Oct" for this and next week (empty for overdue and later weeks, whose label is their days) */
  range: string;
  entries: T[];
  /** Sum of outgoing payments in the group, per currency */
  totals: Totals;
}

/**
 * Group dated entries by calendar week (Monday first, as in Germany): "Overdue", "This week",
 * "Next week", "12 – 18 Oct". Entries after `today + days` are dropped. Sorted by date.
 */
export function groupByWeek<T extends { date: string; amount?: number | null; currency?: string | null; outgoing?: boolean }>(
  entries: readonly T[],
  today: string,
  days = 30,
): WeekGroup<T>[] {
  const t = parseISO(today);
  const limit = format(addDays(t, days), "yyyy-MM-dd");
  const thisWeek = startOfWeek(t, { weekStartsOn: 1 });
  const groups = new Map<string, WeekGroup<T>>();
  const sorted = [...entries].filter((e) => e.date <= limit).sort((a, b) => a.date.localeCompare(b.date));
  for (const e of sorted) {
    let key: string;
    let label: string;
    let range = "";
    if (e.date < today) {
      key = "overdue";
      label = "Overdue";
    } else {
      const monday = startOfWeek(parseISO(e.date), { weekStartsOn: 1 });
      key = format(monday, "yyyy-MM-dd");
      const weeks = Math.round(differenceInCalendarDays(monday, thisWeek) / 7);
      const sunday = addDays(monday, 6);
      const days =
        monday.getMonth() === sunday.getMonth()
          ? `${format(monday, "d")} – ${format(sunday, "d MMM")}`
          : `${format(monday, "d MMM")} – ${format(sunday, "d MMM")}`;
      // later weeks are named by their days ("12 – 18 Oct", not "Week of 12 Oct 12 – 18 Oct")
      label = weeks === 0 ? "This week" : weeks === 1 ? "Next week" : days;
      range = weeks <= 1 ? days : "";
    }
    let g = groups.get(key);
    if (!g) {
      g = { key, label, range, entries: [], totals: {} };
      groups.set(key, g);
    }
    g.entries.push(e);
    if (e.outgoing && e.amount) g.totals = addToTotals(g.totals, e.amount, e.currency);
  }
  return [...groups.values()].sort((a, b) => (a.key === "overdue" ? -1 : b.key === "overdue" ? 1 : a.key.localeCompare(b.key)));
}

// ------------------------------------------------------------------------------------------------
// Ideas
// ------------------------------------------------------------------------------------------------

/** Rule id of the "N new dates since your last calendar update" Idea (shown as its own card). */
export const CALENDAR_RULE = "calendar_outdated";

export interface SelectIdeasOptions {
  /** Item ids already shown in Top 3 — Ideas about them would repeat the same thing. */
  shownItemIds?: ReadonlySet<string>;
  /** Ideas that just arrived with new mail: always shown, on top (the "New" badge). */
  pinnedIds?: ReadonlySet<string>;
  max?: number;
}

/**
 * Ideas for Today: new ones, minus the calendar Idea (own card) and Ideas that only repeat a Top-3
 * action. Ideas that just arrived with new mail first, then possible scams, then by priority, then
 * newest.
 */
export function selectIdeas(suggestions: readonly Suggestion[], opts: SelectIdeasOptions = {}): { shown: Suggestion[]; more: Suggestion[] } {
  const shownItems = opts.shownItemIds ?? new Set<string>();
  const pinned = opts.pinnedIds ?? new Set<string>();
  const max = opts.max ?? 3;
  const eligible = suggestions
    .filter((s) => s.status === "new" && s.rule_id !== CALENDAR_RULE)
    .filter((s) => pinned.has(s.id) || s.kind === "scam" || !s.refs.some((r) => r.type === "item" && shownItems.has(r.id)))
    .sort(
      (a, b) =>
        Number(pinned.has(b.id)) - Number(pinned.has(a.id)) ||
        Number(b.kind === "scam") - Number(a.kind === "scam") ||
        PRIORITY_WEIGHT[b.priority] - PRIORITY_WEIGHT[a.priority] ||
        b.created_at.localeCompare(a.created_at),
    );
  return { shown: eligible.slice(0, max), more: eligible.slice(max) };
}

/** The calendar Idea, when there is one. */
export function calendarIdea(suggestions: readonly Suggestion[]): Suggestion | null {
  return suggestions.find((s) => s.rule_id === CALENDAR_RULE && s.status === "new") ?? null;
}

export interface IdeaFigure {
  tone: "ok" | "warn";
  label: string;
}

/**
 * The money figure of an Idea (yearly amount). Savings and opportunities read "Could save about
 * 756 € a year"; anything else (price increases, fees) is an extra cost — SPEC §21: never call a
 * price increase "savings".
 */
export function ideaFigure(s: Pick<Suggestion, "kind" | "savings_estimate">): IdeaFigure | null {
  const v = s.savings_estimate;
  if (v === null || v === undefined || !Number.isFinite(v) || v <= 0) return null;
  const money = formatMoney(v, { decimals: "auto" });
  if (s.kind === "saving" || s.kind === "opportunity" || s.kind === "tax") return { tone: "ok", label: `Could save about ${money} a year` };
  return { tone: "warn", label: `+${money}/year extra cost` };
}

/** Is this Idea from today (for the "New" badge)? */
export function isFreshIdea(s: Pick<Suggestion, "created_at">, today: string): boolean {
  return s.created_at.slice(0, 10) >= today;
}

/**
 * Where the letters composer opens for an Idea / action — the parameters the composer reads
 * (`parsePrefill`): `/letters?kind=…&contract=…&doc=…&to=<party>` (`to`, not `party`, which would
 * open the People & organisations drawer instead).
 */
export function composerHref(kind: DraftKind, target: { contractId?: string | null; docId?: string | null; partyId?: string | null }): string {
  const q = new URLSearchParams({ kind });
  if (target.contractId) q.set("contract", target.contractId);
  if (target.docId) q.set("doc", target.docId);
  if (target.partyId) q.set("to", target.partyId);
  return `/letters?${q.toString()}`;
}

// ------------------------------------------------------------------------------------------------
// Words
// ------------------------------------------------------------------------------------------------

/** "Good morning" (5–11), "Good afternoon" (12–17), "Good evening". */
export function greetingFor(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}

/** Drop a leading "Good morning, Sam." from the note (the page already greets). */
export function stripGreeting(text: string): string {
  const out = text.replace(/^\s*(good\s+(morning|afternoon|evening)|hi|hello|guten\s+(morgen|tag|abend))\b[^.!?\n]{0,40}[.!?]\s*/i, "");
  return out.trim() || text.trim();
}

function shortDay(date: string, today: string): string {
  const n = daysBetween(date, today);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n > 1 && n < 7) return format(parseISO(date), "EEEE");
  return formatDate(date, { style: "short", today });
}

const LEADING_VERBS = /^(Pay|Return|Submit|Cancel|Prepare|Decide|Follow|Renew|Send|Check|Call|Book|Bring|Apply|Reply|Answer|Sign|Transfer)\b/;

/** "Pay the parking fine" → "pay the parking fine"; proper nouns ("Ausländerbehörde: …") stay as they are. */
function verbPhrase(a: TodayAction): string {
  return LEADING_VERBS.test(a.title) ? a.title.charAt(0).toLowerCase() + a.title.slice(1) : a.title;
}

/**
 * Code-generated fallback for the secretary's note (when the AI note is unavailable): one or two
 * plain sentences built only from the ledger, so every date and amount is right by construction.
 */
export function agendaSentence(top: readonly TodayAction[], upcoming: readonly TodayAction[], today: string, waiting = 0): string {
  // letters from the watched folder nobody read: their dates are unknown, so nothing is "all clear"
  const unread = waiting ? ` ${waiting === 1 ? "One letter" : `${waiting} letters`} from your folder ${waiting === 1 ? "isn't" : "aren't"} read yet.` : "";
  if (!top.length) {
    const next = upcoming[0];
    if (waiting) return `Nothing due from the letters that were read.${unread}`;
    if (!next) return "Nothing needs you right now. New letters will show up here as soon as they're read.";
    return `Nothing needs you this week. Next up: ${verbPhrase(next)} ${next.dateRole === "on" ? "on" : "by"} ${shortDay(next.actionDate, today)}.`;
  }
  const parts = top.map((a) => {
    const amount = a.amount ? ` (${formatMoney(a.amount, { currency: a.currency })})` : "";
    const when = a.daysLeft < 0 ? "— overdue" : `${a.dateRole === "on" ? "on" : "by"} ${shortDay(a.actionDate, today)}`;
    return `${verbPhrase(a)}${amount} ${when}`;
  });
  const n = top.length;
  const head = n === 1 ? "One thing this week:" : n === 2 ? "Two things this week:" : "Three things this week:";
  const list = parts.length > 1 ? `${parts.slice(0, -1).join("; ")}; and ${parts[parts.length - 1]}` : parts[0];
  const check = top.find((a) => a.needsCheck);
  const tail = check ? " One date needs a quick check from you." : "";
  return `${head} ${list}.${tail}${unread}`;
}

/** "All clear until Friday" (next date within a week) / "until Wed 14 Oct" / "All clear". */
export function allClearTitle(nextDate: string | null | undefined, today: string): string {
  if (!nextDate) return "All clear";
  const n = daysBetween(nextDate, today);
  if (n <= 1) return "All clear for today";
  if (n < 7) return `All clear until ${format(parseISO(nextDate), "EEEE")}`;
  return `All clear until ${formatDate(nextDate, { style: "short", today })}`;
}
