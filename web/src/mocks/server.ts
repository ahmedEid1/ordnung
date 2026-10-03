/**
 * Mock API: routes `/api/*` requests to handlers operating on the in-memory {@link MockDb}.
 * Mutations change the in-memory copy so the UI is fully interactive; long-running work
 * (uploads, New-mail letters) is simulated with realistic stage timings and SSE events.
 */
import { addDays, addMonths, endOfMonth, format, parseISO } from "date-fns";
import type {
  CalendarSyncConnect,
  CalendarSyncFind,
  AppSettings,
  Brief,
  CaseDetail,
  ChatMessage,
  CitationRef,
  Contract,
  ContractComputation,
  DataDeleted,
  DeleteResult,
  DesktopMode,
  DesktopTestResult,
  Document,
  DocumentDetail,
  Draft,
  Evidence,
  DraftCreate,
  FolderStatus,
  HeldResult,
  Health,
  Item,
  ItemAside,
  ItemCreate,
  Job,
  LetterAdvice,
  ListedItem,
  MailOpenResult,
  NoticeUnit,
  PageInfo,
  Profile,
  PartyDetail,
  ReviewStarted,
  StreamEvent,
  Suggestion,
  TimelineEntry,
  SuggestionRef,
  TemplateDraftKind,
  TransferValues,
  UploadResult,
} from "@/api/types";
import { HIGH_STAKES_KINDS, type HighStakesKind } from "@/api/types";
import { ibanLooksValid, normalizeIban } from "@/lib/format";
import { MockDb, letterFor, nowTs } from "./db";
import { emit } from "./events";
import { renderLetter, svgDataUrl, PAGE_H, PAGE_W } from "./pages";
import { icsDataUrl, itemsToIcs } from "./ics";
import { BRIEF_TEXT, DEMO_CHECKS, RULES, USAGE } from "./data/system";
import { FALLBACK_ANSWER, RECORDED, SUGGESTED_QUESTIONS } from "./data/ask";
import { draftChecks, phoneGuidance } from "./data/drafts";
import { ADVICE_ARRIVED_BY_KIND, ADVICE_BY_DOC, ADVICE_BY_KIND } from "./data/advice";
import { ORDER_RECEIPTS, STATUTORY_OBJECTIONS } from "./data/highStakes";
import { courtChannels, isCourtName, templateLetter, templateRefusal } from "./data/templateLetters";
import { mayBeCourt, needsTypedCourt } from "@/features/letters/logic";
import { ordinal } from "@/features/contracts/model";

/** Mirrors compose.COURT_OBJECTION_RECIPIENT. */
const COURT_OBJECTION_RECIPIENT =
  "An objection to a court order goes to the court that issued it — sent to the claimant, it doesn't stop the order (§ 694, § 700 ZPO). This letter's sender isn't a court in Ordnung: type the court's name and address as the order and its yellow envelope show them (for a Mahnbescheid usually a central Mahngericht).";
import { SAM, sha } from "./data/constants";
import { mockNumbers, mockWeek, mockWeekDismiss, mockWeekDone } from "./numbers";
import { TRAY_DOCUMENTS } from "./data/documents";
import { EMAIL_ATTACHMENTS, SUGGESTED_INBOX } from "./data/folder";
import {
  BACKUP_STATIC_MESSAGE,
  DESKTOP_STATIC_MESSAGE,
  SAMPLE_NOTIFICATION,
  mockBackupFile,
  mockBackupInfo,
  mockDesktopReminders,
  mockNotification,
} from "./data/reminders";
import { TRAY_ITEMS } from "./data/items";
import {
  CalendarSyncRefusal,
  mockCalendarPreview,
  mockCalendarSyncStatus,
  mockForgetCalendar,
  mockConnectCalendar,
  mockDisconnectCalendar,
  mockDiscoverCalendars,
  mockRunCalendarSync,
} from "./data/calendarSync";
import { PARTIES } from "./data/parties";
import { doc as makeDoc, item as makeItem } from "./data/helpers";
import { isOpenItem } from "@/features/document/verdict";
import { compareBase } from "@/features/document/trace/copy";
import { NOTICE_BASIS_COPY, documentKindLabel } from "@/lib/copy";
import { DEMO_NOTE } from "./mode";
import { confirmMockGiroCode, mockGiroCode } from "./girocode";
import { checkTracking } from "@/lib/tracking";
import { deliveredBefore, proofRoutes, resolveProofAsset, sentFollowup } from "./proof";
import { addReading, compareReadings, defaultReadings, documentTrace, exportTraces, type TraceLedger } from "./data/traces";

const isHighStakes = (kind: Document["kind"]): kind is HighStakesKind => (HIGH_STAKES_KINDS as readonly (string | null)[]).includes(kind);

export interface MockOptions {
  /** Zero-install hosted demo: actions that need Claude are refused with a friendly message. */
  staticDemo: boolean;
  /** Artificial latency multiplier (0 in tests). */
  latency?: number;
}

interface Ctx {
  db: MockDb;
  params: Record<string, string>;
  query: URLSearchParams;
  body: unknown;
  signal?: AbortSignal | null;
  opts: MockOptions;
}

/** Explicit status + body (default: 200 with the returned value as JSON). */
class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown = null,
  ) {}
}
type Handler = (ctx: Ctx) => unknown | Promise<unknown>;

const sleep = (ms: number, signal?: AbortSignal | null) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });

let seq = 0;
const newId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(++seq).toString(36).padStart(3, "0")}`;

class HttpError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** A calendar-sync refusal as the API answers it (`code` names the field). */
function calendarRefusals<T>(work: () => T): T {
  try {
    return work();
  } catch (err) {
    if (err instanceof CalendarSyncRefusal) throw new HttpError(err.status, err.message, err.code);
    throw err;
  }
}

const DEMO_TRANSLATE_MESSAGE =
  "The demo replays recorded answers, so it can't translate your changes. Run “ordnung serve” (with Claude Code signed in) to re-translate letters you edited.";
const DEMO_DELETE_MESSAGE = "This is the demo, so there is nothing of yours to delete. To start over with Sam's original letters, run “ordnung demo --reset”.";
const STATIC_MESSAGE = "Install Ordnung to try this with your own letters — the online demo only replays recorded examples.";

function needsClaude(ctx: Ctx) {
  if (ctx.opts.staticDemo) throw new HttpError(403, STATIC_MESSAGE, "static_demo");
}

function notFound(what = "Not found"): never {
  throw new HttpError(404, what);
}

// ------------------------------------------------------------------------------------------------
// Job simulation
// ------------------------------------------------------------------------------------------------

const STAGES_TEXT = ["intake", "text", "extract", "verify", "compute", "link", "plan"] as const;
const STAGES_PHOTO = ["intake", "transcribe", "extract", "verify", "compute", "link", "plan"] as const;
const STAGE_MS: Record<string, number> = { intake: 650, text: 700, transcribe: 1500, extract: 1700, verify: 900, compute: 800, link: 600, plan: 600 };

function makeJob(docId: string, kind: Job["kind"] = "ingest"): Job {
  const now = nowTs();
  return {
    id: newId("job"),
    kind,
    status: "running",
    stage: "intake",
    progress: 0,
    doc_id: docId,
    attempts: 1,
    force: kind === "reprocess",
    not_before: null,
    waiting_reason: null,
    error: null,
    created_at: now,
    updated_at: now,
  };
}

const activeJobs = new Map<string, Job>();

async function runJob(db: MockDb, job: Job, photo: boolean, finish: () => void, speed = 1) {
  activeJobs.set(job.id, job);
  const stages = photo ? STAGES_PHOTO : STAGES_TEXT;
  for (let i = 0; i < stages.length; i++) {
    const stage = stages[i]!;
    job.stage = stage;
    job.progress = i / stages.length;
    job.updated_at = nowTs();
    emit("job.progress", { job_id: job.id, doc_id: job.doc_id, stage, progress: job.progress, status: "running" });
    await sleep(STAGE_MS[stage]! * speed);
  }
  finish();
  job.stage = "done";
  job.status = "done";
  job.progress = 1;
  job.updated_at = nowTs();
  emit("job.progress", { job_id: job.id, doc_id: job.doc_id, stage: "done", progress: 1, status: "done" });
  if (job.doc_id) emit("document.processed", { doc_id: job.doc_id, status: db.document(job.doc_id)?.status ?? "processed" });
  emit("suggestions.updated", {});
  emit("item.updated", {});
  activeJobs.delete(job.id);
}

// ------------------------------------------------------------------------------------------------
// Views
// ------------------------------------------------------------------------------------------------

function pageInfos(db: MockDb, d: Document): PageInfo[] {
  const letter = letterFor(d.id);
  const n = letter ? letter.pages.length : d.pages;
  return Array.from({ length: n }, (_, i) => ({
    page: i + 1,
    width: PAGE_W,
    height: PAGE_H,
    text_source: d.text_mode === "vision" ? "transcript" : letter || db.state.uploads[d.id] ? "text" : "none",
  }));
}

/**
 * Whether the person has dealt with a high-stakes letter, as the server decides it (`advice.settles`): every
 * to-do that carries its legal deadline — one the law added, or one whose receipt cites a rule of the card —
 * is closed, and there is one. Another to-do of the letter (the arrears, a handover appointment) never counts,
 * nor a recurring one (it moves on when done) or a rent increase's new rent (the consent decision carries it).
 */
function settles(card: LetterAdvice, items: Item[]): boolean {
  const carries = (i: Item) =>
    !i.recurrence &&
    !(card.kind === "rent_increase" && i.kind === "payment") &&
    (i.origin === "rule" || Boolean(i.computation?.rule_ids.some((r) => card.rule_ids.includes(r))));
  const carrying = items.filter(carries);
  return carrying.length > 0 && !carrying.some(isOpenItem);
}

/** The tag a letter carries once the person said they dealt with a card no to-do can close (`DEALT_WITH_TAG`). */
const DEALT_WITH_TAG = "dealt-with";

/** The steps that ask for the delivery (or receipt) day, which a handled card leaves out (`advice._unless`). */
const ASKS_FOR_DELIVERY = /^(Find the delivery date|Enter the day the dismissal reached you|The period counts from the delivery date|The three weeks count from the day you received)/;

/**
 * The letter's "get advice" card as the real app works it out on read: a card from the letter itself
 * only while it is filed as it was read, else its kind's — without asking again for an arrival day
 * the person entered.
 */
function adviceFor(db: MockDb, d: Document): LetterAdvice | null {
  const own = ADVICE_BY_DOC[d.id];
  // a card recognised on read (an operating-cost statement filed as a utility bill) goes once the person chose
  // another kind for the letter — also the kind it is stored as (review round 2: "Utility bill" kept the card)
  const chosen = db.state.activity.some((a) => a.kind === "document.kind" && a.ref_id === d.id);
  const ownStands = own && d.kind === db.seedKind(d.id) && !(chosen && own.kind !== d.kind);
  const card = ownStands ? own : isHighStakes(d.kind) ? (d.received_date ? ADVICE_ARRIVED_BY_KIND : ADVICE_BY_KIND)[d.kind] : null;
  // as on the server: once the person dealt with the letter, its card is no longer urgent and says so (the
  // demo's landlord cards are ordinary notices with an objection to-do, which can settle); a card no to-do
  // can close once the person marked it dealt with
  const dealt = card?.closable ? d.tags.includes(DEALT_WITH_TAG) : card ? settles(card, db.state.items.filter((i) => i.doc_id === d.id)) : false;
  if (!card || !dealt) return card;
  const steps = card.kind === "operating_costs" ? card.steps : card.steps.filter((s) => !ASKS_FOR_DELIVERY.test(s));
  // as `advice.HANDLED_TITLE`: the title names the letter, not the deadline it no longer urges
  return { ...card, urgent: false, handled: true, steps, title: `${card.title.split(" — ")[0]} — you've dealt with it` };
}

const traceLedger = (db: MockDb): TraceLedger => ({
  documents: db.state.documents,
  items: db.state.items,
  parties: db.state.parties,
  cases: db.state.cases,
  contracts: db.state.contracts,
});
const readingsOf = (db: MockDb, d: Document) => db.state.readings[d.id] ?? defaultReadings(d);
const READING_GONE = "That reading of the letter isn't kept any more — Ordnung keeps the last five.";
const NOTHING_TO_COMPARE = "There is nothing to compare yet: this letter has been read only once.";

