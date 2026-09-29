/**
 * Verdict logic for the Document viewer: which to-do is "the one thing to do", what the main
 * button does, and which items need the person's eyes ("Please check", "When did it arrive?").
 * Pure functions, unit-tested in `verdict.test.ts`.
 */
import type { Document, DocumentDetail, Draft, DraftKind, Item, ItemAside, ItemKind, PartyKind, Priority, Suggestion } from "@/api/types";
import { formatDate, formatMoney } from "@/lib/format";
import { isDirectDebit, isIncomingMoney } from "@/lib/payments";
import { isGermanText } from "./fact-text";

const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, normal: 2, low: 3 };
const KIND_RANK: Record<ItemKind, number> = { deadline: 0, payment: 1, appointment: 2, expiry: 3, task: 4, reminder: 5, milestone: 6 };
/**
 * What a to-do asks of the person: a deadline or a payment is an obligation, anything else (an
 * appointment, an expiry, a task) is not — of two dated to-dos of the same priority, the obligation
 * is "the thing to do" (a scholarship's report deadline, not its optional autumn meeting).
 */
const OBLIGATION: ReadonlySet<ItemKind> = new Set<ItemKind>(["deadline", "payment"]);

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
 * (the rent is not "the thing to do" about a letter), dated before undated, obligations (a deadline,
 * a payment) before the rest (an appointment, an expiry, a task), earliest first, then by kind
 * (deadline > payment > appointment > …), then title for stability.
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
  const ob = Number(OBLIGATION.has(b.kind)) - Number(OBLIGATION.has(a.kind));
  if (ob) return ob;
  if (da && db && da !== db) return da < db ? -1 : 1;
  const kr = (KIND_RANK[a.kind] ?? 9) - (KIND_RANK[b.kind] ?? 9);
  if (kr) return kr;
  return a.title.localeCompare(b.title);
}

/**
 * The primary to-do of a letter (drives the verdict card). Null when nothing is open. Money coming
 * in (a tax refund) is never "what you need to do" — see {@link incomingMoney} — and neither is a
 * to-do the server set aside (`DocumentDetail.set_aside`, the same rules as Today): an invoice payment
 * its payment reminder took over, a date that was long past when the letter was read (an archived
 * lease's deposit, "362 days overdue"), a scam letter's demand.
 */
export function selectPrimaryItem(items: Item[], setAside: readonly Pick<ItemAside, "item_id">[] = []): Item | null {
  const aside = new Set(setAside.map((a) => a.item_id));
  const open = items.filter((i) => isOpenItem(i) && !isIncomingMoney(i) && !aside.has(i.id));
  if (!open.length) return null;
  return [...open].sort(compareItems)[0] ?? null;
}

/** An open to-do the server set aside, with why (see {@link selectPrimaryItem}). */
export interface AsideItem {
  item: Item;
  aside: ItemAside;
}

/**
 * The letter's open to-dos that are not one to act on, as the verdict lists them quietly under what to
 * do: replaced by a payment reminder ("pay that one, not both"), or history ("Still open?"). A scam
 * letter's are left out — its verdict already says "Don't pay".
 */
export function asideItems(detail: Pick<DocumentDetail, "items" | "set_aside">): AsideItem[] {
  const why = new Map((detail.set_aside ?? []).map((a) => [a.item_id, a]));
  return detail.items.flatMap((item) => {
    const aside = why.get(item.id);
    return aside && isOpenItem(item) && aside.reason !== "suspicious" ? [{ item, aside }] : [];
  });
}

/** The payment reminder that replaced this letter's payment (a document id), if any. */
export function replacedBy(detail: Pick<DocumentDetail, "items" | "set_aside">): string | null {
  return asideItems(detail).find((a) => a.aside.reason === "replaced")?.aside.replaced_by ?? null;
}

/** An open payment coming to the person with this letter (a refund), if any. */
export function incomingMoney(items: Item[]): Item | null {
  return items.find((i) => isOpenItem(i) && isIncomingMoney(i) && i.amount != null) ?? null;
}

