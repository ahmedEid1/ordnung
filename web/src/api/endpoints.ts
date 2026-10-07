/**
 * One typed function per endpoint of SPEC §13. Prefer the TanStack Query hooks in `./hooks`
 * inside components; use these directly for imperative flows (downloads, streaming, tests).
 *
 * Every call names its route as the OpenAPI path (`"/api/documents/{doc_id}"`) and method, so the
 * path, the query parameters, the JSON body and the response type all come from the generated
 * schema (`./schema.d.ts`): a route the backend renames or removes fails `tsc`.
 */
import { API_BASE, ApiError, assetUrl, request, requestRaw, type QueryValue, type RequestOptions } from "./client";
import { readStreamEvents } from "./sse-parser";
import type {
  ApiBody,
  ApiMethod,
  ApiPath,
  ApiQuery,
  ApiResponse,
  AskRequest,
  CalendarSyncConnect,
  CalendarSyncFind,
  CalendarSyncMode,
  CallListParams,
  CallNoteCreate,
  CallNotePatch,
  ContractListParams,
  ContractPatch,
  DesktopMode,
  DocumentListParams,
  DocumentPatch,
  DraftCreate,
  DraftPatch,
  Health,
  ItemCreate,
  ItemListParams,
  ItemPatch,
  MarkSentRequest,
  OnboardingRequest,
  PairRequest,
  PartyPatch,
  PathsWith,
  PhoneAccessChange,
  ProfilePatch,
  ProofKind,
  ProofPatch,
  PublicHealth,
  SettingsPatch,
  StreamEvent,
  SuggestionListParams,
  SuggestionPatch,
  TourPatch,
  TrackingUpdate,
  TransferValues,
} from "./types";

const enc = encodeURIComponent;

type PathParams = Record<string, string | number>;

/** `"/api/documents/{doc_id}"` + `{ doc_id: "doc_1" }` → `"/documents/doc_1"` (the client adds `/api`). */
export function apiRoute(template: ApiPath, params: PathParams = {}): string {
  return template.slice(API_BASE.length).replace(/\{(\w+)\}/g, (_, key: string) => {
    if (!(key in params)) throw new Error(`Missing path parameter “${key}” for ${template}`);
    return enc(String(params[key]));
  });
}

interface CallOptions<P extends ApiPath, M extends ApiMethod> {
  params?: PathParams;
  query?: ApiQuery<P, M>;
  body?: ApiBody<P, M> | FormData;
  signal?: AbortSignal;
}

/** `method template` with typed query, body and response (see the module comment). */
function call<M extends ApiMethod, P extends PathsWith<M>>(
  method: M,
  template: P,
  opts: CallOptions<P, M> = {},
): Promise<ApiResponse<P, M>> {
  return request<ApiResponse<P, M>>(apiRoute(template, opts.params), {
    method: method.toUpperCase() as RequestOptions["method"],
    query: opts.query as Record<string, QueryValue> | undefined,
    body: opts.body,
    signal: opts.signal,
  });
}

const SIGNED_OUT =
  "This window isn't signed in to Ordnung any more. Open it again with the link printed by “ordnung serve”.";

/** `GET /api/health` answers without the session token too — with only the version. */
function signedIn(health: Health | PublicHealth): Health {
  if ("today" in health) return health;
  throw new ApiError(401, SIGNED_OUT, health);
}

export interface UploadOptions {
  /** Combine several images into one multi-page letter (default when several photos are dropped). */
  combine?: boolean;
  /** "Keep private — no AI": store and index only, never send to Claude. */
  private?: boolean;
}

/** A proof to attach to a sent letter: the file (kept private, never read by Claude), what it is and the day it shows. */
export interface ProofUpload {
  file: File;
  kind: ProofKind;
  onDate?: string | null;
  note?: string | null;
}