function documentDetail(db: MockDb, id: string): DocumentDetail {
  const d = db.document(id) ?? notFound("This letter doesn't exist (anymore).");
  const items = db.state.items.filter((i) => i.doc_id === id);
  const itemIds = new Set(items.map((i) => i.id));
  const contracts = db.state.contracts.filter((c) => c.source_doc_id === id || c.evidence.some((e) => e.doc_id === id));
  const related = d.case_id ? db.liveDocuments().filter((x) => x.case_id === d.case_id && x.id !== id) : [];
  const suggestions = db.state.suggestions.filter(
    (s) => s.status !== "expired" && s.refs.some((r) => (r.type === "document" && r.id === id) || (r.type === "item" && itemIds.has(r.id))),
  );
  return {
    document: d,
    advice: adviceFor(db, d),
    pages: pageInfos(db, d),
    items,
    contracts,
    party: db.party(d.party_id),
    case: db.state.cases.find((c) => c.id === d.case_id) ?? null,
    related: related.sort((a, b) => ((a.doc_date ?? "") < (b.doc_date ?? "") ? 1 : -1)),
    suggestions,
    drafts: db.state.drafts.filter((x) => x.doc_id === id),
    set_aside: setAside(db, items),
    girocodes: items.filter((i) => i.kind === "payment").map((i) => mockGiroCode(db, i)),
    // like the API: an attachment's letter is linked (with its status now) while it exists; an attachment names its e-mail
    attachments: (EMAIL_ATTACHMENTS[id] ?? []).map((a) => {
      const linked = a.doc_id ? db.document(a.doc_id) : null;
      return { ...a, doc_id: linked ? linked.id : null, status: linked ? linked.status : null };
    }),
    attachments_more: 0,
    email: d.source.startsWith("email:") ? db.document(d.source.slice("email:".length)) : null,
    can_wait_again: wasKeptFromWaiting(db, d),
    // the Idea's list, as the API gives it; the page falls back to the letter's warnings (none are given here)
    scam_signs: [],
    proof_of: db.state.proofs
      .filter((p) => p.doc_id === id)
      .flatMap((p) => {
        const letter = db.state.drafts.find((x) => x.id === p.draft_id);
        return letter ? [{ draft_id: letter.id, subject: letter.subject, proof_id: p.id, kind: p.kind }] : [];
      }),
  };
}

// ------------------------------------------------------------------------------------------------
// The watched folder
// ------------------------------------------------------------------------------------------------

/** Like `inbox_dir_problem`: a full path, not a drive's root, not the home folder. */
function inboxDirProblem(value: string): string | null {
  const v = value.trim();
  if (!(v.startsWith("/") || v.startsWith("~") || /^[A-Za-z]:[\\/]/.test(v))) return "Please choose a full folder path (for example /home/you/Scans).";
  if (/^(\/|[A-Za-z]:[\\/]?)$/.test(v)) return "The inbox can't be the root of a drive.";
  if (/^(~|\/home\/[^/]+|\/Users\/[^/]+)\/?$/.test(v)) return "The inbox can't be your whole home folder — choose a dedicated folder.";
  return null;
}

/** Like the API: a model id or alias as Claude Code takes it — no whitespace, not starting with a dash (it follows `--model` on argv). */
function modelProblem(value: string): string | null {
  if (!value) return "Enter a model id or alias, like claude-sonnet-5 or sonnet.";
  if (!/^[^\s-]\S*$/.test(value)) return "A model name has no spaces and doesn't start with a dash — like claude-sonnet-5 or sonnet[1m].";
  return null;
}

function folderStatus(db: MockDb, canRead: boolean): FolderStatus {
  const s = db.state.settings;
  return {
    folder: s.inbox_dir,
    state: s.inbox_dir ? "watching" : "off",
    problem: null,
    auto_read: s.inbox_auto_read,
    // the static demo reads nothing with Claude: files always wait (like the replay-only demo)
    can_read: canRead,
    waiting: db.liveDocuments().filter((d) => d.status === "held").length,
    suggested: SUGGESTED_INBOX,
    recent: db.state.folderRecent.map((p) => {
      const d = p.doc_id ? db.document(p.doc_id) : null;
      return { ...p, doc_id: d ? d.id : null, status: d ? d.status : null };
    }),
  };
}

/** The held letters among `ids`, a held e-mail's held attachments after it; the rest are skipped. */
function answeredTogether(db: MockDb, ids: string[]): { docs: Document[]; skipped: string[] } {
  const docs = new Map<string, Document>();
  const skipped: string[] = [];
  for (const id of new Set(ids)) {
    const d = db.document(id);
    if (!d || d.status !== "held") {
      skipped.push(id);
      continue;
    }
    docs.set(d.id, d);
    for (const a of db.liveDocuments()) if (a.status === "held" && a.source === `email:${d.id}`) docs.set(a.id, a);
  }
  return { docs: [...docs.values()], skipped };
}

/** Like `held.was_kept_from_waiting`: kept private by answering its wait, and not read since. */
function wasKeptFromWaiting(db: MockDb, d: Document): boolean {
  if (d.deleted_at || !d.ai_private || d.ai_processed_at || d.status !== "processed") return false;
  const answer = db.state.activity.find((e) => e.ref_id === d.id && ["document.kept_private", "document.released", "document.waiting"].includes(e.kind));
  return answer?.kind === "document.kept_private";
}

function heldIds(body: unknown): string[] {
  const ids = (body as { doc_ids?: unknown } | null)?.doc_ids;
  if (!Array.isArray(ids) || !ids.length || ids.some((x) => typeof x !== "string")) throw new HttpError(422, "Choose which letters you mean.");
  return ids as string[];
}

/**
 * Open items that are not one to act on (the server's `ledger` rules, simplified): an invoice
 * payment a later payment reminder of the same thread took over, or a date that was already more
 * than 14 days past when the letter was filed.
 */
function setAside(db: MockDb, items: Item[]): ItemAside[] {
  const docs = db.liveDocuments();
  const byId = new Map(docs.map((d) => [d.id, d]));
  const reminders = docs.filter((d) => d.kind === "dunning" && d.direction === "incoming" && d.case_id);
  const dayMs = 86_400_000;
  return items.flatMap((i): ItemAside[] => {
    if (i.status !== "open") return [];
    const doc = i.doc_id ? byId.get(i.doc_id) : undefined;
    // like the server's scam signs (the demo's scam letter is the one hiding text)
    if (doc?.hidden_text) return [{ item_id: i.id, reason: "suspicious", replaced_by: null }];
    if (i.kind === "payment" && !i.recurrence && doc) {
      const covering = reminders.find(
        (r) => r.id !== doc.id && r.case_id === doc.case_id && (doc.kind === "dunning" ? (doc.doc_date ?? "") < (r.doc_date ?? "") : !(doc.doc_date && r.doc_date && doc.doc_date > r.doc_date)),
      );
      if (covering) return [{ item_id: i.id, reason: "replaced", replaced_by: covering.id }];
    }
    if (!i.recurrence && i.due_date && i.filed_on && (parseISO(i.filed_on).getTime() - parseISO(i.due_date).getTime()) / dayMs > 14) {
      return [{ item_id: i.id, reason: "history", replaced_by: null }];
    }
    return [];
  });
}

/** The timeline's to-dos with why they are not one to act on, as the API gives it (never "Overdue" for those). */
function withAside(db: MockDb, entries: TimelineEntry[]): TimelineEntry[] {
  const items = db.state.items.filter((i) => entries.some((e) => e.ref.type === "item" && e.ref.id === i.id));
  const aside = new Map(setAside(db, items).map((a) => [a.item_id, a.reason]));
  return entries.map((e) => {
    const reason = e.ref.type === "item" ? aside.get(e.ref.id) : undefined;
    return reason && reason !== "suspicious" ? { ...e, aside: reason } : e;
  });
}

function partyDetail(db: MockDb, id: string): PartyDetail {
  const party = db.party(id) ?? notFound("Unknown person or organisation.");
  const items = db.state.items.filter((i) => i.party_id === id && i.status !== "dismissed").sort((a, b) => ((a.due_date ?? "9") < (b.due_date ?? "9") ? -1 : 1));
  return {
    party,
    documents: db.liveDocuments().filter((d) => d.party_id === id).sort((a, b) => ((a.doc_date ?? "") < (b.doc_date ?? "") ? 1 : -1)),
    items,
    contracts: db.state.contracts.filter((c) => c.party_id === id),
    cases: db.state.cases.filter((c) => c.party_id === id),
    set_aside: setAside(db, items),
  };
}

function caseDetail(db: MockDb, id: string): CaseDetail {
  const c = db.state.cases.find((x) => x.id === id) ?? notFound("Unknown thread.");
  return {
    case: c,
    party: db.party(c.party_id),
    documents: db.liveDocuments().filter((d) => d.case_id === id).sort((a, b) => ((a.doc_date ?? "") < (b.doc_date ?? "") ? -1 : 1)),
    items: db.state.items.filter((i) => i.case_id === id),
    drafts: db.state.drafts.filter((d) => d.case_id === id),
  };
}

// ------------------------------------------------------------------------------------------------
// Drafts
// ------------------------------------------------------------------------------------------------

const TEMPLATE_KINDS = new Set<string>(["withdrawal", "extension_request", "payment_plan", "defect_notice", "data_access", "receipts_inspection", "deposit_return", "address_change"]);
const isTemplateKind = (kind: string): kind is TemplateDraftKind => TEMPLATE_KINDS.has(kind);

/** A template letter (fixed text only, as the real app writes it without Claude). */
function composeTemplateDraft(db: MockDb, body: DraftCreate & { kind: TemplateDraftKind }): Draft {
  const contract = body.contract_id ? db.state.contracts.find((c) => c.id === body.contract_id) : undefined;
  const doc = body.doc_id ? db.document(body.doc_id) : null;
  const details = body.details ?? {};
  // instalments on a court order offered to its claimant, typed in: linked to the order, never to the court
  const orderName = doc?.kind === "court_payment_order" ? "Mahnbescheid" : doc?.kind === "enforcement_order" ? "Vollstreckungsbescheid" : null;
  // a typed court is no claimant (compose.to_claimant, review round 3 of phase 2)
  const toClaimant =
    body.kind === "payment_plan" && orderName !== null && Boolean(details.recipient?.trim()) && !mayBeCourt(details.recipient);
  const partyId = toClaimant ? null : body.party_id ?? contract?.party_id ?? doc?.party_id ?? null;
  const party = db.party(partyId);
  const refusal = templateRefusal(body.kind, doc?.kind, toClaimant);
  if (refusal) throw new HttpError(422, refusal);
  if (!party && !details.recipient) throw new HttpError(422, "Choose who the letter is for, or type their name and address.");
  const firstRef = doc?.references[0];
  const reference = contract?.customer_number ? `Kundennummer ${contract.customer_number}` : firstRef ? `${firstRef.label} ${firstRef.value}` : null;
  // the deadline to extend is one someone set — never one the law sets (a rule to-do, an objection period)
  const openDeadline = db.state.items
    .filter((i) => i.doc_id === doc?.id && i.kind === "deadline" && i.status === "open" && i.due_date && i.origin !== "rule" && i.date_spec?.nature !== "objection")
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))[0];
  const payment = db.state.items.find((i) => i.doc_id === doc?.id && i.kind === "payment" && i.status === "open");
  const letterText = doc ? JSON.stringify(letterFor(doc.id) ?? "") : "";
  const period = /(\d{2}\.\d{2}\.\d{4})\s*(?:-|–|bis)\s*(\d{2}\.\d{2}\.\d{4})/.exec(letterText);
  let letter;
  try {
    letter = templateLetter(body.kind, {
      details: { ...details, deadline: details.deadline ?? openDeadline?.due_date ?? null, amount: details.amount ?? payment?.amount ?? null, period: details.period ?? (period ? `${period[1]} – ${period[2]}` : null) },
      reference,
      docDate: doc?.doc_date ?? null,
      topic: contract?.name ?? null,
      address: db.state.profile.address,
      iban: db.state.profile.iban,
      taxOffice: party?.kind === "tax_office",
      schufa: /schufa/i.test(party?.name ?? details.recipient ?? ""),
      today: db.today,
      courtOrder: body.kind === "payment_plan" ? orderName : null,
    });
  } catch (err) {
    throw new HttpError(422, err instanceof Error ? err.message : String(err));
  }
  if (isCourtName(party?.name ?? details.recipient?.split("\n")[0])) letter.guidance.channels = courtChannels();
  const now = nowTs();
  const salutationDe = "Sehr geehrte Damen und Herren,";
  const body_de = [salutationDe, ...letter.paragraphs].join("\n\n");
  const draft: Draft = {
    id: newId("drf"),
    kind: body.kind,
    language: body.language ?? "de",
    tracking_number: null,
    answered_on: null,
    answer_doc_id: null,
    party_id: party?.id ?? null,
    case_id: contract?.case_id ?? doc?.case_id ?? null,
    doc_id: body.doc_id ?? null,
    contract_id: body.contract_id ?? null,
    sender_block: `${SAM.name}\n${SAM.street}\n${SAM.city}`,
    recipient_block: party ? `${party.name}\n${(party.address ?? "").replace(/, /g, "\n")}` : (details.recipient ?? "").trim(),
    place_date: `Musterstadt, ${format(parseISO(db.today), "dd.MM.yyyy")}`,
    subject: letter.subject,
    body: body_de,
    body_translation: [`Subject: ${letter.subjectEn}`, ["Dear Sir or Madam,", ...letter.paragraphsEn].join("\n\n"), `Yours faithfully\n${SAM.name}`].join("\n\n"),
    enclosures: [],
    notes_for_user: [
      "The demo uses Ordnung's fixed sentences only. With Claude connected, it also writes a short polite paragraph in your words.",
      ...letter.notes,
      "Based on the law as of 25 September 2026. Not legal advice. Not reviewed by a lawyer.",
    ],
    checks: [],
    send_guidance: letter.guidance,
    sent_channel: null,
    status: "draft",
    sent_at: null,
    created_at: now,
    updated_at: now,
  };
  return { ...draft, checks: checksFor(db, draft) };
}