/** An objection deadline: only matters if the person disagrees with the decision. */
export function isOptionalObjection(i: Pick<Item, "date_spec">): boolean {
  return i.date_spec?.nature === "objection";
}

/**
 * A price increase that asks for the person's consent (a bank's new account fee, § 675g BGB): agreeing is a
 * choice, not a to-do to get done by a date (walkthrough of phase 2: "Give consent to the fee increase — by
 * Mon 30 Nov" nudged the person to accept, where the Stadtwerke's increase was put as a decision).
 */
export function isConsentRequest(i: Pick<Item, "kind" | "title" | "action">, doc: Pick<Document, "kind">): boolean {
  return doc.kind === "price_increase" && i.kind !== "payment" && /\bconsent\b|zustimm/i.test(`${i.title} ${i.action ?? ""}`);
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
 * increase's new rent, only owed once the person agrees (§ 558b Abs. 1 BGB; the server cites `bgb_558b` on the
 * new rent alone, dated or not — never on the current rent):
 * "decide first" until they closed the decision to-do among the letter's `items` ({@link consentDecided}),
 * then "only if you agreed" — Ordnung doesn't know which way they decided, and paying the higher rent can
 * count as agreeing, so it never leads with "Pay" for it.
 * It stays open (nothing is dismissed for the person), but "Pay" is no longer the main button.
 */
export function notOwedReason(i: Item, advice: DocumentDetail["advice"], items: Item[] = []): NotOwed | null {
  if (i.kind !== "payment" || i.direction === "in") return null;
  const cites = (rule: string) => Boolean(i.computation?.rule_ids.includes(rule));
  // only the new rent cites § 558b for its note — never the current rent, which is owed as ever (holding it back
  // risks arrears, § 543 Abs. 2 Nr. 3 BGB): the server marks the new rent, dated or not (review round 2)
  if (cites("bgb_558b")) return consentDecided(items) ? "if_agreed" : "consent";
  if (i.recurrence) return null;
  return cites("bgb_556_3") || (advice?.kind === "operating_costs" && advice.urgent) ? "late_statement" : null;
}

export function mayNotBeOwed(i: Item, advice: DocumentDetail["advice"], items: Item[] = []): boolean {
  return notOwedReason(i, advice, items) !== null;
}

/**
 * The other open deadlines the law sets for this letter (a dismissal's registration), earliest first —
 * never one the server set aside (`setAside`, as {@link selectPrimaryItem}): a date already past when the
 * letter was added is listed quietly under "Probably dealt with", not also as "Also: … 189 days overdue"
 * (UI audit round 2).
 */
export function otherLawDeadlines(items: Item[], primary: Item | null, setAside: readonly Pick<ItemAside, "item_id">[] = []): Item[] {
  const aside = new Set(setAside.map((a) => a.item_id));
  return items
    .filter((i) => i.origin === "rule" && isOpenItem(i) && i.id !== primary?.id && i.due_date && !aside.has(i.id))
    .sort(compareItems);
}

export type MainAction =
  | { type: "draft"; draftKind: Extract<DraftKind, "objection" | "cancellation">; label: string; item: Item | null }
  | { type: "pay"; item: Item }
  | { type: "calendar"; item: Item }
  | { type: "done"; item: Item }
  | { type: "scam"; realDocId: string | null }
  | { type: "decide"; suggestion: Suggestion }
  /** The payment reminder that took over this letter's payment: open it (and pay that one). */
  | { type: "reminder"; docId: string }
  | { type: "none" };

