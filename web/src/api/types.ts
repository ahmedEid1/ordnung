/**
 * API types — derived from the generated OpenAPI schema (`./schema.d.ts`), which is generated from
 * the FastAPI app (`make openapi`: `ordnung openapi > web/openapi.json` + `npm run gen:api`).
 * `src/ordnung/models.py` is the single source of truth; nothing here restates a field.
 *
 * Drift guards:
 * - the backend test `tests/test_openapi_contract.py` fails when `web/openapi.json` or
 *   `schema.d.ts` is stale;
 * - `EnumContract` below fails to compile when an `as const` array differs from the API's enum;
 * - `contract.test.ts` checks every endpoint call (path, method, query, body) and every mock
 *   handler (status, response shape) against `openapi.json`.
 *
 * Rules:
 * - Field names are snake_case exactly as the API returns them.
 * - Enums are also kept as `as const` arrays so tests and copy helpers can iterate every value
 *   (see `lib/copy.ts`). Never render these raw — map them through copy helpers.
 * - Dates are ISO `YYYY-MM-DD` strings; timestamps are ISO-8601 UTC strings.
 */
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

// ------------------------------------------------------------------------------------------------
// Helpers to address the generated schema
// ------------------------------------------------------------------------------------------------

export type ApiPath = keyof paths;
export type ApiMethod = "get" | "post" | "put" | "patch" | "delete";
type Operation<P extends ApiPath, M extends ApiMethod> = NonNullable<paths[P][M]>;

/** Paths that define method `M`. */
export type PathsWith<M extends ApiMethod> = {
  [P in ApiPath]: [Operation<P, M>] extends [never] ? never : P;
}[ApiPath];

type Success<R> = R extends { 200: infer S } ? S : R extends { 201: infer S } ? S : R extends { 202: infer S } ? S : R extends { 204: infer S } ? S : never;

/** The JSON body of the success response of `M P` (`void` for 204 / non-JSON responses). */
export type ApiResponse<P extends ApiPath, M extends ApiMethod> =
  Success<Operation<P, M>["responses"]> extends { content: { "application/json": infer J } } ? J : void;

/** The query parameters of `M P`. */
export type ApiQuery<P extends ApiPath, M extends ApiMethod> = Operation<P, M> extends { parameters: { query?: infer Q } }
  ? [Q] extends [never | undefined]
    ? never
    : NonNullable<Q>
  : never;

/** The JSON request body of `M P`. */
export type ApiBody<P extends ApiPath, M extends ApiMethod> = Operation<P, M> extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

// ------------------------------------------------------------------------------------------------
// Enums (arrays for iteration; their element types must equal the API's — see EnumContract)
// ------------------------------------------------------------------------------------------------

export const DOCUMENT_KINDS = [
  "tax_assessment",
  "tax_letter",
  "authority_letter",
  "residence_permit",
  "social_insurance",
  "health_insurance",
  "invoice",
  "dunning",
  "contract",
  "contract_change",
  "price_increase",
  "cancellation_confirmation",
  "payslip",
  "bank_letter",
  "insurance",
  "rent_lease",
  "utility_bill",
  "university",
  "employment",
  "appointment",
  "fine",
  "receipt",
  "identity_document",
  "broadcasting_fee",
  "certificate",
  "personal",
  "other",
  // high-stakes letters: Ordnung's rules assign these from the reading (the person may too)
  "court_payment_order",
  "enforcement_order",
  "dismissal",
  "landlord_notice",
  "rent_increase",
  "operating_costs",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];

/** Letters whose deadlines the rules engine handles specially (they carry a "get advice" card). */
export const HIGH_STAKES_KINDS = [
  "court_payment_order",
  "enforcement_order",
  "dismissal",
  "landlord_notice",
  "rent_increase",
  "operating_costs",
] as const satisfies readonly DocumentKind[];
export type HighStakesKind = (typeof HIGH_STAKES_KINDS)[number];

/** `held`: from the watched folder (or attached to an e-mail from it), waiting for "Read these". */
export const DOCUMENT_STATUSES = ["queued", "processing", "processed", "needs_review", "failed", "held"] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

export const DIRECTIONS = ["incoming", "outgoing", "note"] as const;
export type Direction = (typeof DIRECTIONS)[number];

export const PARTY_KINDS = [
  "authority",
  "tax_office",
  "immigration_office",
  "health_insurer",
  "insurer",
  "bank",
  "landlord",
  "employer",
  "university",
  "utility",
  "telecom",
  "retailer",
  "doctor",
  "gym",
  "public_broadcaster",
  "transport",
  "person",
  "company",
  "other",
] as const;
export type PartyKind = (typeof PARTY_KINDS)[number];

export const ITEM_KINDS = ["deadline", "payment", "appointment", "task", "expiry", "reminder", "milestone"] as const;
export type ItemKind = (typeof ITEM_KINDS)[number];

export const ITEM_STATUSES = ["open", "done", "dismissed", "snoozed", "missed"] as const;
export type ItemStatus = (typeof ITEM_STATUSES)[number];