/** The remedy the law gives a court order or a landlord's notice, whatever the reading says. */
const STATUTORY_REMEDY: Record<string, string> = { court_payment_order: "Widerspruch", enforcement_order: "Einspruch", landlord_notice: "Widerspruch" };

function composeDraft(db: MockDb, body: DraftCreate): Draft {
  if (isTemplateKind(body.kind)) return composeTemplateDraft(db, { ...body, kind: body.kind });
  const contract = body.contract_id ? db.state.contracts.find((c) => c.id === body.contract_id) : undefined;
  const doc = body.doc_id ? db.document(body.doc_id) : null;
  // a notice without notice period has no hardship objection: its card offers none (compose.objection_remedy)
  const card = doc && body.kind === "objection" && doc.kind === "landlord_notice" ? adviceFor(db, doc) : null;
  if (card && card.draft === null) throw new HttpError(422, card.facts[0]?.text ?? "There is no hardship objection against this notice.");
  // an objection to a court order whose sender isn't a court goes to the court the person typed
  const typedCourt = body.kind === "objection" && doc !== null && needsTypedCourt(doc, db.party(doc.party_id));
  const partyId = typedCourt ? null : body.party_id ?? contract?.party_id ?? doc?.party_id ?? null;
  const party = db.party(partyId);
  const ref = contract?.customer_number ?? doc?.references[0]?.value ?? party?.identifiers[0]?.value ?? "";
  const refLabel = party?.identifiers[0]?.label ?? "Referenz";
  const now = nowTs();
  const placeDate = `Musterstadt, ${format(parseISO(db.today), "dd.MM.yyyy")}`;
  let subject: string;
  let bodyDe: string;
  let bodyEn: string;
  const endDate = contract?.computed?.current_term_end ?? contract?.computed?.earliest_exit ?? null;
  const endDe = endDate ? format(parseISO(endDate), "dd.MM.yyyy") : null;
  const endEn = endDate ? format(parseISO(endDate), "d MMM yyyy") : null;
  if (body.kind === "cancellation") {
    subject = `Kündigung ${contract ? `– ${contract.name}` : ""}${ref ? ` – ${refLabel} ${ref}` : ""}`.trim();
    bodyDe = `Sehr geehrte Damen und Herren,\n\nhiermit kündige ich den oben genannten Vertrag fristgerecht${endDe ? ` zum ${endDe}` : ""}, hilfsweise zum nächstmöglichen Zeitpunkt.\n\nBitte bestätigen Sie mir den Eingang dieser Kündigung und das Beendigungsdatum schriftlich.\n\nMit freundlichen Grüßen\n\n${SAM.name}`;
    bodyEn = `Dear Sir or Madam,\n\nI hereby cancel the above contract with due notice${endEn ? ` effective ${endEn}` : ""}, or alternatively at the next possible date.\n\nPlease confirm receipt of this cancellation and the end date in writing.\n\nKind regards\n\n${SAM.name}`;
  } else if (body.kind === "objection" && doc?.kind && STATUTORY_REMEDY[doc.kind]) {
    const dDate = doc.doc_date ? format(parseISO(doc.doc_date), "dd.MM.yyyy") : "";
    // the application to suspend enforcement only when ticked, and only against an enforcement order (templates.objection)
    const suspend = body.suspend_enforcement && doc.kind === "enforcement_order";
    const suspendDe = suspend ? "\n\nIch beantrage, die Zwangsvollstreckung aus dem Vollstreckungsbescheid einstweilen einzustellen." : "";
    const suspendEn = suspend ? "\n\nI apply for enforcement of the order to be suspended for the time being (einstweilige Einstellung)." : "";
    const remedy = STATUTORY_REMEDY[doc.kind]!;
    const noun = doc.kind === "court_payment_order" ? "Mahnbescheid" : doc.kind === "enforcement_order" ? "Vollstreckungsbescheid" : "Kündigung";
    subject = `${remedy} gegen ${doc.kind === "landlord_notice" ? "Ihre" : "den"} ${noun}${dDate ? ` vom ${dDate}` : ""}${ref ? ` – ${refLabel} ${ref}` : ""}`;
    bodyDe =
      doc.kind === "landlord_notice"
        ? `Sehr geehrte Damen und Herren,\n\nhiermit widerspreche ich Ihrer Kündigung${dDate ? ` vom ${dDate}` : ""} des Mietverhältnisses und verlange die Fortsetzung des Mietverhältnisses (§ 574 BGB).\n\nDie Gründe teile ich Ihnen auf Wunsch gesondert mit.\n\nMit freundlichen Grüßen\n\n${SAM.name}`
        : `Sehr geehrte Damen und Herren,\n\nhiermit lege ich gegen den ${noun}${dDate ? ` vom ${dDate}` : ""}${ref ? `, ${refLabel} ${ref},` : ""} ${remedy} ein.\n\n${doc.kind === "court_payment_order" ? "Ich widerspreche dem geltend gemachten Anspruch insgesamt." : "Eine Begründung reiche ich nach."}${suspendDe}\n\nMit freundlichen Grüßen\n\n${SAM.name}`;
    bodyEn =
      doc.kind === "landlord_notice"
        ? `Dear Sir or Madam,\n\nI hereby object to your notice terminating the tenancy and request that the tenancy be continued (§ 574 BGB).\n\nI will give you my reasons separately on request.\n\nYours faithfully\n\n${SAM.name}`
        : `Dear Sir or Madam,\n\nI hereby lodge an objection (${remedy}) against the ${noun}${ref ? `, ${refLabel} ${ref}` : ""}.\n\n${doc.kind === "court_payment_order" ? "I object to the entire claim." : "I will submit the reasons separately."}${suspendEn}\n\nYours faithfully\n\n${SAM.name}`;
  } else if (body.kind === "objection") {
    const dDate = doc?.doc_date ? format(parseISO(doc.doc_date), "dd.MM.yyyy") : "…";
    subject = `Einspruch gegen den Bescheid vom ${dDate}${ref ? ` – ${refLabel} ${ref}` : ""}`;
    bodyDe = `Sehr geehrte Damen und Herren,\n\nhiermit lege ich gegen den Bescheid vom ${dDate}${ref ? `, ${refLabel} ${ref},` : ""} Einspruch ein. Eine Begründung reiche ich nach.\n\n${body.suspend_enforcement ? "Ich beantrage die Aussetzung der Vollziehung.\n\n" : ""}${body.instructions ? "Die Aufwendungen für meinen Laptop (1.049,00 EUR) nutze ich überwiegend beruflich; eine Bestätigung meines Arbeitgebers füge ich bei.\n\n" : ""}Mit freundlichen Grüßen\n\n${SAM.name}`;
    bodyEn = `Dear Sir or Madam,\n\nI hereby file an objection (Einspruch) against the decision of ${doc?.doc_date ? format(parseISO(doc.doc_date), "d MMM yyyy") : "…"}${ref ? `, ${refLabel} ${ref}` : ""}. I will submit my reasons separately.\n\n${body.suspend_enforcement ? "I apply for suspension of enforcement (Aussetzung der Vollziehung).\n\n" : ""}${body.instructions ? "I use my laptop (€1,049.00) mainly for work; I enclose a confirmation from my employer.\n\n" : ""}Kind regards\n\n${SAM.name}`;
  } else {
    subject = `Ihr Schreiben${doc?.doc_date ? ` vom ${format(parseISO(doc.doc_date), "dd.MM.yyyy")}` : ""}${ref ? ` – ${refLabel} ${ref}` : ""}`;
    bodyDe = `Sehr geehrte Damen und Herren,\n\nvielen Dank für Ihr Schreiben. ${body.instructions ? "Ich habe dazu folgende Frage: …" : "Bitte teilen Sie mir mit, wie wir weiter verfahren."}\n\nMit freundlichen Grüßen\n\n${SAM.name}`;
    bodyEn = `Dear Sir or Madam,\n\nthank you for your letter. ${body.instructions ? "I have the following question: …" : "Please let me know how we proceed."}\n\nKind regards\n\n${SAM.name}`;
  }
  const statutory = body.kind === "objection" && doc?.kind ? STATUTORY_OBJECTIONS[doc.kind] : undefined;
  const letterDeadline = db.state.items.find((i) => i.doc_id === doc?.id && i.kind === "deadline" && i.status === "open");
  const guidance =
    contract?.id === "ctr_phone"
      ? phoneGuidance()
      : statutory
        ? // a court order's or a landlord's notice's objection: the real rules' form and channels (never e-mail at a court)
          { ...structuredClone(statutory.guidance), send_by: letterDeadline?.send_by ?? null, must_arrive_by: letterDeadline?.due_date ?? null }
        : {
          send_by: contract?.computed?.send_by ?? db.state.items.find((i) => i.doc_id === doc?.id && i.send_by)?.send_by ?? null,
          post_too_late: false,
          must_arrive_by: contract?.computed?.cancel_by ?? db.state.items.find((i) => i.doc_id === doc?.id && i.kind === "deadline")?.due_date ?? null,
          form: contract?.category === "rent" || contract?.category === "employment" ? ("written_form" as const) : ("text_form" as const),
          form_note:
            contract?.category === "rent" || contract?.category === "employment"
              ? "Must be signed by hand on paper — print, sign and send by Einwurf-Einschreiben."
              : "Text form is enough: email or letter.",
          channels: [
            { channel: "registered_letter" as const, label: "Einwurf-Einschreiben", allowed: true, recommended: true, note: "Keep the receipt as proof of delivery.", citation: null },
            { channel: "email" as const, label: party?.email ? `Email to ${party.email}` : "Email", allowed: !(contract?.category === "rent" || contract?.category === "employment"), recommended: false, note: null, citation: null },
          ],
          tips: ["Keep a copy of what you sent."],
        };
  if (!statutory && isCourtName(party?.name)) guidance.channels = courtChannels();
  if (typedCourt) guidance.channels = courtChannels();
  const draft: Draft = {
    id: newId("drf"),
    kind: body.kind,
    language: body.language ?? "de",
    tracking_number: null,
    answered_on: null,
    answer_doc_id: null,
    party_id: partyId,
    case_id: body.case_id ?? contract?.case_id ?? doc?.case_id ?? null,
    doc_id: body.doc_id ?? null,
    contract_id: body.contract_id ?? null,
    sender_block: `${SAM.name}\n${SAM.street}\n${SAM.city}\n${SAM.email}`,
    recipient_block: party ? `${party.name}\n${(party.address ?? "").replace(/, /g, "\n")}` : (body.details?.recipient ?? "").trim(),
    place_date: placeDate,
    subject,
    body: bodyDe,
    body_translation: bodyEn,
    enclosures: body.kind === "objection" && body.instructions ? ["Bestätigung des Arbeitgebers"] : [],
    notes_for_user: statutory ? [...statutory.notes] : body.kind === "objection" ? ["An objection is free. It only needs to arrive in time — reasons can follow later."] : [],
    checks: [],
    send_guidance: guidance,
    sent_channel: null,
    status: "draft",
    sent_at: null,
    created_at: now,
    updated_at: now,
  };
  return { ...draft, checks: checksFor(db, draft) };
}

/** The API's checks for a draft as it stands now (they run again whenever it is saved). */
function checksFor(db: MockDb, d: Draft): Draft["checks"] {
  const contract = d.contract_id ? db.state.contracts.find((c) => c.id === d.contract_id) : undefined;
  const doc = d.doc_id ? db.document(d.doc_id) : null;
  const party = db.party(d.party_id);
  const channel = d.send_guidance?.channels.find((c) => c.channel === d.sent_channel);
  return draftChecks({
    ...d,
    references: [contract?.customer_number, ...(doc?.references ?? []).map((r) => r.value), ...(party?.identifiers ?? []).map((r) => r.value)],
    letterDate: doc?.doc_date ? format(parseISO(doc.doc_date), "dd.MM.yyyy") : null,
    formNote: d.send_guidance?.form_note,
    sentVia: d.status === "sent" ? (channel?.label ?? null) : null,
  });
}

// ------------------------------------------------------------------------------------------------
// Ask (streamed)
// ------------------------------------------------------------------------------------------------

const CITABLE = new Set<string>(["document", "item", "contract", "party"]);

/** Titles of the New-mail letters' records before they are opened (recordings may cite them). */
function trayLabel(r: SuggestionRef): string | null {
  if (r.type === "document") {
    const d = TRAY_DOCUMENTS[r.id];
    return d ? (d.title ?? d.filename) : null;
  }
  if (r.type === "item") return Object.values(TRAY_ITEMS).flat().find((i) => i.id === r.id)?.title ?? null;
  if (r.type === "party") return PARTIES.find((p) => p.id === r.id)?.name ?? null;
  return null;
}