export const api = {
  // -- system ------------------------------------------------------------------------------------
  health: (signal?: AbortSignal) => call("get", "/api/health", { signal }).then(signedIn),
  /** "Run check": every `ordnung doctor` check plus one tiny live call (429 within a minute). */
  probeHealth: () => call("get", "/api/health", { query: { probe: true } }).then(signedIn),
  profile: () => call("get", "/api/profile"),
  updateProfile: (profile: ProfilePatch) => call("put", "/api/profile", { body: profile }),
  settings: () => call("get", "/api/settings"),
  updateSettings: (settings: SettingsPatch) => call("put", "/api/settings", { body: settings }),
  onboarding: (body: OnboardingRequest) => call("post", "/api/onboarding", { body }),
  /** "Delete everything": wipes the data folder; the API insists on the typed word `DELETE`. */
  deleteEverything: () => call("delete", "/api/data", { body: { confirm: "DELETE" } }),

  // -- documents ---------------------------------------------------------------------------------
  documents: (params: DocumentListParams = {}) => call("get", "/api/documents", { query: { ...params } }),
  /** Multipart upload: `files` (repeated), `combine`, `private` → 201 with documents, jobs, duplicates, errors. */
  uploadDocuments: (files: File[] | FileList, opts: UploadOptions = {}) => {
    const form = new FormData();
    for (const f of Array.from(files)) form.append("files", f, f.name);
    form.append("combine", String(Boolean(opts.combine)));
    form.append("private", String(Boolean(opts.private)));
    return call("post", "/api/documents", { body: form });
  },
  document: (id: string) => call("get", "/api/documents/{doc_id}", { params: { doc_id: id } }),
  updateDocument: (id: string, patch: DocumentPatch) =>
    call("patch", "/api/documents/{doc_id}", { params: { doc_id: id }, body: patch }),
  /** Move a letter to the trash (`purge`: delete it and everything derived from it for good). */
  deleteDocument: (id: string, opts: { purge?: boolean } = {}) =>
    call("delete", "/api/documents/{doc_id}", { params: { doc_id: id }, query: { purge: opts.purge || undefined } }),
  /** 202 with the new reading job. */
  reprocessDocument: (id: string) => call("post", "/api/documents/{doc_id}/reprocess", { params: { doc_id: id } }),
  /** Original file (PDF/image). */
  fileUrl: (id: string) => assetUrl(apiRoute("/api/documents/{doc_id}/file", { doc_id: id })),
  /** Rendered page image (1-based page number). */
  pageUrl: (id: string, page: number) => assetUrl(apiRoute("/api/documents/{doc_id}/pages/{page}.jpg", { doc_id: id, page })),
  thumbnailUrl: (id: string) => assetUrl(apiRoute("/api/documents/{doc_id}/thumbnail.jpg", { doc_id: id })),
  /** "How it was read": one reading's steps (`run`: its trace id; default the newest kept) and every kept reading. */
  documentTrace: (id: string, run?: string | null) =>
    call("get", "/api/documents/{doc_id}/trace", { params: { doc_id: id }, query: { run: run ?? undefined } }),
  /** What a later reading (`head`, default the newest) decided differently from an earlier one (`base`, default the one before). */
  traceComparison: (id: string, runs: { base?: string | null; head?: string | null } = {}) =>
    call("get", "/api/documents/{doc_id}/trace/compare", {
      params: { doc_id: id },
      query: { base: runs.base ?? undefined, head: runs.head ?? undefined },
    }),
  /** Every kept reading of the letters not in the trash, as stored (for "Download your records"). */
  traces: () => call("get", "/api/traces"),

  // -- the watched folder ------------------------------------------------------------------------
  /** The watched folder: path, state (or problem), auto-read, letters waiting, the last files. */
  folder: () => call("get", "/api/folder"),
  /** "Read these": the waiting letters the person saw may be sent to Claude (409 in the replay-only demo). */
  readHeld: (docIds: string[]) => call("post", "/api/documents/held/read", { body: { doc_ids: docIds } }),
  /** "Keep private": the waiting letters stay on this computer, never sent to Claude. */
  keepHeldPrivate: (docIds: string[]) => call("post", "/api/documents/held/keep-private", { body: { doc_ids: docIds } }),
  /** Undo "Keep private": letters kept private from waiting (never read since) wait again. */
  waitAgain: (docIds: string[]) => call("post", "/api/documents/held/wait", { body: { doc_ids: docIds } }),

  // -- to-dos & dates ----------------------------------------------------------------------------
  items: (params: ItemListParams = {}) => call("get", "/api/items", { query: { ...params } }),
  createItem: (item: ItemCreate) => call("post", "/api/items", { body: item }),
  updateItem: (id: string, patch: ItemPatch) => call("patch", "/api/items/{item_id}", { params: { item_id: id }, body: patch }),
  deleteItem: (id: string) => call("delete", "/api/items/{item_id}", { params: { item_id: id } }),
  /** "Yes, that's right" — sets grounding to `user`. */
  confirmItem: (id: string) => call("post", "/api/items/{item_id}/confirm", { params: { item_id: id } }),
  /** "These match the letter": the person compared a payment's transfer details with the letter. */
  confirmGiroCode: (id: string, values: TransferValues) =>
    call("post", "/api/items/{item_id}/girocode/confirm", { params: { item_id: id }, body: values }),
  itemIcsUrl: (id: string) => assetUrl(apiRoute("/api/items/{item_id}.ics", { item_id: id })),

  // -- contracts, parties, threads ---------------------------------------------------------------
  contracts: (params: ContractListParams = {}) => call("get", "/api/contracts", { query: { ...params } }),
  updateContract: (id: string, patch: ContractPatch) =>
    call("patch", "/api/contracts/{contract_id}", { params: { contract_id: id }, body: patch }),
  parties: () => call("get", "/api/parties"),
  party: (id: string) => call("get", "/api/parties/{party_id}", { params: { party_id: id } }),
  /** The Land a sender is in, which only the person can tell: its letters' dates are recomputed. */
  updateParty: (id: string, patch: PartyPatch) => call("patch", "/api/parties/{party_id}", { params: { party_id: id }, body: patch }),
  case: (id: string) => call("get", "/api/cases/{case_id}", { params: { case_id: id } }),

  // -- views -------------------------------------------------------------------------------------
  timeline: (from?: string, to?: string) => call("get", "/api/timeline", { query: { from, to } }),
  lanes: (from?: string, to?: string) => call("get", "/api/lanes", { query: { from, to } }),
  dashboard: () => call("get", "/api/dashboard"),
  /** My numbers: yours, your documents, a call sheet per organisation, open cases (worked out on read). */
  numbers: () => call("get", "/api/numbers"),
  /** The weekly session: seven steps and "All clear until …". */
  week: () => call("get", "/api/week"),
  /** "Done": remembers the session (answers the session as it stands afterwards). */
  weekDone: () => call("post", "/api/week/done"),
  /** "Not now" on Today's prompt. */
  weekDismiss: () => call("post", "/api/week/dismiss"),

  // -- ideas & brief -----------------------------------------------------------------------------
  suggestions: (params: SuggestionListParams = {}) => call("get", "/api/suggestions", { query: { ...params } }),
  updateSuggestion: (id: string, patch: SuggestionPatch) =>
    call("patch", "/api/suggestions/{suggestion_id}", { params: { suggestion_id: id }, body: patch }),
  /** 202: the review runs in the background; new Ideas arrive with `suggestions.updated`. */
  runReview: () => call("post", "/api/suggestions/review"),
  brief: () => call("get", "/api/brief"),
  regenerateBrief: () => call("post", "/api/brief"),

  // -- ask ---------------------------------------------------------------------------------------
  /**
   * Stream an answer. Yields `tool_use` / `tool_result` events (the visible trace), `text` deltas
   * and finally `done` (with `message_id`, `thread_id`, validated `citations`) or `error`.
   */
  ask: async function* (body: AskRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    const res = await requestRaw(apiRoute("/api/ask"), {
      method: "POST",
      body,
      signal,
      headers: { Accept: "text/event-stream" },
    });
    if (!res.body) throw new ApiError(res.status, "The answer stream was empty.");
    yield* readStreamEvents(res.body, signal);
  },
  chat: (threadId: string) => call("get", "/api/chat/{thread_id}", { params: { thread_id: threadId } }),

  // -- letters (drafts) --------------------------------------------------------------------------
  drafts: () => call("get", "/api/drafts"),
  createDraft: (body: DraftCreate) => call("post", "/api/drafts", { body }),
  draft: (id: string) => call("get", "/api/drafts/{draft_id}", { params: { draft_id: id } }),
  updateDraft: (id: string, patch: DraftPatch) =>
    call("patch", "/api/drafts/{draft_id}", { params: { draft_id: id }, body: patch }),
  /** Deletes the letter and its proofs; their files too unless `keepProofFiles` (they stay as documents). */
  deleteDraft: (id: string, keepProofFiles = false) =>
    call("delete", "/api/drafts/{draft_id}", { params: { draft_id: id }, query: keepProofFiles ? { keep_proof_files: true } : {} }),
  /** Translate the (edited) letter again; only `body_translation` changes. 409 in the demo. */
  translateDraft: (id: string) => call("post", "/api/drafts/{draft_id}/translate", { params: { draft_id: id } }),
  draftPdfUrl: (id: string) => assetUrl(apiRoute("/api/drafts/{draft_id}/pdf", { draft_id: id })),
  /** The printable letter as one image, page under page (the print preview: phones show no PDF inline). */
  draftPreviewUrl: (id: string) => assetUrl(apiRoute("/api/drafts/{draft_id}/preview.png", { draft_id: id })),
  markDraftSent: (id: string, body: MarkSentRequest) =>
    call("post", "/api/drafts/{draft_id}/sent", { params: { draft_id: id }, body }),

  // -- proof of a sent letter --------------------------------------------------------------------
  /** Tracking number, proofs (what each shows and doesn't), timeline, what's missing, what it waits for. */
  draftProof: (id: string) => call("get", "/api/drafts/{draft_id}/proof", { params: { draft_id: id } }),
  /** Save or (with `null`) remove the tracking number; a mistyped check digit answers 422 with the reason. */
  setTracking: (id: string, body: TrackingUpdate) =>
    call("put", "/api/drafts/{draft_id}/tracking", { params: { draft_id: id }, body }),
  /** Multipart: `file`, `kind`, `on_date`, `note` → 201 with the letter's new proof overview. */
  addProof: (id: string, upload: ProofUpload) => {
    const form = new FormData();
    form.append("file", upload.file);
    form.append("kind", upload.kind);
    if (upload.onDate) form.append("on_date", upload.onDate);
    if (upload.note?.trim()) form.append("note", upload.note.trim());
    return call("post", "/api/drafts/{draft_id}/proofs", { params: { draft_id: id }, body: form });
  },
  updateProof: (id: string, proofId: string, patch: ProofPatch) =>
    call("patch", "/api/drafts/{draft_id}/proofs/{proof_id}", { params: { draft_id: id, proof_id: proofId }, body: patch }),
  /** Removes the proof; its file is deleted for good unless another proof uses it. */
  removeProof: (id: string, proofId: string) =>
    call("delete", "/api/drafts/{draft_id}/proofs/{proof_id}", { params: { draft_id: id, proof_id: proofId } }),
  /** "It's answered": by the letter `docId`, or (`null`) by phone, e-mail …; closes the follow-up. */
  markAnswered: (id: string, docId: string | null) =>
    call("post", "/api/drafts/{draft_id}/answered", { params: { draft_id: id }, body: { doc_id: docId } }),
  /** Take back "it's answered" (Undo): the letter waits again and its follow-up reopens. */
  unmarkAnswered: (id: string) => call("delete", "/api/drafts/{draft_id}/answered", { params: { draft_id: id } }),
  /** The Nachweis: summary and timeline, the letter as sent, every proof file — one PDF. */
  proofPdfUrl: (id: string) => assetUrl(apiRoute("/api/drafts/{draft_id}/proof.pdf", { draft_id: id })),

  // -- waiting for & call notes ------------------------------------------------------------------
  /** Replies, money and callbacks the person is owed: overdue first, then answered, then waiting (each by day). */
  waiting: () => call("get", "/api/waiting"),
  calls: (params: CallListParams = {}) => call("get", "/api/calls", { query: { ...params } }),
  createCall: (body: CallNoteCreate) => call("post", "/api/calls", { body }),
  /** Say the promise made on the call was kept (or take that back). */
  updateCall: (id: string, patch: CallNotePatch) => call("patch", "/api/calls/{call_id}", { params: { call_id: id }, body: patch }),
  deleteCall: (id: string) => call("delete", "/api/calls/{call_id}", { params: { call_id: id } }),

  // -- calendar ----------------------------------------------------------------------------------
  calendarIcsUrl: () => assetUrl(apiRoute("/api/calendar.ics")),
  calendarExported: () => call("post", "/api/calendar/exported"),

  // -- reminders outside the browser & backup ----------------------------------------------------
  /** `preview: false` leaves today's texts out (they are built from the agenda). */
  desktopReminders: (preview = true) => call("get", "/api/reminders/desktop", { query: { preview: preview ? undefined : false } }),
  /** Show today's notification now (a sample when nothing is due); the morning one still comes. */
  testDesktopNotification: (mode: DesktopMode) => call("post", "/api/reminders/desktop/test", { body: { mode } }),
  backupInfo: () => call("get", "/api/backup"),
  /**
   * The encrypted backup file. The passphrase goes to this computer's Ordnung only, in the request
   * body; the file comes back as it is made (a Blob once complete).
   */
  downloadBackup: async (passphrase: string, signal?: AbortSignal): Promise<Blob> => {
    const body: ApiBody<"/api/backup", "post"> = { passphrase };
    const res = await requestRaw(apiRoute("/api/backup"), { method: "POST", body, signal });
    return res.blob();
  },

  // -- calendar sync (CalDAV) --------------------------------------------------------------------
  calendarSync: () => call("get", "/api/calendar/sync"),
  calendarSyncPreview: (mode: CalendarSyncMode) => call("get", "/api/calendar/sync/preview", { query: { mode } }),
  /** The calendars that take events at or under an address (nothing is stored). */
  discoverCalendars: (body: CalendarSyncFind) => call("post", "/api/calendar/sync/discover", { body }),
  /** Connect (or change the mode of) the calendar; the app password goes to this computer's keyring only. */
  connectCalendarSync: (body: CalendarSyncConnect) => call("put", "/api/calendar/sync", { body }),
  runCalendarSync: () => call("post", "/api/calendar/sync/run"),
  disconnectCalendarSync: (removeEvents: boolean) => call("post", "/api/calendar/sync/disconnect", { body: { remove_events: removeEvents } }),

  // -- phone access ------------------------------------------------------------------------------
  // On the computer (computer only): Settings → Phone.
  /** Whether phone access can be used here and is on, its address, certificate, pairing progress and phones. */
  phone: () => call("get", "/api/phone"),
  /** Turn phone access on or off, choose its address or port, or say "This is my home network". */
  updatePhone: (change: PhoneAccessChange) => call("put", "/api/phone", { body: change }),
  /** A new pairing code (replacing an open one): the only answer that contains it. */
  createPhonePairing: () => call("post", "/api/phone/pairing"),
  /** Cancel the open pairing code (the dialog closed); 204. */
  cancelPhonePairing: () => call("delete", "/api/phone/pairing"),
  /** Remove a paired phone: it is signed out at once. */
  removePhone: (id: string) => call("delete", "/api/phone/devices/{device_id}", { params: { device_id: id } }),
  /** "Start over": off, every phone removed, a new certificate when it is turned on again. */
  resetPhone: () => call("post", "/api/phone/reset"),
  // On a phone that isn't paired yet (the only call it may make): the answer sets its sign-in cookie.
  /** Pair this phone with the code shown on the computer (404 `not_phone` on the computer itself). */
  pairPhone: (body: PairRequest) => call("post", "/api/phone/pair", { body }),

  // -- privacy & AI usage ------------------------------------------------------------------------
  /** What Ordnung did, newest first; `device`: only what one paired phone did (its id). */
  activity: (limit = 100, device?: string | null) => call("get", "/api/activity", { query: { limit, device: device ?? undefined } }),
  usage: () => call("get", "/api/usage"),
  rules: () => call("get", "/api/rules"),
  jobs: (activeOnly = false) => call("get", "/api/jobs", { query: { active_only: activeOnly || undefined } }),

  // -- demo --------------------------------------------------------------------------------------
  tour: () => call("get", "/api/demo/tour"),
  updateTour: (patch: TourPatch) => call("patch", "/api/demo/tour", { body: patch }),
  mailTray: () => call("get", "/api/demo/mail"),
  demoQuestions: () => call("get", "/api/demo/questions"),
  openMail: (id: string) => call("post", "/api/demo/mail", { body: { id } }),
};

export type Api = typeof api;
