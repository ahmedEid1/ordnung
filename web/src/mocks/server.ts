/**
 * Mock API: routes `/api/*` requests to handlers operating on the in-memory {@link MockDb}.
 * Mutations change the in-memory copy so the UI is fully interactive; long-running work
 * (uploads, New-mail letters) is simulated with realistic stage timings and SSE events.
 */
import { addDays, format, parseISO } from "date-fns";
import type {
  AppSettings,
  Brief,
  CaseDetail,
  ChatMessage,
  CitationRef,
  Contract,
  DataDeleted,
  DeleteResult,
  Document,
  DocumentDetail,
  Draft,
  DraftCreate,
  Health,
  Item,
  ItemAside,
  Job,
  LetterAdvice,
  MailOpenResult,
  PageInfo,
  Profile,
  PartyDetail,
  ReviewStarted,
  StreamEvent,
  Suggestion,
  SuggestionRef,
  TemplateDraftKind,
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

/** Mirrors compose.COURT_OBJECTION_RECIPIENT. */
const COURT_OBJECTION_RECIPIENT =
  "An objection to a court order goes to the court that issued it — sent to the claimant, it doesn't stop the order (§ 694, § 700 ZPO). This letter's sender isn't a court in Ordnung: type the court's name and address as the order and its yellow envelope show them (for a Mahnbescheid usually a central Mahngericht).";
import { SAM, sha } from "./data/constants";
import { TRAY_DOCUMENTS } from "./data/documents";
import { TRAY_ITEMS } from "./data/items";
import { PARTIES } from "./data/parties";
import { doc as makeDoc, item as makeItem } from "./data/helpers";
import { isOpenItem } from "@/features/document/verdict";
import { documentKindLabel } from "@/lib/copy";
import { DEMO_NOTE } from "./mode";

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

const DEMO_TRANSLATE_MESSAGE =
  "The demo replays recorded answers, so it can't translate your changes. Run `ordnung serve` (with Claude Code signed in) to re-translate letters you edited.";
const DEMO_DELETE_MESSAGE = "This is the demo, so there is nothing of yours to delete. To start over with Sam's original letters, run `ordnung demo --reset`.";
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
  };
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
        // The online demo's Ask page explains a question without a recording in a note of its own.
        const text = rec?.text ?? (ctx.opts.staticDemo ? "" : FALLBACK_ANSWER);
        const written = rec?.raw ?? text;
        for (const t of rec?.tools ?? []) {
          send({ type: "tool_use", name: t.name, input: t.input });
          await sleep(550 * speed, signal);
          send({ type: "tool_result", name: t.name, text: t.result });
          await sleep(200 * speed, signal);
        }
        if (!rec && !text) {
          send({ type: "done", text, note: null, thread_id: threadId, citations: [] });
          return;
        }
        send({ type: "text" });
        await sleep(Math.min(2500, 4 * written.length) * speed, signal);
        if (!rec) {
          send({ type: "done", text, note: null, thread_id: threadId, citations: [] });
          return;
        }
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
      const cleared = body && typeof body === "object" && (body as { inbox_dir?: unknown }).inbox_dir === null ? { inbox_dir: null } : {};
      return (db.state.settings = { ...db.state.settings, ...patch, models, ...cleared });
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
      Object.assign(st, { parties: [], cases: [], documents: [], items: [], contracts: [], suggestions: [], drafts: [], activity: [], chat: [], tray: [], uploads: {} });
      st.profile = { ...st.profile, name: "", address: "", email: "", phone: "", onboarded: false };
      return { removed: ["derived", "drafts", "files", "ordnung.db"], kept: [] } satisfies DataDeleted;
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
          mime: combine ? "application/pdf" : first.type || "application/octet-stream",
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
            db.log("document.processed", `Filed “${first.name}” (demo — not read by AI)`, "document", id);
          },
          ctx.opts.latency ?? 1,
        );
      }
      return new Reply(201, { documents, jobs, duplicates: [], errors: [] } satisfies UploadResult);
    },
  ],
  ["GET", "/documents/:id", ({ db, params }) => documentDetail(db, params.id!)],
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
      void runJob(ctx.db, job, d.text_mode === "vision", () => ctx.db.upsertDocument({ ...prev, updated_at: nowTs(), ai_processed_at: nowTs() }), (ctx.opts.latency ?? 1) * 0.6);
      return new Reply(202, job);
    },
  ],

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
      return items.slice(0, Number(f("limit") ?? 1000));
    },
  ],
  [
    "POST",
    "/items",
    ({ db, body }) => {
      const b = (body ?? {}) as Partial<Item>;
      if (!b.title || !b.kind) throw new HttpError(422, "A to-do needs a title and a kind.");
      const it = makeItem({ ...b, id: newId("itm"), kind: b.kind, title: b.title, origin: "manual", grounding: "user", due_date_source: b.due_date ? "manual" : "none", created_at: nowTs(), updated_at: nowTs() });
      db.state.items.push(it);
      emit("item.updated", { item_id: it.id });
      return new Reply(201, it);
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

  // contracts, parties, threads
  [
    "GET",
    "/contracts",
    ({ db, query }) =>
      db.state.contracts.filter((c) => (!query.get("status") || c.status === query.get("status")) && (!query.get("party_id") || c.party_id === query.get("party_id"))),
  ],
  [
    "PATCH",
    "/contracts/:id",
    ({ db, params, body }) => {
      const c = db.state.contracts.find((x) => x.id === params.id) ?? notFound("Unknown contract.");
      Object.assign(c, pick<Contract>(body, ["name", "category", "status", "cost_amount", "cost_interval", "notice_value", "notice_unit", "end_date", "customer_number"]), { updated_at: nowTs() });
      return c;
    },
  ],
  ["GET", "/parties", ({ db }) => [...db.state.parties].sort((a, b) => a.name.localeCompare(b.name))],
  ["GET", "/parties/:id", ({ db, params }) => partyDetail(db, params.id!)],
  ["GET", "/cases/:id", ({ db, params }) => caseDetail(db, params.id!)],

  // views
  ["GET", "/timeline", ({ db, query }) => db.timeline(query.get("from"), query.get("to"))],
  ["GET", "/lanes", ({ db, query }) => db.lanes(query.get("from"), query.get("to"))],
  ["GET", "/dashboard", ({ db }) => db.dashboard()],

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
      ctx.db.log("review", "Weekly review: no new Ideas (demo)");
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
    ({ db, params }) => {
      db.state.drafts = db.state.drafts.filter((d) => d.id !== params.id);
      return new Reply(204);
    },
  ],
  [
    "POST",
    "/drafts/:id/sent",
    ({ db, params, body }) => {
      const d = db.state.drafts.find((x) => x.id === params.id) ?? notFound("Unknown letter.");
      const b = (body ?? {}) as { channel?: string; date?: string };
      const date = b.date ?? db.today;
      d.status = "sent";
      d.sent_channel = b.channel ?? "letter";
      d.sent_at = `${date}T12:00:00Z`;
      d.updated_at = nowTs();
      d.checks = checksFor(db, d);
      const party = db.party(d.party_id);
      db.state.items.push(
        makeItem({
          id: newId("itm"),
          kind: "task",
          title: `Follow up: has ${party?.name ?? "the recipient"} confirmed your letter?`,
          description: d.subject,
          due_date: format(addDays(parseISO(date), d.kind === "data_access" ? 35 : 21), "yyyy-MM-dd"),
          party_id: d.party_id,
          case_id: d.case_id,
          contract_id: d.contract_id,
          origin: "draft",
          grounding: "user",
          created_at: nowTs(),
          updated_at: nowTs(),
        }),
      );
      db.log("draft.sent", `You sent “${d.subject}”`, "draft", d.id);
      emit("item.updated", {});
      return d;
    },
  ],

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
    m = /^\/drafts\/([^/]+)\/pdf$/.exec(path);
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