/** Citations as the API's `done` event carries them: with the cited record's label. */
function citationRefs(db: MockDb, refs: SuggestionRef[]): CitationRef[] {
  const labelOf = (r: SuggestionRef): string | null => {
    if (r.type === "document") {
      const d = db.document(r.id);
      return d ? (d.title ?? d.filename) : null;
    }
    if (r.type === "item") return db.state.items.find((i) => i.id === r.id)?.title ?? null;
    if (r.type === "contract") return db.state.contracts.find((c) => c.id === r.id)?.name ?? null;
    return db.party(r.id)?.name ?? null;
  };
  // recordings may cite letters of the New-mail tray that aren't opened yet: label them from the tray;
  // like the API, a citation of a record that exists nowhere is dropped
  return refs.flatMap((r) => {
    const label = CITABLE.has(r.type) ? (labelOf(r) ?? trayLabel(r)) : null;
    return label ? [{ type: r.type as CitationRef["type"], id: r.id, label }] : [];
  });
}

/** The check's label, as the API sends it with every checked answer (the recordings are English). */
const CHECK_LABEL = "Checked by Ordnung:";

function askStream(ctx: Ctx): Response {
  const { db } = ctx;
  const body = (ctx.body ?? {}) as { question?: string; thread_id?: string | null };
  const question = (body.question ?? "").trim();
  const threadId = body.thread_id || newId("thr");
  const q = question.toLowerCase();
  const rec = RECORDED.find((r) => r.question.toLowerCase() === q) ?? RECORDED.find((r) => r.match.some((group) => group.every((w) => q.includes(w))));
  const now = nowTs();
  // like the API, only an answer is stored with its question: the demo's "no recording" reply is not
  // (it never went through the check, so it carries no message id and no "checked" line)
  if (rec)
    db.state.chat.push({ id: newId("msg"), thread_id: threadId, role: "user", content: question, citations: [], tool_calls: [], created_at: now, note: null, note_label: null, checked: false });
  const enc = new TextEncoder();
  const signal = ctx.signal;
  const speed = ctx.opts.latency ?? 1;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // like the API: one default `message` event per StreamEvent, `type` inside the JSON data
      const send = (ev: StreamEvent) => {
        if (signal?.aborted) return;
        controller.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`));
      };
      try {
        controller.enqueue(enc.encode(": connected\n\n"));
        await sleep(250 * speed, signal);
        // like the real API: the tool trace, one `text` event without text while the answer is
        // written (its words — `raw` — are never sent before the check), then `done` with the checked
        // answer, which may leave a value or a sentence out, and Ordnung's note in its own field.
        // A question without a recording gets the demo's `demo_miss` error, as from the local demo: the
        // Ask page shows it as a note, not as a failure to retry.
        if (!rec) {
          send({ type: "error", error: FALLBACK_ANSWER, text: FALLBACK_ANSWER, error_code: "demo_miss" });
          return;
        }
        const text = rec.text;
        const written = rec.raw ?? text;
        for (const t of rec.tools) {
          send({ type: "tool_use", name: t.name, input: t.input });
          await sleep(550 * speed, signal);
          send({ type: "tool_result", name: t.name, text: t.result });
          await sleep(200 * speed, signal);
        }
        send({ type: "text" });
        await sleep(Math.min(2500, 4 * written.length) * speed, signal);
        const messageId = newId("msg");
        db.state.chat.push({
          id: messageId,
          thread_id: threadId,
          role: "assistant",
          content: text,
          citations: rec.citations ?? [],
          tool_calls: rec.tools.map((t) => ({ name: t.name, input: t.input, result: t.result })),
          created_at: nowTs(),
          note: rec.note ?? null,
          note_label: CHECK_LABEL,
          checked: true,
        } satisfies ChatMessage);
        send({ type: "done", text, note: rec.note ?? null, note_label: CHECK_LABEL, message_id: messageId, thread_id: threadId, citations: citationRefs(db, rec.citations ?? []) });
      } catch (err) {
        send({ type: "error", error: err instanceof Error ? err.message : "The answer was interrupted." });
      } finally {
        try {
          controller.close();
        } catch {
          /* closed */
        }
      }
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" } });
}

// ------------------------------------------------------------------------------------------------
// Routes
// ------------------------------------------------------------------------------------------------

const ITEM_PATCHABLE = ["title", "description", "due_date", "due_time", "amount", "status", "snoozed_until", "priority", "area", "location", "recurrence"] as const;
/** A letter filed as another kind than it was read as: the online demo has no rules engine to follow it. */
export function refiledNote(read: Document["kind"], chosen: Document["kind"]): string {
  return (
    `${DEMO_NOTE} the dates and to-dos on this page are still those of the kind it was read as, “${documentKindLabel(read ?? "other")}”. ` +
    `This demo has no rules engine to work them out again for “${documentKindLabel(chosen ?? "other")}” — the installed app does.`
  );
}

const DOC_PATCHABLE = ["title", "kind", "area", "doc_date", "received_date", "party_id", "case_id", "ai_private", "tags", "direction"] as const;

function withoutNulls(src: unknown): Record<string, unknown> {
  return Object.fromEntries(Object.entries((src ?? {}) as Record<string, unknown>).filter(([, v]) => v !== null && v !== undefined));
}

function pick<T extends object>(src: unknown, keys: readonly string[]): Partial<T> {
  const out: Record<string, unknown> = {};
  if (src && typeof src === "object") for (const k of keys) if (k in src) out[k] = (src as Record<string, unknown>)[k];
  return out as Partial<T>;
}

/** NW's public holidays the gym's four weeks can end on (the mock has no holiday calendar). */
const NW_HOLIDAYS: Record<string, string> = {
  "2026-10-03": "Tag der Deutschen Einheit",
  "2026-11-01": "Allerheiligen",
  "2026-12-25": "Erster Weihnachtstag",
  "2026-12-26": "Zweiter Weihnachtstag",
  "2027-01-01": "Neujahr",
};

/** Why `d` is no working day in NW, in the engine's words ("a Saturday", "a public holiday, …"), or null. */
function notWorkingDay(d: Date): string | null {
  const holiday = NW_HOLIDAYS[format(d, "yyyy-MM-dd")];
  if (holiday) return `a public holiday, ${holiday}`;
  if (d.getDay() === 6) return "a Saturday";
  return d.getDay() === 0 ? "a Sunday" : null;
}

/**
 * Like the API: FitWell's four weeks run from the arrival day the person confirmed (§ 130 BGB); an end
 * on a weekend or holiday moves to the next working day (§ 193 BGB), and the send-by date leaves four
 * working days for the post.
 */
function recomputeGymPrice(db: MockDb, receivedDate: string) {
  const it = db.state.items.find((i) => i.id === "itm_gym_price");
  if (!it?.computation) return;
  const day = (d: Date | string) => format(typeof d === "string" ? parseISO(d) : d, "EEE d MMM yyyy");
  const iso = (d: Date) => format(d, "yyyy-MM-dd");
  const end = addDays(parseISO(receivedDate), 28);
  const why = notWorkingDay(end);
  let due = end;
  while (notWorkingDay(due)) due = addDays(due, 1);
  let sendBy = due;
  for (let left = 4; left > 0; ) {
    sendBy = addDays(sendBy, -1);
    if (!notWorkingDay(sendBy)) left -= 1;
  }
  const moved = why ? `${day(end)} is ${why}, so the deadline moves to ${day(due)}` : `${day(due)} is a working day, so it stays`;
  it.due_date = iso(due);
  it.send_by = iso(sendBy);
  it.grounding = "user";
  it.updated_at = nowTs();
  it.computation = {
    ...it.computation,
    due_date: iso(due),
    send_by: iso(sendBy),
    summary: `Four weeks after the day you received it (${day(receivedDate)}) is ${why ? `${day(end)}, ${why}, so the deadline moves to ${day(due)}` : day(due)}.`,
    steps: [
      { label: `Not an authority's letter, so no delivery days: the period runs from the day you received it (${day(receivedDate)})`, date: receivedDate, rule_id: "private_sender_arrival", citation: "§ 130 Abs. 1 BGB" },
      { label: `Counting starts the day after ${day(receivedDate)}`, date: receivedDate, rule_id: "bgb_187_1", citation: "§ 187 Abs. 1 BGB" },
      { label: `Four weeks later: ${day(end)}`, date: iso(end), rule_id: "bgb_188", citation: "§ 188 Abs. 2 BGB" },
      { label: moved, date: iso(due), rule_id: "bgb_193", citation: "§ 193 BGB" },
      { label: `Send by ${day(sendBy)} to allow 4 business days for a letter to arrive`, date: iso(sendBy), rule_id: "postal_buffer", citation: null },
    ],
    rule_ids: ["private_sender_arrival", "bgb_187_1", "bgb_188", "bgb_193", "postal_buffer"],
    // like the engine: the rule it applied stays said; the arrival day is no longer assumed
    warnings: it.computation.warnings.filter((w) => w.startsWith("No delivery days were added")),
    confidence: "high",
  };
}

/** `d` moved by `n` NW working days (negative: back); `d` itself is not counted. */
function workingDays(d: Date, n: number): Date {
  let x = d;
  for (let left = Math.abs(n); left > 0; ) {
    x = addDays(x, Math.sign(n));
    if (!notWorkingDay(x)) left -= 1;
  }
  return x;
}

/**
 * The notice terms in words, as the API's `entered_notice` says them — null when they give no dates by
 * themselves: a period with its basis (a job's without one runs to the 15th or the end of a month), the
 * day of the month notice must arrive by, with the period asked for too, or — for a job or a lease — the
 * statutory notice periods the contract names; a fixed-term job's early notice is named.
 */
function enteredNotice(c: Contract): string | null {
  const { notice_value: n, notice_unit: unit, notice_basis: basis, notice_day: day } = c;
  const period = n != null && unit ? periodPhrase(n, unit) : null;
  const job = c.category === "employment";
  let words: string;
  if (day && basis === "end_of_month") words = `${period ?? "notice"} by the ${ordinal(day)} of the month, to the end of that month`;
  else if (period && basis) words = `${period} ${NOTICE_BASIS_COPY[basis].label}`;
  else if (period && job) words = `${period} to the 15th or the end of a month`;
  else if (c.notice_statutory && (job || c.category === "rent")) words = "the statutory notice periods";
  else return null;
  return job && c.end_date && c.notice_before_end ? `${words}, also before the fixed term ends` : words;
}

/**
 * The API's `notice_evidence`: the contract's quotes with the notice terms the person entered as one
 * of their own (grounding `user`) when they give dates by themselves — replaced by the next correction,
 * gone again with an Undo back to none. The letter's quotes stay.
 */
function noticeEvidence(c: Contract): Evidence[] {
  const kept = c.evidence.filter((e) => e.grounding !== "user");
  const quote = enteredNotice(c);
  if (!quote) return kept;
  return [...kept, { doc_id: c.source_doc_id ?? "", page: null, quote, grounding: "user", value_consistent: true, score: 0, boxes: [] }];
}

const mockDay = (d: Date, year = true) => format(d, year ? "EEE d MMM yyyy" : "EEE d MMM");
const mockIso = (d: Date) => format(d, "yyyy-MM-dd");

/** `d` moved by `k` notice periods of `unit`. */
function addNotice(d: Date, k: number, unit: NoticeUnit): Date {
  return unit === "months" ? addMonths(d, k) : addDays(d, (unit === "weeks" ? 7 : 1) * k);
}

/** The latest day `n` `unit`s' notice can arrive so that the period fits before the end of `end`. */
function latestReceipt(end: Date, n: number, unit: NoticeUnit): Date {
  let r = addNotice(end, -n, unit);
  while (addNotice(addDays(r, 1), n, unit) <= end) r = addDays(r, 1);
  return r;
}

/** The safe date (the last working day on or before `cancelBy`) and when to post a letter: four working days before it, today at the latest. */
function sendingDates(cancelBy: Date, today: Date): { safe: Date; sendBy: Date; late: boolean } {
  let safe = cancelBy;
  while (notWorkingDay(safe)) safe = addDays(safe, -1);
  const late = workingDays(safe, -4) < today;
  return { safe, sendBy: late ? today : workingDays(safe, -4), late };
}

/** A period in the engine's words (`fmt_period`): "one month", "four weeks", "10 days". */
function fmtPeriod(n: number, unit: NoticeUnit): string {
  const number = unit !== "days" && n >= 1 && n <= 6 ? ["one", "two", "three", "four", "five", "six"][n - 1] : String(n);
  return `${number} ${n === 1 ? unit.replace(/s$/, "") : unit}`;
}

/** A notice period in the engine's words (`notice_phrase`): "one month's notice", "four weeks' notice". */
const periodPhrase = (n: number, unit: NoticeUnit) => `${fmtPeriod(n, unit)}${n === 1 ? "'s" : "'"} notice`;

/** The rule each regime the mock works dates out for applies first (`_REGIME_RULE`). */
const REGIME_RULE: Record<string, string> = { as_written: "contract_as_written", bgb309_new: "bgb_309_9_new", tkg56: "tkg_56", employment622: "bgb_622" };

/** Rules under which a consumer contract after its first term can be ended any day with at most one month's notice, or at a month's end by its own day of the month. */
const MINIMUM_TERM_REGIMES = new Set<string>(["bgb309_new", "tkg56"]);