/**
 * The one main button of the verdict card:
 * scam → never "Pay" (offer to compare with a real letter) · Einspruch/Widerspruch → draft the
 * objection (type comes from the Rechtsbehelfsbelehrung, never a guess), unless the person has dealt
 * with the letter ({@link isLetterSettled}) or every open to-do was set aside (an archived letter) · an
 * invoice a payment reminder replaced → open the reminder (never Pay twice) · a notice deadline on a
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
  const aside = asideItems(detail);
  const allAside = aside.length > 0 && !primary;
  // once the person dealt with the letter (objected, or paid), it is settled: no objection to draft
  const stillOpen = primary ? isOpenItem(primary) : !allAside && !isLetterSettled(detail);
  if ((remedy === "einspruch" || remedy === "widerspruch" || courtOrder) && stillOpen) {
    return { type: "draft", draftKind: "objection", label: "Draft objection", item: primary };
  }
  const reminder = replacedBy(detail);
  if (!primary && reminder) return { type: "reminder", docId: reminder };
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
 * The draft of this kind the person already started about the letter (the newest), if any: the
 * verdict then offers to continue it instead of drafting a second one.
 */
export function existingDraft(drafts: readonly Draft[], kind: DraftKind): Draft | null {
  return [...drafts].filter((d) => d.kind === kind).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0] ?? null;
}

/**
 * Rules that apply no law — the letter's own date, Ordnung's safety margin for the post, a date an
 * authority set — so a date computed only with them needs no "Based on the law as of …" disclaimer
 * (a passport's expiry, a dentist's appointment).
 */
const NO_LAW = new Set(["date_as_written", "authority_deadline", "postal_buffer"]);
/** A bank's execution time (§ 675s BGB) — nothing to transfer for a direct debit. */
const TRANSFER_TIME = "bgb_675s";

/** Whether the to-do's date was worked out with a legal rule (then the verdict shows the legal disclaimer). */
export function usesLaw(item: Pick<Item, "computation" | "kind" | "title" | "action" | "description">): boolean {
  const debit = isDirectDebit(item);
  return (item.computation?.rule_ids ?? []).some((r) => !NO_LAW.has(r) && !(debit && r === TRANSFER_TIME));
}

// ------------------------------------------------------------------------------------------------
// Words: the verdict leads in English, the letter's German follows as a quote
// ------------------------------------------------------------------------------------------------

/** A title word longer than this (a German compound) gets the smaller headline size on phones. */
const LONG_WORD = 20;

/** Whether a title has a word too long for the big headline at 320 px ("(Immatrikulationsbescheinigung)"). */
export function hasLongWord(title: string): boolean {
  return title.split(/\s+/).some((w) => w.length > LONG_WORD);
}

/** An action longer than this reads as a paragraph (the law behind it), not a headline. */
export const HEADLINE_CHARS = 140;

export interface VerdictWords {
  /** The headline — always English. */
  lead: string;
  /** A paragraph-long English action under the headline, or null. */
  body: string | null;
  /** The to-do's own title under the headline when it adds something (it may be German: marked so). */
  sub: string | null;
  /** The letter's German words, shown under the English as "The letter says: …", or null. */
  quote: string | null;
}

const PER: Partial<Record<string, string>> = { "1 months": " a month", "1 years": " a year", "3 months": " a quarter", "1 weeks": " a week" };

/**
 * An English headline from what the to-do is — for when the reading gave the action and the title only
 * in German ("Semesterbeitrag von 312,40 € rechtzeitig überweisen"): "Pay €312.40 to Hochschule
 * Musterstadt", "Keep €63.00 a month in your account for the direct debit", "Go to the appointment".
 */
export function plainLead(item: Item, party?: string | null): string {
  const money = item.amount != null ? formatMoney(item.amount, { currency: item.currency }) : null;
  const per = item.recurrence ? (PER[`${item.recurrence.interval} ${item.recurrence.unit}`] ?? "") : "";
  switch (item.kind) {
    case "payment":
      if (item.direction === "in") return money ? `${money}${per} comes to you` : "Money comes to you";
      if (isDirectDebit(item)) return `Keep ${money ? `${money}${per}` : "the money"} in your account for the direct debit`;
      return money ? `Pay ${money}${per}${party ? ` to ${party}` : ""}` : `Pay what the letter asks for${party ? ` to ${party}` : ""}`;
    case "appointment":
      return "Go to the appointment";
    case "expiry":
      return "Renew it in time if you still need it";
    case "deadline":
      switch (item.date_spec?.nature) {
        case "objection":
          return "Object in time if you disagree";
        case "notice":
          return "Cancel in time if you want to";
        case "payment":
          return money ? `Pay ${money} in time` : "Pay in time";
        case "declaration":
          return "Send what the letter asks for in time";
        default:
          return "Do what the letter asks in time";
      }
    default:
      return "Do what the letter asks";
  }
}