export const PRIORITIES = ["low", "normal", "high", "critical"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const AREAS = [
  "home",
  "work",
  "study",
  "health",
  "money",
  "residence",
  "tax",
  "mobility",
  "insurance",
  "leisure",
  "family",
  "other",
] as const;
export type Area = (typeof AREAS)[number];

export const SUGGESTION_KINDS = [
  "deadline",
  "saving",
  "risk",
  "followup",
  "hygiene",
  "tax",
  "opportunity",
  "scam",
  "info",
] as const;
export type SuggestionKind = (typeof SUGGESTION_KINDS)[number];

export const SUGGESTION_STATUSES = ["new", "accepted", "dismissed", "snoozed", "done", "expired"] as const;
export type SuggestionStatus = (typeof SUGGESTION_STATUSES)[number];

export const DRAFT_KINDS = [
  "cancellation",
  "objection",
  "general_reply",
  "withdrawal",
  "extension_request",
  "payment_plan",
  "defect_notice",
  "data_access",
  "receipts_inspection",
  "deposit_return",
  "address_change",
] as const;
export type DraftKind = (typeof DRAFT_KINDS)[number];
/** Letters written entirely from fixed templates, filled with {@link LetterDetails}. */
export type TemplateDraftKind = Exclude<DraftKind, "cancellation" | "objection" | "general_reply">;

export const CONTRACT_CATEGORIES = [
  "mobile",
  "internet",
  "energy",
  "gas",
  "insurance",
  "gym",
  "streaming",
  "software",
  "rent",
  "employment",
  "transport",
  "bank",
  "membership",
  "other",
] as const;
export type ContractCategory = (typeof CONTRACT_CATEGORIES)[number];

export const COST_INTERVALS = ["monthly", "quarterly", "yearly", "once"] as const;
export type CostInterval = (typeof COST_INTERVALS)[number];

export const NOTICE_UNITS = ["days", "weeks", "months"] as const;
export type NoticeUnit = (typeof NOTICE_UNITS)[number];

export const NOTICE_BASES = ["end_of_term", "any_time", "end_of_month"] as const;
export type NoticeBasis = (typeof NOTICE_BASES)[number];

export const PERIOD_UNITS = ["days", "weeks", "months", "years", "business_days", "werktage"] as const;
export type PeriodUnit = (typeof PERIOD_UNITS)[number];

export const CONFIDENCES = ["high", "medium", "low"] as const;
export type Confidence = (typeof CONFIDENCES)[number];

export const GROUNDINGS = ["verified", "model_read", "unverified", "user"] as const;
export type Grounding = (typeof GROUNDINGS)[number];

export const CONTRACT_REGIMES = [
  "bgb309_new",
  "bgb309_old",
  "tkg56",
  "vvg11",
  "sgbv175",
  "stromgvv20",
  "rent573c",
  "employment622",
  "bgb675h",
  "as_written",
] as const;
export type ContractRegime = (typeof CONTRACT_REGIMES)[number];

export const REMEDY_TYPES = ["einspruch", "widerspruch", "klage", "none", "unclear"] as const;
export type RemedyType = (typeof REMEDY_TYPES)[number];

export const DATE_NATURES = ["objection", "payment", "declaration", "notice", "appointment", "other"] as const;
export type DateNature = (typeof DATE_NATURES)[number];

export const CONTRACT_STATUSES = ["active", "cancelled", "ended"] as const;
export type ContractStatus = (typeof CONTRACT_STATUSES)[number];

export const DRAFT_STATUSES = ["draft", "final", "sent"] as const;
export type DraftStatus = (typeof DRAFT_STATUSES)[number];

export const SEND_CHANNELS = [
  "online_button",
  "email",
  "fax",
  "letter",
  "registered_letter",
  "in_person",
  "portal",
] as const;
export type SendChannelKind = (typeof SEND_CHANNELS)[number];

/** What a proof of a sent letter is (`drafts.proof.PROOF_KINDS` says what each one shows). */
export const PROOF_KINDS = [
  "posting_receipt",
  "delivery_record",
  "return_receipt",
  "fax_report",
  "sent_email",
  "cancel_confirmation",
  "other",
] as const;
export type ProofKind = (typeof PROOF_KINDS)[number];

/** Where a "Waiting for" entry comes from, and how it stands (`secretary.waiting`). */
export const WAITING_SOURCES = ["letter", "money", "call"] as const;
export type WaitingSource = (typeof WAITING_SOURCES)[number];
export const WAITING_STATUSES = ["waiting", "overdue", "answered", "closed"] as const;
export type WaitingStatus = (typeof WAITING_STATUSES)[number];

export const SEND_FORMS = ["text_form", "written_form", "any"] as const;
export type SendForm = (typeof SEND_FORMS)[number];

export const TIMELINE_TYPES = [
  "document",
  "deadline",
  "payment",
  "appointment",
  "task",
  "expiry",
  "contract",
  "draft",
  "milestone",
  "reminder",
] as const;
export type TimelineType = (typeof TIMELINE_TYPES)[number];

export const AREA_STATUSES = ["ok", "attention", "urgent"] as const;
export type AreaStatusLevel = (typeof AREA_STATUSES)[number];

export const LANE_BAR_KINDS = ["contract", "notice_window", "validity", "period", "event"] as const;
export type LaneBarKind = (typeof LANE_BAR_KINDS)[number];

export const LANE_BAR_STATUSES = ["ok", "attention", "urgent", "past"] as const;
export type LaneBarStatus = (typeof LANE_BAR_STATUSES)[number];

export const MARKER_KINDS = [
  "deadline",
  "send_by",
  "cancel_by",
  "renewal",
  "expiry",
  "payment",
  "appointment",
  "other",
] as const;
export type MarkerKind = (typeof MARKER_KINDS)[number];

export const JOB_KINDS = ["ingest", "reprocess", "review"] as const;
export type JobKind = (typeof JOB_KINDS)[number];

export const JOB_STATUSES = ["queued", "running", "waiting", "done", "failed"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

/** Pipeline stages reported by `job.progress` (SPEC §8). */
export const JOB_STAGES = [
  "intake",
  "text",
  "transcribe",
  "extract",
  "verify",
  "compute",
  "link",
  "plan",
  "done",
] as const;
export type JobStage = (typeof JOB_STAGES)[number];

export type ItemOrigin = Schemas["Item"]["origin"];
export type DueDateSource = Schemas["Item"]["due_date_source"];
export type TextSource = Schemas["PageInfo"]["text_source"];
export type RefType = Schemas["SuggestionRef"]["type"];

/** Who is asking (`Health.client`): the browser on the computer Ordnung runs on, or a phone paired over the home network. */
export const CLIENT_KINDS = ["computer", "phone"] as const;
export type ClientKind = (typeof CLIENT_KINDS)[number];

/** Why phone access is on but no phone can reach it (`PhoneStatus.problem.code`). */
export const PHONE_PROBLEM_CODES = ["no_network", "address_gone", "other_network", "port_busy", "failed"] as const;
export type PhoneProblemCode = (typeof PHONE_PROBLEM_CODES)[number];

/** What the computer must know at once about phone access (`PhoneStatus.notice.code`, shown in the danger tone). */
export const PHONE_NOTICE_CODES = ["pairing_stopped", "code_reused", "token_reuse"] as const;
export type PhoneNoticeCode = (typeof PHONE_NOTICE_CODES)[number];

/**
 * The `code` of every phone-access refusal (`{detail, code}`, `ApiError.code`): the phone listener's gate before
 * routing and the phone routes after it. Error bodies aren't in the schema, so this mirrors
 * `ordnung.phone.PhoneErrorCode` by hand (`ERROR_STATUS` there gives each one's status).
 */
export const PHONE_ERROR_CODES = [
  "misdirected",
  "wrong_host",
  "bad_path",
  "unexpected_body",
  "length_required",
  "too_large",
  "not_home_network",
  "cross_site",
  "phone_not_paired",
  "computer_only",
  "too_many",
  "unavailable",
  "not_set_up",
  "no_network",
  "port_busy",
  "not_listening",
  "too_many_phones",
  "code_used",
  "wrong_code",
  "invalid",
  "not_phone",
] as const;
export type PhoneErrorCode = (typeof PHONE_ERROR_CODES)[number];

/** Why hand-off sync is paused or needs the person (`SyncStatus.problem.code`; the web shows its words, never the code). */
export const SYNC_PROBLEM_CODES = [
  "folder_missing",
  "folder_empty",
  "folder_other",
  "folder_full",
  "folder_unreachable",
  "online_only",
  "two_setups",
  "passphrase_needed",
  "keyring_unavailable",
  "keyring_locked",
  "newer_ordnung",
  "arrival_stalled",
  "not_received",
  "pull_unfinished",
  "no_space",
  "damaged",
  "local_damaged",
  "copied_folder",
  "local_rollback",
  "save_failing",
  "forgotten",
] as const;
export type SyncProblemCode = (typeof SYNC_PROBLEM_CODES)[number];

/** What the person can do about a sync problem (`SyncProblem.actions`, the main one first). */
export const SYNC_PROBLEM_ACTIONS = ["passphrase", "choose_folder", "refill", "same_computer", "new_computer", "keep_as_is", "abandon"] as const;
export type SyncProblemAction = (typeof SYNC_PROBLEM_ACTIONS)[number];

/**
 * The `code` of every hand-off sync refusal (`{detail, code}`, `ApiError.code`): its routes, and the gate's
 * `standby` for any write while another computer is in use. Error bodies aren't in the schema, so this mirrors
 * `ordnung.sync.SyncErrorKind` by hand (`ERROR_STATUS` there gives each one's status; a contract test compares).
 */
export const SYNC_ERROR_CODES = [
  "unavailable",
  "not_connected",
  "already_connected",
  "folder",
  "name",
  "passphrase",
  "wrong_passphrase",
  "newer_ordnung",
  "full",
  "folder_problem",
  "pull_unfinished",
  "passphrase_needed",
  "no_space",
  "no_choice",
  "not_arrived",
  "standby",
  "in_use",
  "not_received",
  "not_needed",
  "not_found",
] as const;
export type SyncErrorCode = (typeof SYNC_ERROR_CODES)[number];

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Same<A, B> = Equal<A, B> extends true ? true : ["enum differs from the API", A, B];

/**
 * Compile-time guard: every enum array above equals the API's enum. When the backend adds or
 * removes a value, `tsc` fails here — update the array (and the copy in `lib/copy.ts`).
 */
export type EnumContract = [
  Same<DocumentKind, NonNullable<Schemas["Document"]["kind"]>>,
  Same<DocumentStatus, Schemas["Document"]["status"]>,
  Same<Direction, Schemas["Document"]["direction"]>,
  Same<PartyKind, Schemas["Party"]["kind"]>,
  Same<ItemKind, Schemas["Item"]["kind"]>,
  Same<ItemStatus, Schemas["Item"]["status"]>,
  Same<Priority, Schemas["Item"]["priority"]>,
  Same<Area, Schemas["Item"]["area"]>,
  Same<SuggestionKind, Schemas["Suggestion"]["kind"]>,
  Same<SuggestionStatus, Schemas["Suggestion"]["status"]>,
  Same<DraftKind, Schemas["Draft"]["kind"]>,
  Same<HighStakesKind, Schemas["LetterAdvice"]["kind"]>,
  Same<ContractCategory, Schemas["Contract"]["category"]>,
  Same<CostInterval, NonNullable<Schemas["Contract"]["cost_interval"]>>,
  Same<NoticeUnit, NonNullable<Schemas["Contract"]["notice_unit"]>>,
  Same<NoticeBasis, NonNullable<Schemas["Contract"]["notice_basis"]>>,
  Same<PeriodUnit, NonNullable<Schemas["DateSpec"]["unit"]>>,
  Same<Confidence, Schemas["ComputationReceipt"]["confidence"]>,
  Same<Grounding, Schemas["Evidence"]["grounding"]>,
  Same<ContractRegime, Schemas["ContractComputation"]["regime"]>,
  Same<RemedyType, Schemas["Remedy"]["type"]>,
  Same<DateNature, Schemas["DateSpec"]["nature"]>,
  Same<ContractStatus, Schemas["Contract"]["status"]>,
  Same<DraftStatus, Schemas["Draft"]["status"]>,
  Same<SendChannelKind, Schemas["SendChannel"]["channel"]>,
  Same<SendForm, Schemas["SendGuidance"]["form"]>,
  Same<ProofKind, Schemas["Proof"]["kind"]>,
  Same<WaitingSource, Schemas["WaitingEntry"]["source"]>,
  Same<WaitingStatus, Schemas["WaitingEntry"]["status"]>,
  Same<TimelineType, Schemas["TimelineEntry"]["type"]>,
  Same<AreaStatusLevel, Schemas["AreaStatus"]["status"]>,
  Same<LaneBarKind, Schemas["LaneBar"]["kind"]>,
  Same<LaneBarStatus, Schemas["LaneBar"]["status"]>,
  Same<MarkerKind, Schemas["TimelineMarker"]["kind"]>,
  Same<JobKind, Schemas["Job"]["kind"]>,
  Same<JobStatus, Schemas["Job"]["status"]>,
  Same<JobStage, Schemas["JobProgressEvent"]["stage"]>,
  Same<ClientKind, Schemas["Health"]["client"]>,
  Same<PhoneProblemCode, Schemas["PhoneProblem"]["code"]>,
  Same<PhoneNoticeCode, Schemas["PhoneNotice"]["code"]>,
  Same<SyncProblemCode, Schemas["SyncProblem"]["code"]>,
  Same<SyncProblemAction, Schemas["SyncProblem"]["actions"][number]>,
];
// Referencing the tuple makes every entry resolve (an entry that isn't `true` is a compile error).
const enumContract: EnumContract extends true[] ? true : never = true;
void enumContract;

// ------------------------------------------------------------------------------------------------
// Evidence & dates
// ------------------------------------------------------------------------------------------------

/** Highlight rectangle in relative coordinates (0..1) on a rendered page image. */
export type Box = Schemas["Box"];
/** Where a fact came from (page, verbatim quote, highlight boxes). */
export type Evidence = Schemas["Evidence"];
/** What a document *says* about a date; the rules engine turns it into a concrete date. */
export type DateSpec = Schemas["DateSpec"];
export type ComputationStep = Schemas["ComputationStep"];
/** "Why this date?" — the rules engine's receipt for a computed due date. */
export type ComputationReceipt = Schemas["ComputationReceipt"];
export type Recurrence = Schemas["Recurrence-Output"];

// ------------------------------------------------------------------------------------------------
// Core entities
// ------------------------------------------------------------------------------------------------

export type Identifier = Schemas["Identifier"];
/** A person or organisation ("People & organisations" in the UI). */
export type Party = Schemas["Party"];
/** A thread of related letters ("Threads" in the UI). */
export type Case = Schemas["Case"];
export type Remedy = Schemas["Remedy"];
export type PaymentDetails = Schemas["PaymentDetails"];
export type KeyFact = Schemas["KeyFact"];
/** A letter / file ("Letters" in the Inbox). `deleted_at` is set while it is in the trash. */
export type Document = Schemas["Document"];
export type ContractComputation = Schemas["ContractComputation"];
export type Contract = Schemas["Contract"];
/** A to-do or date ("To-dos & dates" in the UI). */
export type Item = Schemas["Item"];
/** A to-do as `GET /api/items` lists it: with `aside`, why it is not one to act on (null: it is). */
export type ListedItem = Schemas["ListedItem"];
export type SuggestionRef = Schemas["SuggestionRef"];
export type SuggestionAction = Schemas["SuggestionAction"];
/** An "Idea" from the secretary. */
export type Suggestion = Schemas["Suggestion"];
export type SendChannel = Schemas["SendChannel"];
export type SendGuidance = Schemas["SendGuidance"];
export type DraftCheck = Schemas["DraftCheck"];
/** The facts a template letter needs (`POST /api/drafts` `details`); every field is optional here. */
export type LetterDetails = Schemas["LetterDetails"];
/** A letter Ordnung drafted for the user ("Letters"). */
export type Draft = Schemas["Draft"];
/** One piece of proof of a sent letter; its file is a private outgoing document (never read by Claude). */
export type Proof = Schemas["Proof"];
/** A phone call the person noted (Gesprächsnotiz); a promise with a day is waited for. */
export type CallNote = Schemas["CallNote"];
export type Activity = Schemas["Activity"];
export type LLMCallRecord = Schemas["LLMCallRecord"];
export type Job = Schemas["Job"];
export type ChatMessage = Schemas["ThreadMessage"];

// ------------------------------------------------------------------------------------------------
// Profile & settings
// ------------------------------------------------------------------------------------------------

export type Profile = Schemas["Profile"];
export type ModelSettings = Schemas["ModelSettings"];
export type AppSettings = Schemas["AppSettings"];

// ------------------------------------------------------------------------------------------------
// View models
// ------------------------------------------------------------------------------------------------

export type RefLink = Schemas["RefLink"];
export type TimelineEntry = Schemas["TimelineEntry"];
export type AreaStatus = Schemas["AreaStatus"];
export type MoneySummary = Schemas["MoneySummary"];
export type DashboardStats = Schemas["DashboardStats"];
export type Dashboard = Schemas["Dashboard"];
export type PageInfo = Schemas["PageInfo"];
export type DocumentDetail = Schemas["DocumentDetail"];
/** A GiroCode (EPC QR) for one payment — or why there is none — worked out on read by the server. */
export type GiroCode = DocumentDetail["girocodes"][number];
export type GiroCodeReady = Schemas["GiroCodeReady"];
export type GiroCodeBlocked = Schemas["GiroCodeBlocked"];
/** The transfer details a GiroCode carries, as the person compares them with the letter. */
export type TransferValues = Schemas["TransferValues"];
/** The "get advice" card of a high-stakes letter (court order, dismissal, tenancy …), worked out on read. */
export type LetterAdvice = Schemas["LetterAdvice"];
export type AdviceFact = Schemas["AdviceFact"];
export type HelpLink = Schemas["HelpLink"];
export type PartyDetail = Schemas["PartyDetail"];
/** An open to-do of a party that is not one to act on (replaced by a reminder, history, scam signs). */
export type ItemAside = Schemas["ItemAside"];
export type CaseDetail = Schemas["CaseDetail"];
/** Model use for one purpose (calls, cache hits, errors, tokens, cost). */
export type PurposeUsage = Schemas["PurposeUsage"];
/** @deprecated use {@link PurposeUsage} */
export type UsagePurposeStats = PurposeUsage;
export type UsageStats = Schemas["UsageStats"];
/** "How it was read": a letter's reading shown (`run`), its steps (`spans`) and every kept reading (`runs`). */
export type DocumentTrace = Schemas["DocumentTrace"];
/** One reading of a letter, summed up (when, how long, model calls, tokens, cost, how it ended). */
export type TraceRun = Schemas["TraceRun"];
/** One step of a reading, depth-first in display order; `attributes` follow `ordnung/trace/facts.py`. */
export type TraceSpan = Schemas["TraceSpan"];
export type SpanKind = Schemas["TraceSpan"]["kind"];
/** One thing two readings decided differently (a date, a quote's grounding, a model call's outcome …). */
export type TraceChange = Schemas["TraceChange"];
export type TraceComparison = Schemas["TraceComparison"];
export type TraceExport = Schemas["TraceExport"];
export type ClaudeStatus = Schemas["ClaudeStatus"];
/** One `ordnung doctor` check (listed by `GET /api/health?probe=1`). */
export type DoctorCheck = Schemas["DoctorCheck"];
/**
 * `GET /api/health` for the signed-in app. `today` is the app's "today" (ISO date) — always use
 * it, never the browser clock; `rules_last_checked` is the "Based on the law as of" date. `client` says who asked:
 * this computer's browser, or a paired phone (which gets no data folder, Claude path or checks) —
 * `usePhoneCompanion()` in `features/phone/client.ts`.
 */
export type Health = Schemas["Health"];
/** `GET /api/health` without the session token (the endpoint client turns it into a 401 error). */
export type PublicHealth = Schemas["PublicHealth"];
/** An entry of the legal rules catalog ("How dates are computed"). */
export type RuleInfo = Schemas["RuleInfo"];
/**
 * A date on the life lanes. The API sends each one's life `area` and the to-do or contract it
 * stands for (`ref`); both are optional here because the web app also builds lanes itself
 * (`contractLanes`).
 */
export type TimelineMarker = Omit<Schemas["TimelineMarker"], "area" | "ref"> & { area?: Area | null; ref?: RefLink | null };
/**
 * A bar on the life lanes. `open_end` marks a bar with no end date (an open-ended contract, or
 * "cancellable any time" after a minimum term): its `end` is only where the chart stops drawing
 * it, so it is never shown as a date. `area` is the life area of what the bar stands for (the
 * Contracts lane holds contracts of every area). The API sends both; they are optional here
 * because the web app also builds lanes itself (`contractLanes`).
 */
export type LaneBar = Omit<Schemas["LaneBar"], "area" | "open_end" | "markers"> & {
  area?: Area | null;
  open_end?: boolean;
  markers: TimelineMarker[];
};
/** A "life lane" (Residence permit, Contracts, Tax, Study, …) on the year-ahead timeline. */
export type Lane = Omit<Schemas["Lane"], "bars" | "markers"> & { bars: LaneBar[]; markers: TimelineMarker[] };
export type SearchHit = Schemas["SearchHit"];
export type TourState = Schemas["TourState"];
/** A letter waiting in the demo's "New mail" tray; `received_date` is the day it arrived (the postmark). */
export type MailTrayItem = Schemas["MailTrayItem"];
/** `GET /api/numbers`: About you, identity documents, a call sheet per organisation, open cases. */
export type MyNumbers = Schemas["MyNumbers"];
/** One number, sorted by whose it is, with its check-digit test and the letter that shows it. */
export type MyNumber = Schemas["MyNumber"];
export type IdentityDocument = Schemas["IdentityDocument"];
export type CallSheet = Schemas["CallSheet"];
export type OpenCase = Schemas["OpenCase"];
export type LetterRef = Schemas["LetterRef"];
/** `GET /api/week`: the weekly session's seven steps and "All clear until …". */
export type WeeklySession = Schemas["WeeklySession"];
export type WeekStep = Schemas["WeekStep"];
export type WeekEntry = Schemas["WeekEntry"];
/** An e-mail's attachment and what became of it (`DocumentDetail.attachments`). */
export type EmailAttachment = Schemas["EmailAttachment"];
export type AttachmentOutcome = EmailAttachment["outcome"];
/** `GET /api/folder`: the watched folder, its state, the letters waiting and the last files it brought in. */
export type FolderStatus = Schemas["FolderStatus"];
export type FolderState = FolderStatus["state"];
export type FolderPickup = Schemas["FolderPickup"];
/** A letter's tracking number as the server read it (S10 check digit, or twelve digits unchecked). */
export type TrackingInfo = Schemas["TrackingInfo"];
/** A proof with its file and, in code-written words, what it shows and what it does not. */
export type ProofEntry = Schemas["ProofEntry"];
export type ProofEvent = Schemas["ProofEvent"];
/** `GET /api/drafts/{id}/proof`: tracking number, proofs, timeline, what's missing, what it waits for. */
export type ProofOverview = Schemas["ProofOverview"];
/** A sent letter a document is proof of (`DocumentDetail.proof_of`). */
export type ProofLink = Schemas["ProofLink"];
/** Something the person is owed — a reply, money or a callback ("Waiting for"). */
export type WaitingEntry = Schemas["WaitingEntry"];

// ------------------------------------------------------------------------------------------------
// Responses that are not models.py view models (defined next to their routes)
// ------------------------------------------------------------------------------------------------

/** `POST /api/documents` (201): queued letters with their jobs, duplicates (ids) and rejected files. */
export type UploadResult = Schemas["UploadResult"];
export type UploadError = Schemas["UploadError"];
/** `DELETE /api/documents/{id}`. */
export type DeleteResult = Schemas["DeleteResult"];
/** `POST /api/demo/mail`. */
export type MailOpenResult = Schemas["MailOpenResult"];
/** `GET /api/brief` / `POST /api/brief`. */
export type Brief = Schemas["Brief"];
/** `POST /api/calendar/exported`. */
export type CalendarExportResult = Schemas["CalendarExportResult"];
/** `POST /api/suggestions/review` (202): the review runs in the background. */
export type ReviewStarted = Schemas["ReviewStarted"];
/** `DELETE /api/data` ("Delete everything"): what was removed, and entries Ordnung left alone. */
export type DataDeleted = Schemas["DataDeleted"];
/** `POST /api/documents/held/read` · `…/keep-private`: the letters answered for, jobs queued, ids no longer waiting. */
export type HeldResult = Schemas["HeldResult"];
/** `GET /api/reminders/desktop`: the notification tool, today's text in each mode, start at login. */
export type DesktopReminders = Schemas["DesktopReminders"];
export type NotificationText = Schemas["NotificationText"];
/** Whether `ordnung autostart` starts Ordnung at login, and for which data folder. */
export type AutostartInfo = Schemas["AutostartInfo"];
/** `POST /api/reminders/desktop/test`. */
export type DesktopTestResult = Schemas["DesktopTestResult"];
/** The two modes a desktop notification can be shown in (the setting also has `off`). */
export type DesktopMode = NonNullable<Schemas["DesktopTestRequest"]["mode"]>;
/** `GET /api/backup`: what an encrypted backup made now would hold. */
export type BackupInfo = Schemas["BackupInfo"];
/** `GET /api/calendar/sync`: calendar sync (CalDAV) — available here, the connected calendar, the last sync. */
export type CalendarSyncStatus = Schemas["CalendarSyncStatus"];
export type CalendarSyncReport = Schemas["CalendarSyncReport"];
/** One event exactly as calendar sync would send it. */
export type CalendarEventPreview = Schemas["CalendarEventPreview"];
export type CalendarSyncPreview = Schemas["CalendarSyncPreview"];
/** What the calendar gets: dates and alarms only (`discreet`), or the calendar file's events (`full`). */
export type CalendarSyncMode = CalendarSyncStatus["mode"];
/** `PUT /api/calendar/sync` (`password: null` keeps the saved app password). */
export type CalendarSyncConnect = Schemas["CalendarSyncConnect"];
/** `POST /api/calendar/sync/discover`: where to look for calendars, with which account. */
export type CalendarSyncFind = Schemas["CalendarSyncFind"];
/** A calendar that takes events, as discovery found it. */
export type CalendarChoice = Schemas["CalendarChoice"];

// ------------------------------------------------------------------------------------------------
// Phone access (Settings → Phone on the computer; pairing on the phone)
// ------------------------------------------------------------------------------------------------

/**
 * `GET /api/phone` (computer only): whether phone access can be used here (`available`, never in the demo), is on
 * (`enabled`) and reachable (`listening`, at `url`), why not (`problem`), what to know at once (`notice`), the
 * certificate's fingerprints, the open pairing code's progress (never the code) and the paired phones.
 */
export type PhoneStatus = Schemas["PhoneStatus"];
/** Why phone access is on but not listening, in words for the person. */
export type PhoneProblem = Schemas["PhoneProblem"];
/** A danger-tone notice: wrong codes stopped a pairing, a code was used twice, a phone's sign-in was used twice. */
export type PhoneNotice = Schemas["PhoneNotice"];
/** An address of this computer on a home network (`recommended`: the one it reaches the internet from). */
export type AddressChoice = Schemas["AddressChoice"];
/** A paired phone (never its sign-in): name, platform, its two check words, when and where it was last used. */
export type PhoneDevice = Schemas["PhoneDevice"];
/** The open pairing code's progress: when it ends, whether a phone opened the page, wrong codes and from where. */
export type PhonePairingState = Schemas["PhonePairingState"];
/** `POST /api/phone/pairing`: the QR code's `url` (`https://<address>:<port>/pair#<code>`), the code, its end. */
export type PhonePairing = Schemas["PhonePairing"];
/** `POST /api/phone/pair` on the phone: the name it got and the two words both screens show. */
export type PairResult = Schemas["PairResult"];

// ------------------------------------------------------------------------------------------------
// Hand-off sync between the person's computers (Settings → Your computers; the standing-by screen)
// ------------------------------------------------------------------------------------------------

/**
 * `GET /api/sync` (computer only, from the server's memory — it never reads the folder or the password store):
 * whether sync can be used here, this computer's `mode` (`in_use` or `standing_by`), what it is busy with, the
 * computers, what is arriving, a choice to make, a problem, notices and kept copies.
 */
export type SyncStatus = Schemas["SyncStatus"];
/** `off`, `starting`, `in_use` (this computer is the one in use) or `standing_by` (another is: writes are refused). */
export type SyncMode = SyncStatus["mode"];
/** `idle`, `saving`, `waiting` (for the sync tool), `bringing_over` (writes refused for a moment) or `keeping`. */
export type SyncActivity = SyncStatus["activity"];
/** A computer of this sync as this one sees it (`key` is a small number for the UI, never its id). */
export type SyncComputer = Schemas["SyncComputer"];
export type SyncComputerState = SyncComputer["state"];
/** Calendar sync on another computer compared with this one's. */
export type SyncCalendarMatch = SyncComputer["calendar"];
/** A version still arriving from the sync tool (files and bytes; online-only placeholders counted apart). */
export type SyncArriving = Schemas["SyncArriving"];
/** Why sync is paused or needs the person: a title and a message for people, and what can be done. */
export type SyncProblem = Schemas["SyncProblem"];
/** One computer's Ordnung in a choice: its letters, how many were added since the two last agreed, the newest. */
export type SyncSide = Schemas["SyncSide"];
/** Both computers changed something: which computer's Ordnung to keep (`joining`: this one is joining with letters). */
export type SyncChoice = Schemas["SyncChoice"];
export type SyncLetter = Schemas["SyncLetter"];
/** A kept copy: this computer's data saved (an encrypted backup) before it was replaced. */
export type SyncKept = Schemas["SyncKept"];
/** Something the person should know about once (dismissed with `PATCH /api/sync`). */
export type SyncNotice = Schemas["SyncNotice"];
export type SyncNoticeCode = SyncNotice["code"];
/** How far a first save, or bringing a version over, has got. */
export type SyncProgress = Schemas["SyncProgress"];
/** `POST /api/sync/inspect`: what a folder would be — a new sync, one to join, or refused (and why). */
export type SyncFolderInfo = Schemas["SyncFolderInfo"];
/** `PUT /api/sync`: the status, or the choice to answer first (joining with letters on both sides). */
export type SyncConnected = Schemas["SyncConnected"];

// ------------------------------------------------------------------------------------------------
// Requests
// ------------------------------------------------------------------------------------------------

export type ProfilePatch = Schemas["ProfilePatch"];
export type SettingsPatch = Schemas["SettingsPatch"];
export type OnboardingRequest = Schemas["OnboardingRequest"];
export type DocumentPatch = Schemas["DocumentPatch"];
export type ItemCreate = Schemas["ItemCreate"];
export type ItemPatch = Schemas["ItemPatch"];
export type ContractPatch = Schemas["ContractPatch"];
/** `PATCH /api/parties/{id}`: the Land a sender is in (`null`: "Don't know"). */
export type PartyPatch = Schemas["PartyPatch"];
export type SuggestionPatch = Schemas["SuggestionPatch"];
export type DraftCreate = Schemas["DraftCreate"];
export type DraftPatch = Schemas["DraftPatch"];
export type MarkSentRequest = Schemas["MarkSentRequest"];
export type TrackingUpdate = Schemas["TrackingUpdate"];
export type ProofPatch = Schemas["ProofPatch"];
export type CallNoteCreate = Schemas["CallNoteCreate"];
export type CallNotePatch = Schemas["CallNotePatch"];
export type AskRequest = Schemas["AskRequest"];
export type TourPatch = Schemas["TourPatch"];
export type HeldRequest = Schemas["HeldRequest"];
/** `PUT /api/phone`: on or off, the address or port (none: the saved or recommended one), "This is my home network". */
export type PhoneAccessChange = Schemas["PhoneAccessChange"];
/** `POST /api/phone/pair`: the code as shown or typed (spaces, dashes and case don't matter) and this phone's name. */
export type PairRequest = Schemas["PairRequest"];
/** `PUT /api/sync`: set up a new sync folder or join one (the passphrase travels only to this computer's Ordnung). */
export type SyncConnect = Schemas["SyncConnect"];
/** `PATCH /api/sync`: rename this computer, answer a problem, or dismiss a notice. */
export type SyncChange = Schemas["SyncChange"];
/** `DELETE /api/sync`: disconnect (`unreceived_ok`: the second confirmation). */
export type SyncDisconnect = Schemas["SyncDisconnect"];
/** `POST /api/sync/use-here`: "Use Ordnung here" (`older_copy`, or `cancel` a waiting take-over). */
export type SyncUseHere = Schemas["SyncUseHere"];
/** `POST /api/sync/save`: save now (`hand_over`: then stand by). */
export type SyncSave = Schemas["SyncSave"];

export type DocumentListParams = ApiQuery<"/api/documents", "get">;
export type ItemListParams = ApiQuery<"/api/items", "get">;
export type ContractListParams = ApiQuery<"/api/contracts", "get">;
export type SuggestionListParams = ApiQuery<"/api/suggestions", "get">;
export type CallListParams = ApiQuery<"/api/calls", "get">;

// ------------------------------------------------------------------------------------------------
// Streams: POST /api/ask and GET /api/events (their payloads are OpenAPI components too)
// ------------------------------------------------------------------------------------------------

/**
 * One event of the streamed `POST /api/ask` answer (the JSON `data` of a default SSE `message`):
 * `tool_use` / `tool_result` (the visible trace, human label/summary in `text`), `text` deltas,
 * then `done` (the checked answer in `text`, validated `citations`, `message_id`, `thread_id`)
 * or `error`.
 */
export type StreamEvent = Schemas["StreamEvent"];
/** A validated citation of the final `done` event. */
export type CitationRef = Schemas["CitationRef"];

/** Live event name → the JSON `data` of that SSE event on `GET /api/events`. */
export type ServerEventMap = Schemas["ServerEvents"];
export type ServerEventType = keyof ServerEventMap;
export type ServerEvent = { [K in ServerEventType]: { type: K; data: ServerEventMap[K] } }[ServerEventType];

export type JobProgressEvent = ServerEventMap["job.progress"];
export type LlmPausedEvent = ServerEventMap["llm.paused"];