/**
 * Like the rules engine once the person entered the notice terms on a card, for the contracts whose card
 * offers it: one that follows its own terms (`as_written`), a consumer contract whose first term is over
 * (at most one month's notice, any day — `_plan_minimum_term`) and a fixed-term job ({@link recomputeJob}).
 * "At any time" counts the notice from when a letter posted today arrives (four working days); "to the end
 * of a month" finds the first month end whose deadline — the notice period's, or the contract's day of that
 * month, whichever comes first (`DayOfMonth`) — hasn't passed; "to the end of the term" needs a start date
 * and term the mock's contracts don't have. Other contracts keep their dates (the mock has no rules engine
 * for those), and so does a first term still running.
 */
function recomputeNotice(db: MockDb, c: Contract) {
  const regime = c.computed?.regime ?? "";
  if (regime === "employment622") return recomputeJob(db, c);
  const consumer = MINIMUM_TERM_REGIMES.has(regime);
  if (!c.computed || (regime !== "as_written" && !consumer) || (consumer && (c.computed.current_term_end ?? "") >= db.today)) return;
  const today = parseISO(db.today);
  const byDay = c.notice_day && c.notice_basis === "end_of_month" ? c.notice_day : null;
  let n = c.notice_value;
  let unit = c.notice_unit;
  let basis = c.notice_basis;
  // a consumer contract: at most one month's notice, one month when none is given (assumed), counted from any
  // day — unless the contract's day of the month decides
  const assumed = consumer && !byDay && (!n || !unit);
  if (consumer && (assumed || (n && unit && (unit === "months" ? n > 1 : unit === "weeks" ? n > 4 : n > 30)))) [n, unit] = [1, "months"];
  if (consumer && !byDay) basis = "any_time";
  const general = "No special consumer rule applies that we know of, so we used the contract's own terms.";
  const warnings = assumed ? ["The contract's notice period wasn't found; we assumed the longest the law allows, which gives the earliest date."] : consumer ? [] : [general];
  const blank: ContractComputation = {
    ...c.computed,
    current_term_end: null,
    cancel_by: null,
    send_by: null,
    safe_date: null,
    next_renewal: null,
    earliest_exit: null,
    confidence: assumed ? "medium" : consumer ? "high" : "low",
    steps: [],
    warnings,
  };
  const unknown = (reason: string) => {
    c.computed = { ...blank, confidence: "low", summary: `We couldn't compute a cancellation date: ${reason[0]!.toLowerCase()}${reason.slice(1)}`, warnings: [...warnings, reason] };
  };
  if (!byDay && (!n || !unit)) return unknown("The contract's notice period is missing.");
  if (basis === "any_time" && n && unit) {
    const arrival = workingDays(today, 4);
    const exit = addNotice(arrival, n, unit);
    c.computed = {
      ...blank,
      earliest_exit: mockIso(exit),
      summary: `You can cancel any time with ${periodPhrase(n, unit)}: if your cancellation arrives by ${mockDay(arrival)}, the contract ends on ${mockDay(exit)}.`,
      steps: [{ label: `If it arrives by ${mockDay(arrival)}, the contract ends ${fmtPeriod(n, unit)} later, on ${mockDay(exit)}`, date: mockIso(exit), rule_id: "bgb_188", citation: "§ 188 BGB" }],
      rule_ids: [REGIME_RULE[regime]!, "bgb_188"],
    };
    return;
  }
  if (basis !== "end_of_month") return unknown("We need the contract's start date and term to compute the deadline.");
  // the notice period's deadline, or the contract's day of the month the contract ends in: the earlier one
  const deadline = (end: Date) => {
    const onDay = byDay ? new Date(end.getFullYear(), end.getMonth(), Math.min(byDay, end.getDate())) : null;
    const byPeriod = n && unit ? latestReceipt(end, n, unit) : null;
    return onDay && byPeriod ? (onDay < byPeriod ? onDay : byPeriod) : (onDay ?? byPeriod)!;
  };
  let end = endOfMonth(today);
  while (deadline(end) < today) end = endOfMonth(addDays(end, 1));
  const cancelBy = deadline(end);
  const { safe, sendBy, late } = sendingDates(cancelBy, today);
  // the engine's `DayOfMonth`: its text ("the 10th of the month", "10 days' notice by the 10th of the month") and phrase
  const dayText = byDay ? `${n && unit ? `${periodPhrase(n, unit)} by ` : ""}the ${ordinal(byDay)} of the month` : null;
  const notice = dayText ? (n && unit ? dayText : `notice by ${dayText}`) : periodPhrase(n!, unit!);
  const steps: ContractComputation["steps"] = [
    { label: `To end the contract on ${mockDay(end)} with ${notice}, it must arrive by ${mockDay(cancelBy)}`, date: mockIso(cancelBy), rule_id: byDay ? "contract_as_written" : "bgb_188", citation: byDay ? "The contract's own terms" : "§ 188 BGB" },
  ];
  if (mockIso(safe) !== mockIso(cancelBy)) steps.push({ label: `Safe date: make sure it arrives by ${mockDay(safe)}`, date: mockIso(safe), rule_id: "safe_date", citation: null });
  steps.push({ label: `Post it by ${mockDay(sendBy)} to allow 4 business days for delivery`, date: mockIso(sendBy), rule_id: "postal_buffer", citation: null });
  const detail = dayText ? ` (${dayText}, as the contract says)` : "";
  c.computed = {
    ...blank,
    cancel_by: mockIso(cancelBy),
    safe_date: mockIso(safe),
    send_by: mockIso(sendBy),
    earliest_exit: mockIso(end),
    summary: `To leave on ${mockDay(end)}, your notice must arrive by ${mockDay(cancelBy)}${detail}${mockIso(sendBy) !== mockIso(cancelBy) ? `; send it by ${mockDay(sendBy, false)}` : ""}.`,
    steps,
    rule_ids: [...new Set([REGIME_RULE[regime]!, ...steps.map((s) => s.rule_id!)])],
    warnings: late ? [...warnings, "The usual sending time has passed — use the fastest channel allowed (online button, email, fax or in person) today."] : warnings,
  };
}

/** The engine's note on a job whose contract names the statutory notice periods (`_STATUTORY_NOTE`). */
const STATUTORY_JOB_NOTE =
  "Your contract names the statutory notice periods: for you, four weeks to the 15th or the end of a month (§ 622 Abs. 1 BGB). The longer periods of § 622 Abs. 2 BGB bind only your employer, unless your contract extends them to you (§ 622 Abs. 6 BGB).";

/**
 * Like the rules engine for a fixed-term job once the person entered its notice terms (`_ends_by_itself`,
 * `_plan_employment`): it ends by itself on its end date unless its contract lets it be ended earlier by
 * notice. Then it is planned like an open-ended job — at least four weeks' notice to the 15th or the end of
 * a month (only the end of a month when the contract says so) — and still ends by itself on that date when
 * the notice can't end it sooner. A job without an end date, or past it, keeps its dates.
 */
function recomputeJob(db: MockDb, c: Contract) {
  if (!c.computed || !c.end_date || c.end_date < db.today) return;
  const today = parseISO(db.today);
  const end = parseISO(c.end_date);
  // the engine names the statutory periods the contract names only where notice was planned
  const others = (c.computed.notes ?? []).filter((note) => note !== STATUTORY_JOB_NOTE);
  const fixed = (label: string, notes = others) => {
    c.computed = {
      ...c.computed!,
      notes,
      current_term_end: c.end_date,
      cancel_by: null,
      send_by: null,
      safe_date: null,
      next_renewal: null,
      earliest_exit: c.end_date,
      confidence: "high",
      warnings: [],
      summary: `This contract ends by itself on ${mockDay(end)} — no cancellation needed.`,
      steps: [{ label, date: c.end_date, rule_id: "fixed_term", citation: "§ 620 Abs. 1 BGB; § 15 Abs. 1 TzBfG" }],
      rule_ids: ["bgb_622", "fixed_term"],
    };
  };
  if (!c.notice_before_end) return fixed(`Fixed term: it ends on ${mockDay(end)}`);
  const warnings: string[] = [];
  let n = c.notice_value ?? 4;
  let unit: NoticeUnit = c.notice_unit ?? "weeks";
  let basis = c.notice_basis;
  // a contract that names the statutory periods states the four weeks (`notice_statutory`): no warning, a note
  const statutory = c.notice_statutory && (!c.notice_value || !c.notice_unit);
  if ((!c.notice_value || !c.notice_unit) && !statutory) warnings.push("No notice period found; we used the statutory four weeks (§ 622 Abs. 1 BGB) — check your contract or collective agreement for a longer one.");
  const notes = statutory ? [...others, STATUTORY_JOB_NOTE] : others;
  // before the fixed term's end, § 622 Abs. 1 BGB at least: a shorter notice, or notice to any day, is usually the probation period's
  const shorter = latestReceipt(end, n, unit) > latestReceipt(end, 4, "weeks");
  if (shorter || basis === "any_time") {
    warnings.push("Before the fixed term's end we used at least four weeks' notice to the 15th or the end of a month (§ 622 Abs. 1 BGB): a shorter notice, or notice to any day, is usually the probation period's (§ 622 Abs. 3 BGB), and after it a contract can rarely agree less (§ 622 Abs. 4, 5 BGB).");
    if (shorter) [n, unit] = [4, "weeks"];
    basis = null;
  }
  const monthEndOnly = basis === "end_of_month";
  const deadline = (d: Date) => latestReceipt(d, n, unit);
  // the first 15th or end of a month (only an end, when the contract says so) whose deadline hasn't passed
  const exit = ((): Date => {
    for (let month = endOfMonth(today); ; month = endOfMonth(addDays(month, 1))) {
      const days = monthEndOnly ? [month] : [new Date(month.getFullYear(), month.getMonth(), 15), month];
      const reachable = days.find((d) => deadline(d) >= today);
      if (reachable) return reachable;
    }
  })();
  const cancelBy = deadline(exit);
  if (exit >= end) return fixed(`Fixed term: notice can't end it sooner, so it ends on ${mockDay(end)}`, notes);
  const { safe, sendBy, late } = sendingDates(cancelBy, today);
  if (late) warnings.push("The usual sending time has passed — hand the signed letter over in person (with a witness) or by messenger today.");
  const steps: ContractComputation["steps"] = [
    { label: `To end the contract on ${mockDay(exit)} with ${periodPhrase(n, unit)}, it must arrive by ${mockDay(cancelBy)}`, date: mockIso(cancelBy), rule_id: "bgb_188", citation: "§ 188 BGB" },
    { label: `If you don't give notice, it ends by itself on ${mockDay(end)}`, date: c.end_date, rule_id: "fixed_term", citation: "§ 620 Abs. 1 BGB; § 15 Abs. 1 TzBfG" },
  ];
  if (mockIso(safe) !== mockIso(cancelBy)) steps.push({ label: `Safe date: make sure it arrives by ${mockDay(safe)}`, date: mockIso(safe), rule_id: "safe_date", citation: null });
  steps.push({ label: `Post it by ${mockDay(sendBy)} to allow 4 business days for delivery`, date: mockIso(sendBy), rule_id: "postal_buffer", citation: null });
  const send = mockIso(sendBy) !== mockIso(cancelBy) ? `; send it by ${mockDay(sendBy, false)}` : "";
  c.computed = {
    ...c.computed,
    current_term_end: c.end_date,
    cancel_by: mockIso(cancelBy),
    send_by: mockIso(sendBy),
    safe_date: mockIso(safe),
    next_renewal: null,
    earliest_exit: mockIso(exit),
    confidence: warnings.some((w) => w.startsWith("No notice period")) ? "medium" : "high",
    warnings,
    notes,
    summary: `To leave on ${mockDay(exit)}, your notice must arrive by ${mockDay(cancelBy)}${send}. If you don't give notice, it ends by itself on ${mockDay(end)}.`,
    steps,
    rule_ids: ["bgb_622", ...steps.map((s) => s.rule_id!)],
  };
}

function recomputeParking(db: MockDb, receivedDate: string) {
  const it = db.state.items.find((i) => i.id === "itm_parking");
  if (!it) return;
  const due = format(addDays(parseISO(receivedDate), 7), "yyyy-MM-dd");
  it.due_date = due;
  it.grounding = "user";
  it.updated_at = nowTs();
  it.computation = {
    ...(it.computation ?? { holiday_calendar: "", rule_ids: [], steps: [], summary: "", warnings: [], confidence: "high", due_date: due, send_by: null, safe_date: null }),
    due_date: due,
    summary: `The letter reached you on ${format(parseISO(receivedDate), "EEE d MMM")}; one week later is ${format(parseISO(due), "EEE d MMM")}.`,
    steps: [
      { label: "Letter arrived (confirmed by you)", date: receivedDate, rule_id: "receipt_user", citation: null },
      { label: "One week later", date: due, rule_id: "bgb_188", citation: "§ 188 Abs. 2 BGB" },
    ],
    warnings: [],
    confidence: "high",
  };
  const s = db.state.suggestions.find((x) => x.id === "sug_parking");
  if (s) s.status = "done";
}

/** The Mahnbescheid's objection deadline once Sam enters the envelope date (receipts computed by the real rules). */
function recomputeCourtOrder(db: MockDb, receivedDate: string) {
  const it = db.state.items.find((i) => i.id === "itm_court_objection");
  const receipt = ORDER_RECEIPTS[receivedDate];
  if (!it || !receipt) return;
  Object.assign(it, { due_date: receipt.due_date, send_by: receipt.send_by, computation: receipt, updated_at: nowTs() });
}

