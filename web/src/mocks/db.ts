/**
 * In-memory mock database: a deep copy of the sample life that mutations modify, plus the
 * computed views the real API derives (dashboard, timeline, lanes, search).
 */
import type {
  AreaStatus,
  Case,
  ChatMessage,
  Contract,
  ContractComputation,
  Dashboard,
  DateSpec,
  Document,
  Draft,
  Evidence,
  Item,
  ItemCreate,
  Lane,
  LaneBar,
  MailTrayItem,
  Party,
  Recurrence,
  Suggestion,
  TimelineEntry,
  TimelineMarker,
  TourState,
  Activity,
  Profile,
  AppSettings,
  Health,
  Area,
  FolderPickup,
  CallNote,
  Proof,
} from "@/api/types";
import { addDays, differenceInCalendarDays, parseISO, format } from "date-fns";
import { PARTIES, TRAY_ONLY_PARTIES } from "./data/parties";
import { CASES, DOCUMENTS, TRAY_CASES, TRAY_DOCUMENTS } from "./data/documents";
import { ITEMS, TRAY_ITEMS } from "./data/items";
import { CONTRACTS } from "./data/contracts";
import { SUGGESTIONS, TRAY_SUGGESTIONS } from "./data/suggestions";
import { DRAFTS } from "./data/drafts";
import { ACTIVITY, HEALTH, MAIL_TRAY, PROFILE, SETTINGS, TOUR, TRAY_DOC } from "./data/system";
import { LETTERS } from "./data/letters";
import { FOLDER_DOCUMENTS, FOLDER_LETTERS, FOLDER_RECENT } from "./data/folder";
import { renderLetter, type RenderedLetter } from "./pages";
import { TODAY } from "./data/constants";
import { item as makeItem, spec } from "./data/helpers";
import { dayStep, sameRule, steps } from "@/features/items/repeat";
import { isDirectDebit, isIncomingMoney } from "@/lib/payments";
import { paysOnSite } from "@/features/document/item-meta";
import { CALL_NOTES, PROOF_DOCUMENTS, PROOF_DRAFTS, PROOF_ITEMS, PROOF_PARTIES, PROOFS } from "./data/proof";
import type { ReadingSeed } from "./data/traces";

const clone = <T>(v: T): T => (typeof structuredClone === "function" ? structuredClone(v) : JSON.parse(JSON.stringify(v)));

const rendered = new Map<string, RenderedLetter>();

/** Rendered page images + layout for a document (cached). */
export function letterFor(docId: string): RenderedLetter | null {
  if (rendered.has(docId)) return rendered.get(docId)!;
  const spec = LETTERS[docId] ?? FOLDER_LETTERS[docId];
  if (!spec) return null;
  const r = renderLetter(spec);
  rendered.set(docId, r);
  return r;
}

/** Fill page + boxes of evidence by locating the quote on the rendered letter. */
function resolveEvidence(e: Evidence): Evidence {
  const letter = letterFor(e.doc_id);
  if (!letter) return e;
  const hit = letter.locate(e.quote, e.page);
  if (!hit) return { ...e, grounding: e.grounding === "user" ? "user" : "unverified", boxes: [], score: 0.4 };
  return { ...e, page: hit.page, boxes: hit.boxes };
}

function resolveAll<T extends { evidence: Evidence[] }>(rows: T[]): T[] {
  return rows.map((r) => ({ ...r, evidence: r.evidence.map(resolveEvidence) }));
}

function resolveDoc(d: Document): Document {
  return { ...d, key_facts: d.key_facts.map((f) => (f.evidence ? { ...f, evidence: resolveEvidence(f.evidence) } : f)) };
}

const daysFrom = (a: string, b: string) => differenceInCalendarDays(parseISO(a), parseISO(b));
/**
 * A real renewal decision, as the API's `is_decision` (`src/ordnung/secretary/triggers.py`): a cancellation
 * deadline guarding a term that would otherwise continue. A contract you can end any month (the
 * Deutschlandticket, a job its contract lets you leave earlier) has no next renewal, so it is none.
 */
const isDecision = (k: ContractComputation | null) => Boolean(k?.cancel_by && k.send_by && k.next_renewal);
/** The day a recent letter is listed under: when it arrived, else its date, else when it was added. */
const recentDay = (d: Document) => d.received_date ?? d.doc_date ?? d.created_at.slice(0, 10);
const iso = (d: Date) => format(d, "yyyy-MM-dd");
/**
 * The mock's clock day: records are stamped on the demo's today with the real time of day, as the demo
 * server stamps them (`ordnung.clock.stamp_simulated_day`) — never the real date, which drifts further into
 * the demo's future every day (walkthrough of phase 2: "Read by Claude on 29 Sep 2026" in a demo of 28 Sep).
 * The newest mock world sets it.
 */
let clockDay: () => string | null = () => null;
const nowTs = () => {
  const real = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const day = clockDay();
  return day ? `${day}${real.slice(10)}` : real;
};

/** The fields of a to-do the person may change (`PATCH /api/items/{id}`). */
const ITEM_PATCHABLE = ["title", "description", "due_date", "due_time", "amount", "status", "snoozed_until", "priority", "area", "location", "recurrence"] as const;