/**
 * What the verdict says to do, always led by English: the reading's action when it is English, else
 * the to-do's English title, else {@link plainLead} — with the letter's German below it as a quote, never
 * as the headline (UI audit round 1: "WHAT YOU NEED TO DO — Semesterbeitrag … überweisen"). An
 * appointment without an action says where to go ("Go to: Autumn Meeting in Berlin").
 */
export function verdictWords(item: Item, party?: string | null): VerdictWords {
  const action = item.action?.trim() || null;
  const title = item.title.trim();
  const titleEnglish = title && !isGermanText(title) ? title : null;
  const english = (): string => {
    if (!titleEnglish) return plainLead(item, party);
    return item.kind === "appointment" && !action && !titleEnglish.includes(":") ? `Go to: ${titleEnglish}` : titleEnglish;
  };
  if (action && !isGermanText(action)) {
    if (action.length > HEADLINE_CHARS && action !== title) {
      // a paragraph of law is no headline: the title leads, the action follows as body text
      return { lead: english(), body: action, sub: null, quote: titleEnglish ? null : title };
    }
    return { lead: action, body: null, sub: action !== title ? title : null, quote: null };
  }
  const quote = action ?? (titleEnglish ? null : title);
  return { lead: english(), body: null, sub: null, quote: quote || null };
}

/** German words in a consequence and what they mean ("Säumnisgebühr" → "a late fee"), in the order they are said. */
const CONSEQUENCES: [RegExp, string][] = [
  [/Säumnis(?:gebühr|zuschlag)|Verspätungszuschlag/i, "a late fee"],
  [/Mahn(?:gebühr|kosten)/i, "reminder fees"],
  [/Verzugszins|Zinsen/i, "interest"],
  [/Inkasso/i, "debt collection"],
  [/(?:weitere|zusätzliche|Mehr)\s*[Kk]osten|Kosten entstehen/i, "extra costs"],
  [/Mahnbescheid|(?<!außer)gerichtlich|Klage/i, "court action"],
  [/Vollstreckung|Pfändung/i, "enforcement"],
  [/Exmatrikulation|exmatrikuliert/i, "losing your place at the university"],
  [/Kündigung|gekündigt|kündigen/i, "the contract being ended"],
  [/Sperr(?:e|ung)|gesperrt/i, "a block"],
  [/bestandskräftig|rechtskräftig|unanfechtbar/i, "the decision becoming final"],
  [/Bußgeld/i, "a fine"],
  [/Schufa/i, "an entry with the credit agency (SCHUFA)"],
  [/Versicherungsschutz/i, "losing your insurance cover"],
];

const joinList = (parts: string[]): string =>
  parts.length < 2 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;

/**
 * "If you ignore it", in English first: an English consequence as it is; a German one as what it warns
 * of ("The letter warns of a late fee and being de-registered from the university.") with the letter's
 * words below as a quote.
 */
export function consequenceWords(text: string): { lead: string; quote: string | null } {
  const t = text.trim();
  if (!isGermanText(t)) return { lead: t, quote: null };
  const found = CONSEQUENCES.filter(([re]) => re.test(t))
    .map(([re, en]) => ({ en, at: t.search(re) }))
    .sort((a, b) => a.at - b.at)
    .map((c) => c.en);
  const warns = [...new Set(found)];
  return { lead: warns.length ? `The letter warns of ${joinList(warns)}.` : "The letter names what happens then:", quote: t };
}