const routes: [string, string, Handler][] = [
  // system
  [
    "GET",
    "/health",
    ({ db, query }) => (query.get("probe") === "1" || query.get("probe") === "true" ? { ...db.state.health, checks: DEMO_CHECKS } : db.state.health) satisfies Health,
  ],
  ["GET", "/profile", ({ db }) => db.state.profile],
  // like the API: PUT merges the fields sent (nulls change nothing; `models` merges by purpose)
  [
    "PUT",
    "/profile",
    ({ db, body }) => {
      const patch = withoutNulls(body) as Partial<Profile>;
      if (typeof patch.iban === "string" && patch.iban.trim()) {
        if (!ibanLooksValid(patch.iban)) throw new HttpError(422, "That IBAN isn't valid — check it against your bank card or banking app.");
        patch.iban = normalizeIban(patch.iban);
      }
      return (db.state.profile = { ...db.state.profile, ...patch });
    },
  ],
  ["GET", "/settings", ({ db }) => db.state.settings],
  [
    "PUT",
    "/settings",
    ({ db, body }) => {
      const patch = withoutNulls(body) as Partial<AppSettings> & { models?: Record<string, string> };
      for (const key of ["demo", "simulated_today"] as const) {
        if (key in patch && patch[key] !== db.state.settings[key]) throw new HttpError(422, `“${key}” is set by how Ordnung was started.`);
      }
      const models = { ...db.state.settings.models, ...(patch.models ?? {}) };
      const sent = body && typeof body === "object" ? (body as { inbox_dir?: unknown }).inbox_dir : undefined;
      // like the API: an empty folder stops watching; anything else must be a folder it may watch
      const cleared = sent === null || (typeof sent === "string" && !sent.trim()) ? { inbox_dir: null } : {};
      if (typeof patch.inbox_dir === "string" && patch.inbox_dir.trim()) {
        const problem = inboxDirProblem(patch.inbox_dir);
        if (problem) throw new HttpError(422, problem);
        patch.inbox_dir = patch.inbox_dir.trim();
      }
      if (typeof patch.model === "string") {
        patch.model = patch.model.trim();
        const problem = modelProblem(patch.model);
        if (problem) throw new HttpError(422, problem);
      }
      const before = db.state.settings.inbox_dir;
      db.state.settings = { ...db.state.settings, ...patch, models, ...cleared };
      if (db.state.settings.inbox_dir !== before) emit("folder.updated", { state: db.state.settings.inbox_dir ? "watching" : "off" });
      return db.state.settings;
    },
  ],
  [
    "POST",
    "/onboarding",
    ({ db, body }) => {
      const b = (body ?? {}) as { profile?: object };
      db.state.profile = { ...db.state.profile, ...(b.profile ?? {}), onboarded: true };
      return db.state.profile;
    },
  ],
  [
    "DELETE",
    "/data",
    ({ db, body, opts }) => {
      if ((body as { confirm?: unknown } | null)?.confirm !== "DELETE") throw new HttpError(422, "Type DELETE to confirm.");
      if (opts.staticDemo) throw new HttpError(409, "This online demo keeps nothing — reload the page to start over with Sam's letters.");
      if (db.state.health.demo) throw new HttpError(409, DEMO_DELETE_MESSAGE);
      const st = db.state;
      // a connected calendar loses Ordnung's events (and the app password) first, as the API does
      const calendarEventsRemoved = mockForgetCalendar(db);
      Object.assign(st, { parties: [], cases: [], documents: [], items: [], contracts: [], suggestions: [], drafts: [], activity: [], chat: [], tray: [], uploads: {}, proofs: [], calls: [], readings: {} });
      st.profile = { ...st.profile, name: "", address: "", email: "", phone: "", onboarded: false };
      return { removed: ["derived", "drafts", "files", "ordnung.db"], kept: [], calendar_events_removed: calendarEventsRemoved } satisfies DataDeleted;
    },
  ],

  // documents
  [
    "GET",
    "/documents",
    ({ db, query }) => {
      const q = query.get("q");
      let docs = q ? db.search(q) : [...db.liveDocuments()].sort((a, b) => ((a.received_date ?? a.doc_date ?? a.created_at) < (b.received_date ?? b.doc_date ?? b.created_at) ? 1 : -1));
      const f = (k: string) => query.get(k);
      if (f("kind")) docs = docs.filter((d) => d.kind === f("kind"));
      if (f("party_id")) docs = docs.filter((d) => d.party_id === f("party_id"));
      if (f("case_id")) docs = docs.filter((d) => d.case_id === f("case_id"));
      if (f("status")) docs = docs.filter((d) => d.status === f("status"));
      if (f("direction")) docs = docs.filter((d) => d.direction === f("direction"));
      if (f("private") === "true") docs = docs.filter((d) => d.ai_private);
      const offset = Number(f("offset") ?? 0);
      const limit = f("limit") ? Number(f("limit")) : docs.length;
      return docs.slice(offset, offset + limit);
    },
  ],
  [
    "POST",
    "/documents",
    (ctx) => {
      needsClaude(ctx);
      const { db, body } = ctx;
      const form = body instanceof FormData ? body : null;
      const files = (form?.getAll("files") ?? []).filter((f): f is File => f instanceof File);
      if (!files.length) throw new HttpError(422, "No files were uploaded.");
      const combine = form?.get("combine") === "true";
      const isPrivate = form?.get("private") === "true";
      const groups: File[][] = combine ? [files] : files.map((f) => [f]);
      const now = nowTs();
      const documents: Document[] = [];
      const jobs: Job[] = [];
      for (const group of groups) {
        const first = group[0]!;
        const id = newId("doc");
        const isImage = first.type.startsWith("image/");
        db.state.uploads[id] = { name: first.name, objectUrl: isImage ? URL.createObjectURL(first) : undefined };
        const d = makeDoc({
          id,
          filename: combine && group.length > 1 ? `${first.name.replace(/\.[^.]+$/, "")} (+${group.length - 1} pages)` : first.name,
          title: null,
          mime: combine ? "application/pdf" : first.type || (/\.eml$/i.test(first.name) ? "message/rfc822" : /\.txt$/i.test(first.name) ? "text/plain" : "application/octet-stream"),
          pages: group.length,
          status: isPrivate ? "processed" : "processing",
          kind: null,
          area: null,
          received_date: db.today,
          ai_private: isPrivate,
          ai_processed_at: null,
          processed_at: null,
          text_mode: isImage ? "vision" : "text",
          created_at: now,
          updated_at: now,
        });
        d.sha256 = sha(id + first.name);
        db.upsertDocument(d);
        documents.push(d);
        if (isPrivate) {
          db.log("document.private", `Stored “${first.name}” privately — not sent to Claude`, "document", id);
          continue;
        }
        const job = makeJob(id);
        jobs.push(job);
        void runJob(
          db,
          job,
          isImage,
          () => {
            const title = first.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
            db.upsertDocument({
              ...d,
              title: title.charAt(0).toUpperCase() + title.slice(1),
              status: "processed",
              kind: "other",
              area: "other",
              summary: "Demo mode: your file stays in this browser tab. In the installed app, Claude reads it and files every date, amount and deadline.",
              explanation: "This is the demo, so nothing was sent anywhere. Install Ordnung to have your own letters read and explained.",
              ai_processed_at: nowTs(),
              processed_at: nowTs(),
              updated_at: nowTs(),
            });
            db.log("document.processed", `Filed “${first.name}” (demo — not read by Claude)`, "document", id);
          },
          ctx.opts.latency ?? 1,
        );
      }
      return new Reply(201, { documents, jobs, duplicates: [], errors: [] } satisfies UploadResult);
    },
  ],
  ["GET", "/documents/:id", ({ db, params }) => documentDetail(db, params.id!)],
  // the watched folder: its state, and the person's answer for the letters waiting
  ["GET", "/folder", ({ db, opts }) => folderStatus(db, !opts.staticDemo)],
  [
    "POST",
    "/documents/held/read",
    (ctx) => {
      needsClaude(ctx);
      const { db } = ctx;
      const { docs, skipped } = answeredTogether(db, heldIds(ctx.body));
      const jobs: Job[] = [];
      for (const d of docs) {
        Object.assign(d, { ai_private: false, status: "processing", updated_at: nowTs() });
        db.log("document.released", `You let Claude read “${d.title ?? d.filename}”`, "document", d.id);
        const job = makeJob(d.id);
        jobs.push(job);
        void runJob(
          db,
          job,
          false,
          () =>
            Object.assign(d, {
              status: "processed",
              kind: "other",
              area: "other",
              summary: "Demo mode: in the installed app, Claude reads it now and files every date, amount and deadline.",
              ai_processed_at: nowTs(),
              processed_at: nowTs(),
              updated_at: nowTs(),
            }),
          ctx.opts.latency ?? 1,
        );
      }
      emit("folder.updated", { state: db.state.settings.inbox_dir ? "watching" : "off" });
      return { documents: docs, jobs, skipped } satisfies HeldResult;
    },
  ],
  [
    "POST",
    "/documents/held/keep-private",
    ({ db, body }) => {
      const { docs, skipped } = answeredTogether(db, heldIds(body));
      for (const d of docs) {
        Object.assign(d, { status: "processed", updated_at: nowTs() });
        db.log("document.kept_private", `You kept “${d.title ?? d.filename}” private · not sent to Claude`, "document", d.id);
        emit("document.updated", { doc_id: d.id });
      }
      emit("folder.updated", { state: db.state.settings.inbox_dir ? "watching" : "off" });
      return { documents: docs, jobs: [], skipped } satisfies HeldResult;
    },
  ],
  [
    "POST",
    "/documents/held/wait",
    ({ db, body }) => {
      // undo "Keep private": like the API, only a letter kept private from waiting, not read since —
      // an e-mail with its attachments kept private with it
      const chosen = new Map<string, Document>();
      const skipped: string[] = [];
      for (const id of new Set(heldIds(body))) {
        const d = db.document(id);
        if (!d || !wasKeptFromWaiting(db, d)) {
          skipped.push(id);
          continue;
        }
        chosen.set(d.id, d);
        for (const a of db.liveDocuments()) if (a.source === `email:${d.id}` && wasKeptFromWaiting(db, a) && !chosen.has(a.id)) chosen.set(a.id, a);
      }
      const documents = [...chosen.values()];
      for (const d of documents) {
        Object.assign(d, { status: "held", updated_at: nowTs() });
        db.log("document.waiting", `“${d.title ?? d.filename}” is back with the letters not read yet`, "document", d.id);
        emit("document.updated", { doc_id: d.id });
      }
      emit("folder.updated", { state: db.state.settings.inbox_dir ? "watching" : "off" });
      return { documents, jobs: [], skipped } satisfies HeldResult;
    },
  ],
  [
    "PATCH",
    "/documents/:id",
    ({ db, params, body }) => {
      const d = db.document(params.id!) ?? notFound();
      const patch = pick<Document>(body, DOC_PATCHABLE);
      const kindChanged = patch.kind !== undefined && patch.kind !== d.kind;
      Object.assign(d, patch, { updated_at: nowTs() });
      if (patch.received_date && d.id === "doc_gym_price") {
        recomputeGymPrice(db, patch.received_date);
        d.warnings = []; // the arrival day is known now: no "we don't know when it arrived"
        db.log("document.confirmed", "You confirmed when FitWell's letter arrived", "document", d.id);
        emit("item.updated", {});
      }
      if (kindChanged) {
        db.refileRuleItems(d);
        // the page keeps the dates and to-dos of the kind the letter was read as: say so where they are, not
        // only in the toast (review round 1: the verdict of a re-filed court order still said "Widerspruch")
        const seed = db.seedKind(d.id);
        d.warnings = d.warnings.filter((w) => !w.startsWith(DEMO_NOTE));
        if (seed && d.kind !== seed) d.warnings.push(refiledNote(seed, d.kind));
        emit("item.updated", {});
      }
      if (patch.received_date && d.id === "doc_parking") {
        recomputeParking(db, patch.received_date);
        d.status = "processed";
        d.warnings = [];
        db.log("document.confirmed", "You confirmed when the parking fine arrived", "document", d.id);
        emit("item.updated", {});
        emit("suggestions.updated", {});
      }
      if (patch.received_date && d.id === "doc_mahnbescheid") {
        recomputeCourtOrder(db, patch.received_date);
        d.warnings = [];
        db.log("document.received_date", `You confirmed that “${d.title}” was delivered on ${patch.received_date}`, "document", d.id);
        emit("item.updated", {});
      }
      if (patch.kind) db.log("document.kind", `You filed “${d.title ?? d.filename}” as “${patch.kind.replace(/_/g, " ")}”`, "document", d.id);
      return d;
    },
  ],
  [
    "DELETE",
    "/documents/:id",
    ({ db, params, query }) => {
      const d = db.document(params.id!) ?? notFound();
      const removed = db.state.items.filter((i) => i.doc_id === d.id && i.status === "open").length;
      d.deleted_at = nowTs();
      db.state.items = db.state.items.filter((i) => i.doc_id !== d.id);
      db.log("document.deleted", `Deleted “${d.title ?? d.filename}” and everything derived from it`, "document", d.id);
      return { id: d.id, purged: query.get("purge") === "true", removed_open_items: removed } satisfies DeleteResult;
    },
  ],
  [
    "POST",
    "/documents/:id/reprocess",
    (ctx) => {
      needsClaude(ctx);
      const d = ctx.db.document(ctx.params.id!) ?? notFound();
      const prev = { ...d };
      d.status = "processing";
      const job = makeJob(d.id, "reprocess");
      // the readings kept so far stay shown while the letter is read again
      const kept = readingsOf(ctx.db, prev);
      ctx.db.state.readings[d.id] = kept;
      void runJob(
        ctx.db,
        job,
        d.text_mode === "vision",
        () => {
          ctx.db.upsertDocument({ ...prev, updated_at: nowTs(), ai_processed_at: nowTs() });
          ctx.db.state.readings[d.id] = addReading(kept, { trigger: "read_again", started_at: job.created_at, job_id: job.id });
        },
        (ctx.opts.latency ?? 1) * 0.6,
      );
      return new Reply(202, job);
    },
  ],
  // "How it was read" (data/traces.ts)
  [
    "GET",
    "/documents/:id/trace",
    ({ db, params, query }) => {
      const d = db.document(params.id!) ?? notFound("This letter doesn't exist (any more).");
      return documentTrace(traceLedger(db), d, readingsOf(db, d), query.get("run")) ?? notFound(READING_GONE);
    },
  ],
  [
    "GET",
    "/documents/:id/trace/compare",
    ({ db, params, query }) => {
      const d = db.document(params.id!) ?? notFound("This letter doesn't exist (any more).");
      const ledger = traceLedger(db);
      const seeds = readingsOf(db, d);
      const head = documentTrace(ledger, d, seeds, query.get("head")) ?? notFound(READING_GONE);
      const headRun = head.run ?? notFound(NOTHING_TO_COMPARE);
      const baseId = query.get("base") ?? compareBase(head.runs, headRun)?.trace_id ?? notFound(NOTHING_TO_COMPARE);
      return compareReadings(documentTrace(ledger, d, seeds, baseId) ?? notFound(READING_GONE), head);
    },
  ],
  ["GET", "/traces", ({ db }) => exportTraces(traceLedger(db), Object.fromEntries(db.liveDocuments().map((d) => [d.id, readingsOf(db, d)])))],

  // items
  [
    "GET",
    "/items",
    ({ db, query }) => {
      let items = [...db.state.items];
      const f = (k: string) => query.get(k);
      if (f("status")) items = items.filter((i) => i.status === f("status"));
      if (f("kind")) items = items.filter((i) => i.kind === f("kind"));
      if (f("area")) items = items.filter((i) => i.area === f("area"));
      for (const k of ["party_id", "doc_id", "contract_id", "case_id"] as const) if (f(k)) items = items.filter((i) => i[k] === f(k));
      if (f("from")) items = items.filter((i) => !i.due_date || i.due_date >= f("from")!);
      if (f("to")) items = items.filter((i) => !i.due_date || i.due_date <= f("to")!);
      if (f("include_undated") !== "true" && (f("from") || f("to"))) items = items.filter((i) => i.due_date);
      items.sort((a, b) => ((a.send_by ?? a.due_date ?? "9999") < (b.send_by ?? b.due_date ?? "9999") ? -1 : 1));
      // like the API: each says whether it is set aside (not one to act on)
      const listed = items.slice(0, Number(f("limit") ?? 1000));
      const aside = new Map(setAside(db, listed).map((a) => [a.item_id, a]));
      return listed.map((i): ListedItem => ({ ...i, aside: aside.get(i.id) ?? null }));
    },
  ],
  [
    "POST",
    "/items",
    ({ db, body }) => {
      const added = db.addItem(newId("itm"), (body ?? {}) as ItemCreate);
      if ("status" in added) throw new HttpError(added.status, added.message);
      emit("item.updated", { item_id: added.item.id });
      return new Reply(201, added.item);
    },
  ],
  [
    "PATCH",
    "/items/:id",
    ({ db, params, body }) => {
      const it = db.state.items.find((i) => i.id === params.id) ?? notFound("Unknown to-do.");
      const patch = pick<Item>(body, ITEM_PATCHABLE);
      Object.assign(it, patch, { updated_at: nowTs(), user_modified: true });
      if (patch.due_date) it.due_date_source = "manual";
      if (patch.status === "done") it.completed_at = nowTs();
      if (patch.status === "open") it.completed_at = null;
      return it;
    },
  ],
  [
    "DELETE",
    "/items/:id",
    ({ db, params }) => {
      db.state.items = db.state.items.filter((i) => i.id !== params.id);
      return new Reply(204);
    },
  ],
  [
    "POST",
    "/items/:id/confirm",
    ({ db, params }) => {
      const it = db.state.items.find((i) => i.id === params.id) ?? notFound("Unknown to-do.");
      it.grounding = "user";
      it.user_modified = true;
      it.updated_at = nowTs();
      const d = it.doc_id ? db.document(it.doc_id) : null;
      if (d && d.status === "needs_review" && d.id !== "doc_scam") {
        const stillOpen = db.state.items.some((i) => i.doc_id === d.id && i.grounding === "unverified");
        if (!stillOpen && d.id !== "doc_parking") d.status = "processed";
      }
      return it;
    },
  ],

  [
    "POST",
    "/items/:id/girocode/confirm",
    ({ db, params, body }) => {
      const result = confirmMockGiroCode(db, params.id!, (body ?? {}) as TransferValues);
      if ("status" in result) throw new HttpError(result.status, result.message);
      emit("document.updated", { doc_id: result.docId });
      return result.code;
    },
  ],

  // contracts, parties, threads
  [
    "GET",
    "/contracts",
    ({ db, query }) =>
      db.state.contracts
        .filter((c) => (!query.get("status") || c.status === query.get("status")) && (!query.get("party_id") || c.party_id === query.get("party_id")))
        .map((c) => db.contractView(c)),
  ],
  [
    "PATCH",
    "/contracts/:id",
    ({ db, params, body }) => {
      const c = db.state.contracts.find((x) => x.id === params.id) ?? notFound("Unknown contract.");
      const notice = pick<Contract>(body, ["notice_value", "notice_unit", "notice_basis"]);
      // like the API: notice terms the person saves replace the letter's day of the month and statutory periods
      // unless they give them (an Undo sends them back)
      const cleared = Object.keys(notice).length ? { notice_day: null, notice_statutory: false } : {};
      const day = { ...cleared, ...pick<Contract>(body, ["notice_day", "notice_statutory"]) };
      const terms = { ...notice, ...day, ...pick<Contract>(body, ["notice_before_end"]) };
      Object.assign(c, pick<Contract>(body, ["name", "category", "status", "cost_amount", "cost_interval", "end_date", "customer_number"]), terms, { updated_at: nowTs() });
      // like the API: the rules engine works the dates out again from the new terms, and the terms
      // the person entered are theirs ("confirmed by the person": the card stops asking to check them)
      if (Object.keys(terms).length) {
        recomputeNotice(db, c);
        c.evidence = noticeEvidence(c);
      }
      return c;
    },
  ],
  ["GET", "/parties", ({ db }) => [...db.state.parties].sort((a, b) => a.name.localeCompare(b.name))],
  ["GET", "/parties/:id", ({ db, params }) => partyDetail(db, params.id!)],
  ["GET", "/cases/:id", ({ db, params }) => caseDetail(db, params.id!)],

  // views
  ["GET", "/timeline", ({ db, query }) => withAside(db, db.timeline(query.get("from"), query.get("to")))],
  ["GET", "/lanes", ({ db, query }) => db.lanes(query.get("from"), query.get("to"))],
  ["GET", "/dashboard", ({ db }) => db.dashboard()],
  ["GET", "/numbers", ({ db }) => mockNumbers(db)],
  ["GET", "/week", ({ db }) => mockWeek(db)],
  ["POST", "/week/done", ({ db }) => mockWeekDone(db)],
  ["POST", "/week/dismiss", ({ db }) => mockWeekDismiss(db)],

  // ideas & brief
  [
    "GET",
    "/suggestions",
    ({ db, query }) => {
      const st = query.get("status");
      const list = db.state.suggestions.filter((s) => (st ? s.status === st : s.status !== "expired"));
      const order = { new: 0, snoozed: 1, accepted: 2, done: 3, dismissed: 4, expired: 5 };
      return list.sort((a, b) => order[a.status] - order[b.status]).slice(0, Number(query.get("limit") ?? 100));
    },
  ],
  [
    "PATCH",
    "/suggestions/:id",
    ({ db, params, body }) => {
      const s = db.state.suggestions.find((x) => x.id === params.id) ?? notFound("Unknown Idea.");
      Object.assign(s, pick<Suggestion>(body, ["status", "snoozed_until"]), { updated_at: nowTs() });
      return s;
    },
  ],
  [
    "POST",
    "/suggestions/review",
    (ctx) => {
      needsClaude(ctx);
      ctx.db.log("review", "Weekly Ideas: nothing new (demo)");
      // like the API: the review runs in the background; its Ideas arrive with `suggestions.updated`
      setTimeout(() => emit("suggestions.updated", { reason: "review", created: 0 }), 400 * (ctx.opts.latency ?? 1));
      return new Reply(202, { started: true, running: true } satisfies ReviewStarted);
    },
  ],
  ["GET", "/brief", ({ db }) => ({ date: db.today, text: BRIEF_TEXT, source: "llm", generated_at: "2026-09-28T05:00:00Z" }) satisfies Brief],
  [
    "POST",
    "/brief",
    (ctx) => {
      needsClaude(ctx);
      return { date: ctx.db.today, text: BRIEF_TEXT, source: "llm", generated_at: nowTs() } satisfies Brief;
    },
  ],

  // ask
  ["POST", "/ask", (ctx) => askStream(ctx)],
  ["GET", "/chat/:thread", ({ db, params }) => db.state.chat.filter((m) => m.thread_id === params.thread)],

  // drafts
  ["GET", "/drafts", ({ db }) => [...db.state.drafts].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))],
  [
    "POST",
    "/drafts",
    ({ db, body }) => {
      const b = (body ?? {}) as DraftCreate;
      if (!b.kind) throw new HttpError(422, "Choose what kind of letter to write.");
      if (b.kind === "objection") {
        const d = b.doc_id ? db.document(b.doc_id) : null;
        const statutory = Boolean(d?.kind && STATUTORY_REMEDY[d.kind]);
        if (!statutory && (!d?.remedy || !["einspruch", "widerspruch"].includes(d.remedy.type)))
          throw new HttpError(422, "An objection letter needs a decision with instructions on how to object (Rechtsbehelfsbelehrung).");
        // an objection to a court order goes to the court, typed in when its sender isn't one
        // (compose.objection_to_typed_court, review round 3 of phase 2)
        if (d && needsTypedCourt(d, db.party(d.party_id)) && !mayBeCourt(b.details?.recipient)) throw new HttpError(422, COURT_OBJECTION_RECIPIENT);
      }
      const draft = composeDraft(db, b);
      db.state.drafts.unshift(draft);
      return new Reply(201, draft);
    },
  ],
  ["GET", "/drafts/:id", ({ db, params }) => db.state.drafts.find((d) => d.id === params.id) ?? notFound("Unknown letter.")],
  [
    "PATCH",
    "/drafts/:id",
    ({ db, params, body }) => {
      const d = db.state.drafts.find((x) => x.id === params.id) ?? notFound("Unknown letter.");
      // like the API: a sent letter stays as it went out
      if (d.status === "sent") throw new HttpError(409, "This letter was sent: its text stays as it went out, so the PDF and the Nachweis show what you sent. To write again, start a new letter.");
      Object.assign(d, pick<Draft>(body, ["subject", "body", "body_translation", "sender_block", "recipient_block", "place_date", "enclosures", "status"]), { updated_at: nowTs() });
      d.checks = checksFor(db, d);
      return d;
    },
  ],
  [
    "POST",
    "/drafts/:id/translate",
    (ctx) => {
      const d = ctx.db.state.drafts.find((x) => x.id === ctx.params.id) ?? notFound("Unknown letter.");
      needsClaude(ctx);
      // the demo backend only replays recordings, so it can't translate edits (like the real API)
      if (ctx.db.state.health.backend === "replay") throw new HttpError(409, DEMO_TRANSLATE_MESSAGE);
      d.body_translation = `Subject: ${d.subject}\n\n(English translation of the edited letter)\n\n${d.body}`;
      d.updated_at = nowTs();
      return d;
    },
  ],
  [
    "DELETE",
    "/drafts/:id",
    ({ db, params, query }) => {
      // like the API: the letter's proofs go with it, and their files too unless the person keeps them
      const files = new Set(db.state.proofs.filter((p) => p.draft_id === params.id && p.doc_id).map((p) => p.doc_id!));
      db.state.proofs = db.state.proofs.filter((p) => p.draft_id !== params.id);
      const inUse = new Set(db.state.proofs.map((p) => p.doc_id));
      if (query.get("keep_proof_files") === "true") {
        for (const d of db.state.documents) if (files.has(d.id) && d.source === "proof" && !inUse.has(d.id)) d.source = "upload";
      } else {
        db.state.documents = db.state.documents.filter((d) => !(files.has(d.id) && d.source === "proof" && !inUse.has(d.id)));
      }
      db.state.drafts = db.state.drafts.filter((d) => d.id !== params.id);
      return new Reply(204);
    },
  ],
  [
    "POST",
    "/drafts/:id/sent",
    ({ db, params, body }) => {
      const d = db.state.drafts.find((x) => x.id === params.id) ?? notFound("Unknown letter.");
      const b = (body ?? {}) as { channel?: string; date?: string; tracking_number?: string | null };
      const date = b.date ?? db.today;
      const tracking = checkTracking(b.tracking_number ?? "");
      if (tracking.state === "invalid") throw new HttpError(422, tracking.message);
      const channel = b.channel ?? "letter";
      // like the API: only a registered letter has a tracking number; another channel drops a stored one
      if (tracking.state === "valid" && channel !== "registered_letter") throw new HttpError(422, "Only a registered letter (Einschreiben) has a tracking number.");
      // like the API: a sending day after a recorded delivery is refused
      const delivered = deliveredBefore(db, d, date);
      if (delivered) throw new HttpError(422, delivered);
      d.status = "sent";
      d.sent_channel = channel;
      d.sent_at = `${date}T12:00:00Z`;
      // an emptied field ("") removes the number; none sent keeps it
      if (tracking.state === "valid") d.tracking_number = tracking.number;
      else if (channel !== "registered_letter" || typeof b.tracking_number === "string") d.tracking_number = null;
      d.updated_at = nowTs();
      d.checks = checksFor(db, d);
      const party = db.party(d.party_id);
      const followup = sentFollowup(d, date);
      const before = db.state.items.find((i) => i.id === followup.id);
      db.state.items = db.state.items.filter((i) => i.id !== followup.id); // marking it sent again replaces it
      db.state.items.push(
        makeItem({
          id: followup.id,
          kind: "task",
          title: `Check for a reply from ${party?.name ?? "the recipient"}`,
          description: d.subject,
          due_date: followup.due,
          party_id: d.party_id,
          case_id: d.case_id,
          contract_id: d.contract_id,
          doc_id: d.doc_id,
          origin: "draft",
          grounding: "user",
          // correcting how or when it went reopens nothing
          status: before && (before.status === "done" || before.status === "dismissed") ? before.status : "open",
          created_at: nowTs(),
          updated_at: nowTs(),
        }),
      );
      db.log("draft.sent", `You sent “${d.subject}”`, "draft", d.id);
      emit("item.updated", {});
      return d;
    },
  ],

  // proof of sending, waiting for, call notes (src/mocks/proof.ts)
  ...proofRoutes({
    fail: (status, message) => {
      throw new HttpError(status, message);
    },
    created: (body) => new Reply(201, body),
    empty: () => new Reply(204),
  }),

  // calendar, privacy, jobs
  [
    "POST",
    "/calendar/exported",
    ({ db }) => {
      db.state.lastCalendarExport = nowTs();
      const s = db.state.suggestions.find((x) => x.rule_id === "calendar_outdated" && x.status === "new");
      if (s) s.status = "done";
      db.log("calendar.exported", "Exported your dates to your calendar");
      return { last_calendar_export_at: db.state.lastCalendarExport };
    },
  ],
  // calendar sync (CalDAV): `?mock=1` pretends a calendar answers; the static demo can't reach one
  ["GET", "/calendar/sync", ({ db, opts }) => mockCalendarSyncStatus(db, opts.staticDemo)],
  [
    "GET",
    "/calendar/sync/preview",
    ({ db, query }) => {
      const mode = query.get("mode") ?? "discreet";
      if (mode !== "discreet" && mode !== "full") throw new HttpError(422, "Choose discreet or full.");
      return { mode, events: mockCalendarPreview(db, mode) };
    },
  ],
  ["POST", "/calendar/sync/discover", ({ body, opts }) => calendarRefusals(() => mockDiscoverCalendars(body as CalendarSyncFind, opts.staticDemo))],
  ["PUT", "/calendar/sync", ({ db, body, opts }) => calendarRefusals(() => mockConnectCalendar(db, body as CalendarSyncConnect, opts.staticDemo))],
  ["POST", "/calendar/sync/run", ({ db, opts }) => calendarRefusals(() => mockRunCalendarSync(db, opts.staticDemo))],
  [
    "POST",
    "/calendar/sync/disconnect",
    ({ db, body }) => mockDisconnectCalendar(db, (body as { remove_events?: boolean } | null)?.remove_events ?? true),
  ],
  // reminders outside the browser & the encrypted backup (a browser tab can do neither for real)
  ["GET", "/reminders/desktop", ({ db }) => mockDesktopReminders(db)],
  [
    "POST",
    "/reminders/desktop/test",
    ({ db, body, opts }) => {
      if (opts.staticDemo) throw new HttpError(403, DESKTOP_STATIC_MESSAGE, "static_demo");
      const mode = (body as { mode?: DesktopMode } | null)?.mode ?? "discreet";
      if (mode !== "discreet" && mode !== "full") throw new HttpError(422, "Choose discreet or full.");
      return { shown: true, tool: "notify-send", notification: mockNotification(db, mode) ?? SAMPLE_NOTIFICATION, detail: null } satisfies DesktopTestResult;
    },
  ],
  ["GET", "/backup", ({ db }) => mockBackupInfo(db)],
  [
    "POST",
    "/backup",
    ({ body, opts }) => {
      if (opts.staticDemo) throw new HttpError(403, BACKUP_STATIC_MESSAGE, "static_demo");
      const passphrase = (body as { passphrase?: unknown } | null)?.passphrase;
      if (typeof passphrase !== "string" || passphrase.length < 12) throw new HttpError(422, "Use a passphrase of at least 12 characters — a short sentence works well.");
      return new Response(mockBackupFile(), { status: 200, headers: { "Content-Type": "application/octet-stream" } });
    },
  ],
  ["GET", "/activity", ({ db, query }) => db.state.activity.slice(0, Number(query.get("limit") ?? 100))],
  ["GET", "/usage", () => USAGE],
  ["GET", "/rules", () => RULES],
  ["GET", "/jobs", () => [...activeJobs.values()]],

  // demo
  ["GET", "/demo/tour", ({ db }) => db.state.tour],
  ["PATCH", "/demo/tour", ({ db, body }) => (db.state.tour = { ...db.state.tour, ...(body as object) })],
  ["GET", "/demo/mail", ({ db }) => db.state.tray],
  ["GET", "/demo/questions", () => [...SUGGESTED_QUESTIONS]],
  [
    "POST",
    "/demo/mail",
    (ctx) => {
      const { db, body } = ctx;
      const id = (body as { id?: string } | null)?.id ?? "";
      const tray = db.state.tray.find((t) => t.id === id) ?? notFound("That letter is no longer in the tray.");
      const docId = db.trayDocFor(id)!;
      if (tray.opened && tray.doc_id) {
        const existing = db.document(tray.doc_id)!;
        return { document: existing, job: { ...makeJob(existing.id), status: "done", stage: "done", progress: 1 } } satisfies MailOpenResult;
      }
      tray.opened = true;
      tray.doc_id = docId;
      const now = nowTs();
      const placeholder = makeDoc({
        id: docId,
        filename: tray.filename,
        title: null,
        status: "processing",
        kind: null,
        area: null,
        source: "demo_mail",
        received_date: db.today,
        text_mode: tray.photo ? "vision" : "text",
        ai_processed_at: null,
        processed_at: null,
        created_at: now,
        updated_at: now,
      });
      db.upsertDocument(placeholder);
      const job = makeJob(docId);
      void runJob(db, job, tray.photo, () => db.applyTrayDocument(docId), ctx.opts.latency ?? 1);
      return { document: placeholder, job } satisfies MailOpenResult;
    },
  ],
];