/** The `keys` a request body sends, and only those. */
function pick<T extends object>(src: unknown, keys: readonly string[]): Partial<T> {
  const out: Record<string, unknown> = {};
  if (src && typeof src === "object") for (const k of keys) if (k in src) out[k] = (src as Record<string, unknown>)[k];
  return out as Partial<T>;
}

/**
 * Germany's nationwide public holidays the mock's own dates can meet: the API counts the working days of a date added
 * without a letter by these (`ingest.plan.own_context`). The mock has no Land and no rent's Monday-to-Friday.
 */
const NATIONWIDE_HOLIDAYS = new Set([
  "2026-10-03",
  "2026-12-25",
  "2026-12-26",
  "2027-01-01",
  "2027-03-26",
  "2027-03-29",
  "2027-05-01",
  "2027-05-06",
  "2027-05-17",
  "2027-10-03",
  "2027-12-25",
  "2027-12-26",
  "2028-01-01",
]);
const isHoliday = (d: Date) => NATIONWIDE_HOLIDAYS.has(iso(d));

/** `start`'s month `months` later, on `start`'s day (a 31st is a shorter month's last day: 31 Jan → 28 Feb → 31 Mar). */
function monthsOn(start: Date, months: number, day = start.getDate()): Date {
  const first = new Date(start.getFullYear(), start.getMonth() + months, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return new Date(first.getFullYear(), first.getMonth(), Math.min(day, last));
}

/**
 * The `n`th working day (Monday to Saturday, no public holiday) of `month`'s month; -1: its last Monday to Friday that
 * is no public holiday, 24 or 31 December (`ordnung.recurrence`, point 8).
 */
function workingDayOf(month: Date, n: number): Date {
  if (n === -1) {
    let d = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    const closed = (x: Date) => x.getDay() === 0 || x.getDay() === 6 || isHoliday(x) || (x.getMonth() === 11 && (x.getDate() === 24 || x.getDate() === 31));
    while (closed(d)) d = addDays(d, -1);
    return d;
  }
  let d = new Date(month.getFullYear(), month.getMonth(), 1);
  for (let left = n; ; d = addDays(d, 1)) {
    if (d.getDay() !== 0 && !isHoliday(d) && --left === 0) return d;
  }
}

/**
 * The first occurrence of a schedule that starts at `start` with `rule` that is on or after `notBefore` and after
 * `after` (the occurrence marked done): a working day in each of its months from `start`'s month, else a day of the
 * month on or after `start`, else `start`'s day stepped by the rule (points 2, 3, 4, 8 and 10 of `ordnung.recurrence`).
 */
function occurrenceOf(rule: Recurrence, start: string, notBefore: string, after: string | null = null): string {
  const first = parseISO(start);
  const days = dayStep(rule);
  const { months, workingDay, day } = steps(rule);
  for (let k = 0; k < 1200; k++) {
    let at: Date;
    if (days !== null) at = addDays(first, k * days);
    else if (workingDay !== null) at = workingDayOf(monthsOn(first, k * months!, 1), workingDay);
    else if (day !== null) at = monthsOn(first, k * months!, day);
    else at = monthsOn(first, k * months!);
    const date = iso(at);
    if (date >= notBefore && (after === null || date > after) && (day === null || date >= start)) return date;
  }
  return start;
}

/** A rule as sent (`ItemCreate.recurrence`, its defaults left out) as the API stores it; `null`: none. */
function asRule(rule: unknown): Recurrence | null {
  if (!rule || typeof rule !== "object") return null;
  const r = rule as Partial<Recurrence>;
  return { interval: r.interval ?? 1, unit: r.unit ?? "months", working_day: r.working_day ?? null, day_of_month: r.day_of_month ?? null };
}

/** What `DateSpec.nature` a to-do added by hand has (the API's `date_nature`). */
const natureOf = (kind: Item["kind"]): DateSpec["nature"] => (kind === "payment" ? "payment" : kind === "appointment" ? "appointment" : "other");

export interface MockState {
  health: Health;
  profile: Profile;
  settings: AppSettings;
  parties: Party[];
  cases: Case[];
  documents: Document[];
  items: Item[];
  contracts: Contract[];
  suggestions: Suggestion[];
  drafts: Draft[];
  activity: Activity[];
  chat: ChatMessage[];
  tray: MailTrayItem[];
  tour: TourState;
  lastCalendarExport: string;
  /** documents uploaded in this session (for page images of unknown files) */
  uploads: Record<string, { name: string; objectUrl?: string }>;
  /** the last files the watched folder brought in, newest first */
  folderRecent: FolderPickup[];
  /** proofs of sent letters (their files are documents with `source: "proof"`) */
  proofs: Proof[];
  /** call notes (Gesprächsnotizen) */
  calls: CallNote[];
  /** readings added in this session ("Read again"); others follow from the letter (`data/traces.ts`) */
  readings: Record<string, ReadingSeed[]>;
  /** when the newest encrypted backup was downloaded in this session (`null`: none yet), as `BackupInfo.last_copy` says */
  lastBackupAt: string | null;
}

/**
 * What a to-do's day asks of the person on the timeline, as the API's `_item_subtitle` words it: money
 * sent by bank transfer "Transfer by …", a direct debit "Collected by direct debit" (the sender takes
 * it: nothing to send), anything posted "Send by …"; a fee paid on site has no day to transfer by.
 */
function timelineSubtitle(i: Item): string | null {
  const payment = i.kind === "payment" && i.direction !== "in";
  if (payment && isDirectDebit(i)) return "Collected by direct debit";
  if (!i.send_by || paysOnSite(i)) return null;
  return `${payment ? "Transfer" : "Send"} by ${format(parseISO(i.send_by), "EEE d MMM")}`;
}

export class MockDb {
  state: MockState;
  /** The date each of the person's own repeating dates stood at when last marked done, for its "Undo". */
  private marked = new Map<string, string>();

  constructor() {
    clockDay = () => this.today;
    this.state = {
      health: clone(HEALTH),
      profile: clone(PROFILE),
      settings: clone(SETTINGS),
      parties: clone([...PARTIES.filter((p) => !TRAY_ONLY_PARTIES.has(p.id)), ...PROOF_PARTIES]),
      cases: clone(CASES),
      documents: clone([...DOCUMENTS, ...FOLDER_DOCUMENTS, ...PROOF_DOCUMENTS]).map(resolveDoc),
      items: resolveAll(clone([...ITEMS, ...PROOF_ITEMS])),
      contracts: resolveAll(clone(CONTRACTS)),
      suggestions: clone(SUGGESTIONS),
      drafts: clone([...DRAFTS, ...PROOF_DRAFTS]),
      activity: clone(ACTIVITY),
      chat: [],
      tray: clone(MAIL_TRAY),
      tour: clone(TOUR),
      lastCalendarExport: "2026-09-20T16:00:00Z",
      uploads: {},
      folderRecent: clone(FOLDER_RECENT),
      proofs: clone(PROOFS),
      calls: clone(CALL_NOTES),
      readings: {},
      lastBackupAt: null,
    };
  }

  get today(): string {
    return this.state.health.today ?? TODAY;
  }

  // ---------------------------------------------------------------------------------------------
  // lookups
  // ---------------------------------------------------------------------------------------------

  party(id: string | null | undefined): Party | null {
    return this.state.parties.find((p) => p.id === id) ?? null;
  }
  document(id: string): Document | null {
    return this.state.documents.find((d) => d.id === id && !d.deleted_at) ?? null;
  }
  /** Letters (trash and proof files left out: a proof belongs to its letter, like in the API). */
  liveDocuments(): Document[] {
    return this.state.documents.filter((d) => !d.deleted_at && d.source !== "proof");
  }

  /** The kind a demo letter was filed as when it was read (its seed), or `null` for an upload. */
  seedKind(docId: string): Document["kind"] | null {
    return (TRAY_DOCUMENTS[docId] ?? DOCUMENTS.find((d) => d.id === docId))?.kind ?? null;
  }

  /**
   * The person chose a letter's kind: the deadlines the law added to the kind it was read as leave with
   * it (open, unedited ones — as the real app files them), and come back when it is filed as that kind
   * again. The demo can't work out the deadlines of a kind it wasn't read as.
   */
  refileRuleItems(d: Document) {
    const seeded = [...(TRAY_ITEMS[d.id] ?? []), ...ITEMS.filter((i) => i.doc_id === d.id)].filter((i) => i.origin === "rule");
    if (d.kind === this.seedKind(d.id)) {
      const now = nowTs();
      for (const it of resolveAll(clone(seeded))) {
        if (!this.state.items.some((x) => x.id === it.id)) this.state.items.push({ ...it, created_at: now, updated_at: now });
      }
      return;
    }
    this.state.items = this.state.items.filter((i) => !(i.doc_id === d.id && i.origin === "rule" && i.status === "open" && !i.user_modified));
  }

  /** Apply the processed result of a New-mail tray letter (docs, items, ideas, parties). */
  applyTrayDocument(docId: string): Document | null {
    const full = TRAY_DOCUMENTS[docId];
    if (!full) return null;
    if (full.party_id && !this.party(full.party_id)) {
      const p = PARTIES.find((x) => x.id === full.party_id);
      if (p) this.state.parties.push(clone(p));
    }
    for (const c of TRAY_CASES) if (c.id === full.case_id && !this.state.cases.some((x) => x.id === c.id)) this.state.cases.push(clone(c));
    const now = nowTs();
    const processed = resolveDoc({ ...clone(full), created_at: now, updated_at: now, processed_at: now, ai_processed_at: now });
    this.upsertDocument(processed);
    for (const it of resolveAll(clone(TRAY_ITEMS[docId] ?? []))) {
      if (!this.state.items.some((x) => x.id === it.id)) this.state.items.push({ ...it, created_at: now, updated_at: now });
    }
    for (const s of clone(TRAY_SUGGESTIONS[docId] ?? [])) {
      if (!this.state.suggestions.some((x) => x.id === s.id)) this.state.suggestions.unshift({ ...s, created_at: now, updated_at: now });
    }
    if (docId === "doc_power_price") {
      const c = this.state.contracts.find((x) => x.id === "ctr_power");
      if (c?.computed) {
        c.computed = {
          ...c.computed,
          cancel_by: "2026-10-31",
          send_by: "2026-10-27",
          safe_date: "2026-10-30",
          warnings: ["Price increase from 1 Nov: €55.00/month (+€84/year). Special right to cancel until 31 Oct."],
        };
        c.updated_at = now;
      }
    }
    this.log("document.processed", `Read “${processed.title}” (${processed.pages} ${processed.pages === 1 ? "page" : "pages"})`, "document", docId);
    return processed;
  }

  upsertDocument(d: Document) {
    const i = this.state.documents.findIndex((x) => x.id === d.id);
    if (i >= 0) this.state.documents[i] = d;
    else this.state.documents.unshift(d);
  }

  /**
   * A to-do or date the person adds by hand ("Add a date"), as `POST /api/items` files it (`api/routes/items.py`):
   * theirs (`origin: "manual"`, confirmed by them), its date set by them, its links checked, a payment one they
   * make, in euros unless said — on a letter kept private or never read too. A refusal says why (the API's 404/422).
   */
  addItem(id: string, body: ItemCreate): { item: Item } | { status: number; message: string } {
    const title = body.title?.trim();
    if (!title || !body.kind) return { status: 422, message: "A to-do needs a title and a kind." };
    if (body.party_id && !this.party(body.party_id)) return { status: 404, message: "Unknown person or organisation." };
    if (body.case_id && !this.state.cases.some((c) => c.id === body.case_id)) return { status: 404, message: "Unknown thread." };
    if (body.contract_id && !this.state.contracts.some((c) => c.id === body.contract_id)) return { status: 404, message: "Unknown contract." };
    if (body.doc_id && !this.document(body.doc_id)) return { status: 404, message: "Unknown letter." };
    const now = nowTs();
    const amount = body.amount ?? null;
    const recurrence = asRule(body.recurrence);
    const item = makeItem({
      id,
      kind: body.kind,
      title,
      description: body.description ?? null,
      // a repeating date is placed by its rule at once, from the date given (where its schedule starts)
      due_date: body.due_date && recurrence ? occurrenceOf(recurrence, body.due_date, this.today) : (body.due_date ?? null),
      date_spec: body.due_date && recurrence ? spec({ date: body.due_date, nature: natureOf(body.kind) }) : null,
      due_time: body.due_time ?? null,
      amount,
      currency: amount !== null ? (body.currency ?? "EUR") : null,
      direction: body.kind === "payment" ? (body.direction ?? "out") : (body.direction ?? null),
      recurrence,
      priority: body.priority ?? "normal",
      area: body.area ?? "other",
      party_id: body.party_id ?? null,
      case_id: body.case_id ?? null,
      contract_id: body.contract_id ?? null,
      doc_id: body.doc_id ?? null,
      location: body.location ?? null,
      grounding: "user",
      origin: "manual",
      slot_key: null,
      due_date_source: body.due_date ? "manual" : "none",
      filed_on: this.today,
      created_at: now,
      updated_at: now,
    });
    this.state.items.push(item);
    return { item };
  }

  /**
   * The person edits a to-do (`PATCH /api/items/{id}`): only the fields they may change, and it is theirs from then on
   * (`user_modified`); a date they give is theirs too, and done or open again stamps or clears when it was done.
   * `null`: no such to-do (the API's 404).
   *
   * A repeating date of the person's own follows its schedule as the API's does: marked done it moves on to its next
   * date and stays open, and set open again ("Undo") it goes back; a new rule, or its rule sent with a date, starts the
   * schedule again there. (A repeating to-do read from a letter still closes when marked done: the mock has no engine
   * to move it.)
   */
  patchItem(id: string, body: unknown): Item | null {
    const it = this.state.items.find((i) => i.id === id);
    if (!it) return null;
    const patch = pick<Item>(body, ITEM_PATCHABLE);
    const before = { status: it.status, due_date: it.due_date, recurrence: it.recurrence };
    if ("recurrence" in patch) patch.recurrence = asRule(patch.recurrence);
    const own = it.origin === "manual";
    const restart = own && patch.recurrence != null && ("due_date" in patch || !sameRule(patch.recurrence, before.recurrence));
    Object.assign(it, patch, { updated_at: nowTs(), user_modified: true });
    if (patch.due_date) it.due_date_source = "manual";
    if (patch.status === "done") it.completed_at = nowTs();
    if (patch.status === "open") it.completed_at = null;
    if (restart && it.due_date) {
      it.date_spec = spec({ date: it.due_date, nature: natureOf(it.kind) });
      it.due_date = occurrenceOf(it.recurrence!, it.due_date, this.today);
    }
    const rule = it.recurrence;
    const start = it.date_spec?.date ?? it.due_date;
    if (own && rule && start && it.due_date && patch.status === "done" && before.status !== "done") {
      this.marked.set(id, it.due_date);
      Object.assign(it, { status: "open", completed_at: null, due_date: occurrenceOf(rule, start, this.today, it.due_date) });
    } else if (own && patch.status === "open" && before.status === "open" && this.marked.has(id)) {
      it.due_date = this.marked.get(id)!;
      this.marked.delete(id);
    }
    return it;
  }

  log(kind: string, message: string, ref_type: string | null = null, ref_id: string | null = null, data: Record<string, unknown> = {}) {
    const id = Math.max(0, ...this.state.activity.map((a) => a.id)) + 1;
    this.state.activity.unshift({ id, ts: nowTs(), kind, message, ref_type, ref_id, data });
  }

  trayDocFor(mailId: string): string | undefined {
    return TRAY_DOC[mailId];
  }

  // ---------------------------------------------------------------------------------------------
  // views
  // ---------------------------------------------------------------------------------------------

  /** Effective date for sorting: send-by first, else due date. */
  private eff(i: Item): string | null {
    return i.send_by ?? i.due_date;
  }

  openItems(): Item[] {
    const today = this.today;
    return this.state.items.filter(
      (i) => i.status === "open" || (i.status === "snoozed" && (!i.snoozed_until || i.snoozed_until <= today)),
    );
  }

  dashboard(): Dashboard {
    const today = this.today;
    const open = this.openItems().filter((i) => this.eff(i));
    const needsReviewDocs = new Set(this.liveDocuments().filter((d) => d.status === "needs_review").map((d) => d.id));
    const score = (i: Item) => {
      const days = daysFrom(this.eff(i)!, today);
      const pr = { low: 0, normal: 1, high: 2, critical: 3 }[i.priority];
      return days - pr * 2 - (i.doc_id && needsReviewDocs.has(i.doc_id) ? 3 : 0);
    };
    const attention = open
      .filter((i) => {
        const days = daysFrom(this.eff(i)!, today);
        return days <= 7 || (i.priority !== "normal" && i.priority !== "low" && days <= 12);
      })
      .sort((a, b) => score(a) - score(b));
    const attentionIds = new Set(attention.map((i) => i.id));
    const upcoming = open
      .filter((i) => !attentionIds.has(i.id) && daysFrom(i.due_date ?? this.eff(i)!, today) <= 30)
      .sort((a, b) => (this.eff(a)! < this.eff(b)! ? -1 : 1));
    // like the API (`views._decisions`): real decisions whose send-by date is at most 60 days ahead, soonest
    // first — not one whose cancellation was marked as sent
    const decisions = this.state.contracts
      .filter(
        (c) =>
          c.status === "active" &&
          isDecision(c.computed) &&
          daysFrom(c.computed!.send_by!, today) >= 0 &&
          daysFrom(c.computed!.send_by!, today) <= 60 &&
          !this.cancellationSent(c.id),
      )
      .sort((a, b) => a.computed!.send_by!.localeCompare(b.computed!.send_by!) || a.id.localeCompare(b.id));
    const in30 = iso(addDays(parseISO(today), 30));
    const payments = open.filter((i) => i.kind === "payment" && i.direction !== "in" && i.due_date && i.due_date <= in30).sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1));
    const byCat: Record<string, number> = {};
    const otherCurrencies: Record<string, number> = {}; // like the API: fixed costs in euros, other currencies apart
    let fixed = 0;
    for (const c of this.state.contracts) {
      if (c.status !== "active" || c.cost_amount == null || !c.cost_interval || c.cost_interval === "once") continue;
      const m = Math.round(c.cost_amount * { monthly: 1, quarterly: 1 / 3, yearly: 1 / 12 }[c.cost_interval] * 100) / 100;
      const currency = (c.cost_currency || "EUR").toUpperCase();
      if (currency !== "EUR") {
        otherCurrencies[currency] = Math.round(((otherCurrencies[currency] ?? 0) + m) * 100) / 100;
        continue;
      }
      fixed += m;
      byCat[c.category] = Math.round(((byCat[c.category] ?? 0) + m) * 100) / 100;
    }
    const evidence = [...this.state.items.flatMap((i) => i.evidence), ...this.state.contracts.flatMap((c) => c.evidence)];
    const verified = evidence.filter((e) => e.grounding === "verified" || e.grounding === "user").length;
    return {
      today,
      greeting_name: this.state.profile.name.split(" ")[0] ?? "",
      simulated: Boolean(this.state.health.simulated_today),
      attention,
      upcoming,
      decisions,
      money: {
        due_this_month: Math.round(payments.reduce((s, i) => s + (i.amount ?? 0), 0) * 100) / 100,
        fixed_costs_monthly: Math.round(fixed * 100) / 100,
        fixed_costs_monthly_other_currencies: otherCurrencies,
        upcoming_payments: payments.slice(0, 6),
        by_category: byCat,
      },
      areas: this.areas(),
      suggestions: this.state.suggestions.filter((s) => s.status === "new").sort((a, b) => prio(b.priority) - prio(a.priority)),
      // like views.py: newest first by the day each letter is listed under (arrived, else dated, else added);
      // letters waiting from the watched folder are not filed yet — Today counts them apart
      recent_documents: [...this.liveDocuments()]
        .filter((d) => d.status !== "held")
        .sort((a, b) => recentDay(b).localeCompare(recentDay(a)) || b.id.localeCompare(a.id))
        .slice(0, 6),
      waiting: this.liveDocuments().filter((d) => d.status === "held").length,
      stats: {
        documents: this.liveDocuments().length,
        open_items: this.openItems().length,
        contracts: this.state.contracts.filter((c) => c.status === "active").length,
        parties: this.state.parties.length,
        verified_ratio: evidence.length ? Math.round((verified / evidence.length) * 100) / 100 : 0,
      },
    };
  }

  areas(): AreaStatus[] {
    const today = this.today;
    const labels: Partial<Record<Area, string>> = {
      residence: "Residence permit",
      home: "Home",
      money: "Money",
      study: "Study",
      work: "Work",
      health: "Health",
      mobility: "Getting around",
      insurance: "Insurance",
      tax: "Tax",
      leisure: "Leisure",
    };
    const out: AreaStatus[] = [];
    for (const area of Object.keys(labels) as Area[]) {
      // like views.py: a payment nobody sends by bank (a direct debit, money coming in, a fee paid on
      // site) by its due day; the app's one urgency scale — overdue, today and tomorrow urgent, the week
      // attention — where such a payment or an appointment never turns urgent (nothing to send)
      const noTransfer = (i: Item) => isDirectDebit(i) || isIncomingMoney(i) || paysOnSite(i);
      const day = (i: Item) => (noTransfer(i) ? i.due_date : this.eff(i))!;
      const capped = (i: Item) => i.kind === "appointment" || noTransfer(i);
      const items = this.openItems()
        .filter((i) => i.area === area && i.due_date)
        .sort((a, b) => (day(a) < day(b) ? -1 : 1));
      const hasData = items.length || this.liveDocuments().some((d) => d.area === area);
      if (!hasData) continue;
      const next = items[0];
      const rank = { ok: 0, attention: 1, urgent: 2 } as const;
      const levelOf = (i: Item): AreaStatus["status"] => {
        const days = daysFrom(day(i), today);
        if (days <= 1 && !capped(i)) return "urgent";
        return days <= 7 ? "attention" : "ok";
      };
      const status = items.map(levelOf).reduce<AreaStatus["status"]>((a, b) => (rank[b] > rank[a] ? b : a), "ok");
      out.push({
        area,
        label: labels[area]!,
        status,
        headline: next ? next.title : "Nothing coming up",
        next_date: next ? day(next) : null,
        count: items.length,
      });
    }
    return out;
  }

  /** The person's latest cancellation of a contract marked as sent, as the API's `cancellation_sent`. */
  cancellationSent(contractId: string): Contract["cancellation_sent"] {
    const draft = this.state.drafts
      .filter((d) => d.kind === "cancellation" && d.status === "sent" && d.contract_id === contractId)
      .sort((a, b) => (b.sent_at ?? "").localeCompare(a.sent_at ?? ""))[0];
    return draft ? { draft_id: draft.id, sent_on: draft.sent_at?.slice(0, 10) ?? null, channel: draft.sent_channel } : null;
  }

  /** A contract as the API sends it: with its sent cancellation worked out on read. */
  contractView(c: Contract): Contract {
    return { ...c, cancellation_sent: c.status === "active" ? this.cancellationSent(c.id) : null };
  }

  timeline(from?: string | null, to?: string | null): TimelineEntry[] {
    const today = this.today;
    const out: TimelineEntry[] = [];
    for (const i of this.state.items) {
      if (!i.due_date || i.status === "dismissed") continue;
      const p = this.party(i.party_id);
      out.push({
        id: `tl_${i.id}`,
        date: i.due_date,
        time: i.due_time,
        type: i.kind,
        title: i.title,
        subtitle: timelineSubtitle(i) ?? p?.name ?? null,
        status: i.status === "open" && i.due_date < today ? "missed" : i.status,
        priority: i.priority,
        area: i.area,
        ref: { type: "item", id: i.id },
        party_name: p?.name ?? null,
        amount: i.amount,
        currency: i.currency,
        past: i.due_date < today,
        direction: i.kind === "payment" ? i.direction : null,
        aside: null, // the route adds why a to-do is not one to act on (`setAside` in server.ts)
      });
    }
    for (const d of this.liveDocuments()) {
      const date = d.received_date ?? d.doc_date;
      if (!date) continue;
      const p = this.party(d.party_id);
      out.push({
        id: `tl_${d.id}`,
        date,
        time: null,
        type: "document",
        title: d.title ?? d.filename,
        subtitle: p ? `Letter from ${p.name}` : "Letter",
        status: d.status,
        priority: d.urgency ?? "normal",
        area: d.area ?? "other",
        ref: { type: "document", id: d.id },
        party_name: p?.name ?? null,
        amount: null,
        currency: null,
        past: date < today,
        direction: null,
        aside: null,
      });
    }
    for (const c of this.state.contracts) {
      const p = this.party(c.party_id);
      if (c.computed?.current_term_end && c.category !== "employment") {
        out.push({
          id: `tl_${c.id}_term`,
          date: c.computed.current_term_end,
          time: null,
          type: "contract",
          title: `${c.name}: current term ends`,
          subtitle: c.computed.cancel_by && c.computed.cancel_by > today ? `Cancel by ${format(parseISO(c.computed.cancel_by), "d MMM")}` : "Renews automatically",
          status: c.status,
          priority: "normal",
          area: c.area,
          ref: { type: "contract", id: c.id },
          party_name: p?.name ?? null,
          amount: c.cost_amount,
          currency: c.cost_currency,
          past: c.computed.current_term_end < today,
          direction: null,
          aside: null,
        });
      }
    }
    for (const d of this.state.drafts) {
      if (d.status !== "sent" || !d.sent_at) continue;
      const p = this.party(d.party_id);
      const date = d.sent_at.slice(0, 10);
      out.push({
        id: `tl_${d.id}`,
        date,
        time: null,
        type: "draft",
        title: `You sent: ${d.subject}`,
        subtitle: p?.name ?? null,
        status: "sent",
        priority: "normal",
        area: "other",
        ref: { type: "draft", id: d.id },
        party_name: p?.name ?? null,
        amount: null,
        currency: null,
        past: date < today,
        direction: null,
        aside: null,
      });
    }
    return out
      .filter((e) => (!from || e.date >= from) && (!to || e.date <= to))
      .sort((a, b) => (a.date === b.date ? (a.time ?? "") < (b.time ?? "") ? -1 : 1 : a.date < b.date ? -1 : 1));
  }

  lanes(from?: string | null, to?: string | null): Lane[] {
    const today = this.today;
    const has = (id: string) => this.state.items.some((i) => i.id === id);
    const statusFor = (end: string): LaneBar["status"] => {
      const d = daysFrom(end, today);
      if (d < 0) return "past";
      if (d <= 21) return "urgent";
      if (d <= 75) return "attention";
      return "ok";
    };
    const m = (date: string, label: string, kind: TimelineMarker["kind"]): TimelineMarker => ({ date, label, kind });
    const bar = (b: Omit<LaneBar, "status" | "markers" | "ref"> & Partial<LaneBar>): LaneBar => ({
      status: b.status ?? statusFor(b.end),
      markers: [],
      ref: null,
      ...b,
    });

    const lanes: Lane[] = [
      {
        id: "lane_residence",
        label: "Residence permit",
        area: "residence",
        bars: [
          bar({ id: "bar_permit", label: "Residence permit", start: "2024-12-01", end: "2026-11-30", kind: "validity", ref: { type: "document", id: "doc_abh" }, markers: [m("2026-10-14", "Appointment 10:30", "appointment"), m("2026-11-30", "Permit expires", "expiry")] }),
        ],
        markers: [],
      },
      {
        id: "lane_passport",
        label: "Passport",
        area: "residence",
        bars: [bar({ id: "bar_passport", label: "Passport valid", start: "2017-02-11", end: "2027-02-10", kind: "validity", ref: { type: "document", id: "doc_passport" }, markers: [m("2027-02-10", "Passport expires", "expiry")] })],
        markers: [],
      },
      {
        id: "lane_home",
        label: "Home",
        area: "home",
        bars: [bar({ id: "bar_lease", label: "Lease Beispielweg 5", start: "2025-10-01", end: "2027-12-31", kind: "contract", status: "ok", open_end: true, ref: { type: "contract", id: "ctr_rent" } })],
        markers: [m("2026-10-05", "Rent", "payment"), m("2026-10-09", "Utility back payment €184.30", "payment"), m("2026-11-15", "Broadcasting fee", "payment")],
      },
      {
        id: "lane_phone",
        label: "Phone · FunkNetz",
        area: "home",
        bars: [
          bar({ id: "bar_phone_term", label: "Minimum term", start: "2024-11-15", end: "2026-11-14", kind: "contract", ref: { type: "contract", id: "ctr_phone" }, markers: [m("2026-11-14", "Minimum term ends", "renewal")] }),
          bar({ id: "bar_phone_notice", label: "Time to cancel", start: "2026-08-15", end: "2026-10-14", kind: "notice_window", ref: { type: "contract", id: "ctr_phone" }, markers: [m("2026-10-08", "Send by", "send_by"), m("2026-10-14", "Cancel by", "cancel_by")] }),
          bar({ id: "bar_phone_after", label: "Month to month", start: "2026-11-15", end: "2027-12-31", kind: "contract", status: "ok", open_end: true, ref: { type: "contract", id: "ctr_phone" } }),
        ],
        markers: [],
      },
      {
        id: "lane_power",
        label: "Electricity · Stadtwerke",
        area: "home",
        bars: [
          bar({ id: "bar_power", label: "MusterStrom Natur", start: "2025-10-01", end: "2027-12-31", kind: "contract", status: "ok", open_end: true, ref: { type: "contract", id: "ctr_power" } }),
          ...(has("itm_power_cancel")
            ? [bar({ id: "bar_power_right", label: "Special right to cancel", start: "2026-09-28", end: "2026-10-31", kind: "notice_window", ref: { type: "document", id: "doc_power_price" }, markers: [m("2026-10-27", "Send by (post)", "send_by"), m("2026-10-31", "Cancel by", "cancel_by")] })]
            : []),
        ],
        markers: has("itm_power_new") ? [m("2026-11-01", "Price rises (+€84/year)", "other")] : [],
      },
      {
        id: "lane_insurance",
        label: "Liability insurance",
        area: "insurance",
        bars: [
          bar({ id: "bar_liab_2026", label: "Insurance year", start: "2025-12-01", end: "2026-11-30", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_liability" } }),
          bar({ id: "bar_liab_2027", label: "Insurance year (renewed)", start: "2026-12-01", end: "2027-11-30", kind: "contract", status: "ok", ref: { type: "contract", id: "ctr_liability" }, markers: [m("2026-12-01", "Renews · €59.90", "renewal")] }),
          bar({ id: "bar_liab_notice", label: "Time to cancel", start: "2027-06-01", end: "2027-08-31", kind: "notice_window", ref: { type: "contract", id: "ctr_liability" }, markers: [m("2027-08-25", "Send by", "send_by"), m("2027-08-31", "Cancel by", "cancel_by")] }),
        ],
        markers: [],
      },
      {
        id: "lane_study",
        label: "Study",
        area: "study",
        bars: [
          bar({ id: "bar_ws", label: "Winter semester 2026/27", start: "2026-10-01", end: "2027-03-31", kind: "period", status: "ok", ref: { type: "document", id: "doc_uni" } }),
          bar({ id: "bar_ss", label: "Summer semester 2027", start: "2027-04-01", end: "2027-09-30", kind: "period", status: "ok", ref: { type: "document", id: "doc_uni" } }),
        ],
        markers: [m("2026-12-15", "Scholarship report", "deadline"), m("2027-01-15", "Semester fee €312.40", "payment")],
      },
      {
        id: "lane_work",
        label: "Work · Muster Tech",
        area: "work",
        bars: [bar({ id: "bar_job", label: "Werkstudent contract", start: "2025-04-01", end: "2027-03-31", kind: "contract", ref: { type: "contract", id: "ctr_job" }, markers: [m("2027-03-31", "Contract ends", "expiry")] })],
        markers: [],
      },
      {
        id: "lane_money",
        label: "Money",
        area: "money",
        bars: [],
        markers: [m("2026-09-30", "TechMarkt €94.99", "payment"), m("2026-11-30", "Bank fee decision", "deadline"), m("2026-12-01", "Liability €59.90", "payment")],
      },
    ];
    if (has("itm_tax_objection")) {
      lanes.splice(2, 0, {
        id: "lane_tax",
        label: "Tax",
        area: "tax",
        bars: [bar({ id: "bar_tax_objection", label: "Objection period (Einspruch)", start: "2026-09-21", end: "2026-10-21", kind: "notice_window", ref: { type: "document", id: "doc_tax" }, markers: [m("2026-10-15", "Send by", "send_by"), m("2026-10-21", "Deadline", "deadline")] })],
        markers: [],
      });
    }
    // like the API: every bar and date says its life area and what it stands for (a date here
    // with no to-do behind it has no `ref`), and a bar with no end date says so
    const complete: Lane[] = lanes.map((l) => ({
      ...l,
      bars: l.bars.map((b) => {
        const area = b.area ?? l.area;
        return { ...b, area, open_end: b.open_end ?? false, markers: b.markers.map((mk) => ({ ...mk, area: mk.area ?? area, ref: mk.ref ?? b.ref })) };
      }),
      markers: l.markers.map((mk) => ({ ...mk, area: mk.area ?? l.area, ref: mk.ref ?? null })),
    }));
    if (!from && !to) return complete;
    const f = from ?? "0000-01-01";
    const t = to ?? "9999-12-31";
    // like the API: bars are clipped to the range (the chart then says "started before" /
    // "continues after" instead of showing an edge as a date), markers outside it are dropped
    const inRange = (mk: TimelineMarker) => mk.date >= f && mk.date <= t;
    return complete
      .map((l) => ({
        ...l,
        bars: l.bars
          .filter((b) => b.end >= f && b.start <= t)
          .map((b) => ({ ...b, start: b.start < f ? f : b.start, end: b.end > t ? t : b.end, markers: b.markers.filter(inRange) })),
        markers: l.markers.filter(inRange),
      }))
      .filter((l) => l.bars.length || l.markers.length);
  }

  search(q: string): Document[] {
    const needle = q.trim().toLowerCase();
    if (!needle) return this.liveDocuments();
    const words = needle.split(/\s+/);
    const scored = this.liveDocuments()
      .map((d) => {
        const party = this.party(d.party_id)?.name ?? "";
        const text = [d.title, d.summary, d.filename, party, d.kind?.replace(/_/g, " "), ...d.key_facts.map((f) => `${f.label} ${f.value}`), letterFor(d.id)?.pageText(1) ?? ""]
          .join(" ")
          .toLowerCase();
        const title = (d.title ?? "").toLowerCase();
        let score = 0;
        for (const w of words) {
          if (!text.includes(w)) return { d, score: 0 };
          score += title.includes(w) ? 3 : party.toLowerCase().includes(w) ? 2 : 1;
        }
        return { d, score };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score);
    return scored.map((x) => x.d);
  }

  /** Items dated after the last calendar export (drives the "N new dates" Idea). */
  newDatesSinceExport(): Item[] {
    return this.openItems().filter((i) => i.due_date && i.created_at > this.state.lastCalendarExport);
  }
}

function prio(p: string): number {
  return { low: 0, normal: 1, high: 2, critical: 3 }[p as "low"] ?? 1;
}

export { daysFrom, iso as isoDate, nowTs, pick };
