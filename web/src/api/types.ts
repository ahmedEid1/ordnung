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

export const DOCUMENT_STATUSES = ["queued", "processing", "processed", "needs_review", "failed"] as const;
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
  Same<TimelineType, Schemas["TimelineEntry"]["type"]>,
  Same<AreaStatusLevel, Schemas["AreaStatus"]["status"]>,
  Same<LaneBarKind, Schemas["LaneBar"]["kind"]>,
  Same<LaneBarStatus, Schemas["LaneBar"]["status"]>,
  Same<MarkerKind, Schemas["TimelineMarker"]["kind"]>,
  Same<JobKind, Schemas["Job"]["kind"]>,
  Same<JobStatus, Schemas["Job"]["status"]>,
  Same<JobStage, Schemas["JobProgressEvent"]["stage"]>,
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
export type ClaudeStatus = Schemas["ClaudeStatus"];
/** One `ordnung doctor` check (listed by `GET /api/health?probe=1`). */
export type DoctorCheck = Schemas["DoctorCheck"];
/**
 * `GET /api/health` for the signed-in app. `today` is the app's "today" (ISO date) — always use
 * it, never the browser clock; `rules_last_checked` is the "Based on the law as of" date.
 */
export type Health = Schemas["Health"];
/** `GET /api/health` without the session token (the endpoint client turns it into a 401 error). */
export type PublicHealth = Schemas["PublicHealth"];
/** An entry of the legal rules catalog ("How dates are computed"). */
export type RuleInfo = Schemas["RuleInfo"];
export type TimelineMarker = Schemas["TimelineMarker"];
/**
 * A bar on the life lanes. `open_end` marks a bar with no end date (an open-ended contract, or
 * "cancellable any time" after a minimum term): its `end` is only where the chart stops drawing
 * it, so it is never shown as a date. Set by the contract lanes the web app builds itself
 * (`contractLanes`) and by the static demo; the server does not send it yet.
 */
export type LaneBar = Schemas["LaneBar"] & { open_end?: boolean };
/** A "life lane" (Residence, Contracts, Tax, Study, …) on the year-ahead timeline. */
export type Lane = Omit<Schemas["Lane"], "bars"> & { bars: LaneBar[] };
export type SearchHit = Schemas["SearchHit"];
export type TourState = Schemas["TourState"];
/** A letter waiting in the demo's "New mail" tray. */
export type MailTrayItem = Schemas["MailTrayItem"];

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
export type SuggestionPatch = Schemas["SuggestionPatch"];
export type DraftCreate = Schemas["DraftCreate"];
export type DraftPatch = Schemas["DraftPatch"];
export type MarkSentRequest = Schemas["MarkSentRequest"];
export type AskRequest = Schemas["AskRequest"];
export type TourPatch = Schemas["TourPatch"];

export type DocumentListParams = ApiQuery<"/api/documents", "get">;
export type ItemListParams = ApiQuery<"/api/items", "get">;
export type ContractListParams = ApiQuery<"/api/contracts", "get">;
export type SuggestionListParams = ApiQuery<"/api/suggestions", "get">;

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