/** Every mocked route as `[METHOD, "/path/:param"]` (a contract test matches them to `openapi.json`). */
export const MOCK_ROUTES: readonly (readonly [string, string])[] = routes.map(([method, pattern]) => [method, pattern] as const);

const compiled = routes.map(([method, pattern, handler]) => {
  const keys: string[] = [];
  const re = new RegExp(
    "^" +
      pattern.replace(/[.]/g, "\\.").replace(/:(\w+)/g, (_, k: string) => {
        keys.push(k);
        return "([^/]+)";
      }) +
      "$",
  );
  return { method, re, keys, handler };
});

// ------------------------------------------------------------------------------------------------
// Server
// ------------------------------------------------------------------------------------------------

const json = (status: number, body: unknown) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export interface MockServer {
  db: MockDb;
  /** Handle a `/api/...` request (path without the `/api` prefix). */
  handle(method: string, path: string, query: URLSearchParams, body: unknown, signal?: AbortSignal | null): Promise<Response>;
  /** Resolve asset paths (page images, PDFs, .ics) to data: URLs. */
  resolveAsset(path: string): string | null;
  /** Open all New-mail letters instantly (for `?mock=full`). */
  openAllMail(): void;
}

export function createMockServer(opts: MockOptions): MockServer {
  const db = new MockDb();
  const latency = opts.latency ?? 1;

  async function handle(method: string, path: string, query: URLSearchParams, body: unknown, signal?: AbortSignal | null): Promise<Response> {
    const m = method.toUpperCase();
    for (const r of compiled) {
      if (r.method !== m) continue;
      const match = r.re.exec(path);
      if (!match) continue;
      const params: Record<string, string> = {};
      r.keys.forEach((k, i) => (params[k] = decodeURIComponent(match[i + 1]!)));
      if (latency > 0) await sleep((m === "GET" ? 90 + Math.random() * 110 : 160 + Math.random() * 140) * latency);
      try {
        const out = await r.handler({ db, params, query, body, signal, opts });
        if (out instanceof Response) return out;
        if (out instanceof Reply) return json(out.status, out.body);
        return json(200, out ?? null);
      } catch (err) {
        if (err instanceof HttpError) return json(err.status, { detail: err.message, code: err.code });
        console.error("[mock] handler failed", m, path, err);
        return json(500, { detail: "The demo hit an unexpected error." });
      }
    }
    return json(404, { detail: `No mock for ${m} /api${path}` });
  }

  function resolveAsset(path: string): string | null {
    const proof = resolveProofAsset(db, path);
    if (proof) return proof;
    let m = /^\/documents\/([^/]+)\/pages\/(\d+)\.jpg$/.exec(path);
    const pageOf = (id: string, n: number) => {
      const letter = letterFor(decodeURIComponent(id));
      if (letter) return svgDataUrl(letter.pages[Math.min(n, letter.pages.length) - 1] ?? letter.pages[0]!);
      const up = db.state.uploads[decodeURIComponent(id)];
      if (up?.objectUrl) return up.objectUrl;
      const d = db.document(decodeURIComponent(id));
      return svgDataUrl(
        renderLetter({
          brand: { name: d?.filename ?? "Uploaded file", color: "#6b675f", mark: "none", tagline: "Stored on this computer" },
          pages: [{ subject: "Demo preview", blocks: ["In the installed app you would see the real page here.", "Your file never left this browser tab."] }],
        }).pages[0]!,
      );
    };
    if (m) return pageOf(m[1]!, Number(m[2]));
    m = /^\/documents\/([^/]+)\/(thumbnail\.jpg|file)$/.exec(path);
    if (m) return pageOf(m[1]!, 1);
    // the PDF and its print preview: the letter drawn as an image
    m = /^\/drafts\/([^/]+)\/(?:pdf|preview\.png)$/.exec(path);
    if (m) {
      const d = db.state.drafts.find((x) => x.id === decodeURIComponent(m![1]!));
      if (!d) return null;
      const sender = d.sender_block.split("\n");
      const r = renderLetter({
        brand: { name: sender[0] ?? "", color: "#1f1d1a", mark: "none", tagline: sender.slice(1, 3).join(" · ") },
        senderLine: sender.slice(0, 3).join(" · "),
        recipient: d.recipient_block.split("\n"),
        info: [["Datum", d.place_date.replace(/^.*?,\s*/, "")]],
        pages: [{ subject: d.subject, blocks: d.body.split(/\n{2,}/).map((p) => p.replace(/\n/g, " ")) }],
      });
      return svgDataUrl(r.pages[0]!);
    }
    m = /^\/items\/([^/]+)\.ics$/.exec(path);
    if (m) {
      const it = db.state.items.find((i) => i.id === decodeURIComponent(m![1]!));
      return it ? icsDataUrl(itemsToIcs([it], db.state.profile.reminder_days)) : null;
    }
    if (path === "/calendar.ics") return icsDataUrl(itemsToIcs(db.openItems(), db.state.profile.reminder_days));
    return null;
  }

  function openAllMail() {
    for (const t of db.state.tray) {
      if (t.opened) continue;
      const docId = db.trayDocFor(t.id)!;
      t.opened = true;
      t.doc_id = docId;
      db.applyTrayDocument(docId);
    }
  }

  return { db, handle, resolveAsset, openAllMail };
}
