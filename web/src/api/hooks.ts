/**
 * TanStack Query hooks for every endpoint.
 *
 * - `qk` is the query-key factory; invalidate by prefix (e.g. `qk.documents.all`).
 * - Mutations invalidate what they affect. Anything that changes the ledger (documents, to-dos &
 *   dates, contracts, ideas) calls {@link invalidateLedger}, which refreshes every derived view
 *   (dashboard, timeline, lanes, brief…). It is a local app, so refetching is cheap.
 * - Errors of mutations surface as a toast through the global MutationCache handler
 *   (`app/queryClient.ts`); pass `meta: { silent: true }` to opt out.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, type ProofUpload, type UploadOptions } from "./endpoints";
import { ApiError } from "./client";
import { setClientKind } from "./clientKind";
import type {
  CalendarSyncConnect,
  CalendarSyncFind,
  CalendarSyncMode,
  CallListParams,
  CallNoteCreate,
  ContractListParams,
  ContractPatch,
  DesktopMode,
  DocumentDetail,
  DocumentListParams,
  DocumentPatch,
  DraftCreate,
  DraftPatch,
  Health,
  HeldResult,
  ItemCreate,
  ItemListParams,
  ItemPatch,
  MarkSentRequest,
  OnboardingRequest,
  PairRequest,
  PartyDetail,
  PartyPatch,
  PhoneAccessChange,
  PhoneStatus,
  ProfilePatch,
  ProofOverview,
  ProofPatch,
  SettingsPatch,
  StreamEvent,
  SuggestionListParams,
  SuggestionPatch,
  SuggestionRef,
  SyncChange,
  SyncConnect,
  SyncDisconnect,
  SyncSave,
  SyncStatus,
  SyncUseHere,
  TourPatch,
  TransferValues,
} from "./types";

// ------------------------------------------------------------------------------------------------
// Query keys
// ------------------------------------------------------------------------------------------------

export const qk = {
  health: ["health"] as const,
  profile: ["profile"] as const,
  settings: ["settings"] as const,
  documents: {
    all: ["documents"] as const,
    list: (params: DocumentListParams = {}) => ["documents", "list", params] as const,
    detail: (id: string) => ["documents", "detail", id] as const,
    /** Under `documents`, so a new reading (any ledger write) refreshes it. */
    trace: (id: string, run: string | null = null) => ["documents", "trace", id, run] as const,
    traceComparison: (id: string, base: string | null, head: string | null) => ["documents", "trace-compare", id, base, head] as const,
  },
  items: {
    all: ["items"] as const,
    list: (params: ItemListParams = {}) => ["items", "list", params] as const,
  },
  contracts: {
    all: ["contracts"] as const,
    list: (params: ContractListParams = {}) => ["contracts", "list", params] as const,
  },
  parties: {
    all: ["parties"] as const,
    list: () => ["parties", "list"] as const,
    detail: (id: string) => ["parties", "detail", id] as const,
  },
  cases: {
    all: ["cases"] as const,
    detail: (id: string) => ["cases", "detail", id] as const,
  },
  timeline: (from?: string, to?: string) => ["timeline", from ?? null, to ?? null] as const,
  lanes: (from?: string, to?: string) => ["lanes", from ?? null, to ?? null] as const,
  dashboard: ["dashboard"] as const,
  numbers: ["numbers"] as const,
  week: ["week"] as const,
  suggestions: {
    all: ["suggestions"] as const,
    list: (params: SuggestionListParams = {}) => ["suggestions", "list", params] as const,
  },
  brief: ["brief"] as const,
  chat: (threadId: string) => ["chat", threadId] as const,
  drafts: {
    all: ["drafts"] as const,
    list: () => ["drafts", "list"] as const,
    detail: (id: string) => ["drafts", "detail", id] as const,
    proof: (id: string) => ["drafts", "proof", id] as const,
  },
  waiting: ["waiting"] as const,
  calls: {
    all: ["calls"] as const,
    list: (params: CallListParams = {}) => ["calls", "list", params] as const,
  },
  activity: ["activity"] as const,
  usage: ["usage"] as const,
  rules: ["rules"] as const,
  jobs: ["jobs"] as const,
  folder: ["folder"] as const,
  /** Settings → Phone (computer only). */
  phone: ["phone"] as const,
  /** Hand-off sync's status (computer only): Settings → Your computers, the top bar, the standing-by screen. */
  sync: ["sync"] as const,
  tour: ["demo", "tour"] as const,
  mail: ["demo", "mail"] as const,
  questions: ["demo", "questions"] as const,
};

/** Keys whose data derives from the ledger; refreshed after any write. */
const LEDGER_PREFIXES = [
  qk.documents.all,
  qk.items.all,
  qk.contracts.all,
  qk.parties.all,
  qk.cases.all,
  ["timeline"],
  ["lanes"],
  qk.dashboard,
  qk.numbers,
  qk.week,
  qk.suggestions.all,
  qk.brief,
  qk.drafts.all,
  qk.activity,
  qk.jobs,
  qk.folder,
  qk.waiting,
  qk.questions,
] as const;

/** Invalidate every ledger-derived query (documents, items, contracts, views, ideas…). */
export function invalidateLedger(qc: QueryClient): Promise<void> {
  return Promise.all(LEDGER_PREFIXES.map((queryKey) => qc.invalidateQueries({ queryKey }))).then(() => undefined);
}

const MINUTE = 60_000;

// ------------------------------------------------------------------------------------------------
// System
// ------------------------------------------------------------------------------------------------

/** How long `/health` may take before it counts as "Ordnung isn't answering" (a hung server). */
export const HEALTH_TIMEOUT_MS = 10_000;

/** The query's own signal (cancel) plus a time limit, where the browser supports combining them. */
function withTimeout(signal: AbortSignal | undefined, ms: number): AbortSignal | undefined {
  if (typeof AbortSignal === "undefined" || typeof AbortSignal.timeout !== "function") return signal;
  const timeout = AbortSignal.timeout(ms);
  if (!signal) return timeout;
  return typeof AbortSignal.any === "function" ? AbortSignal.any([signal, timeout]) : signal;
}

/**
 * `GET /health` — version, demo flag, the app's today, Claude status, rules "law as of" date. A
 * server that accepts the connection but never answers fails after {@link HEALTH_TIMEOUT_MS}, so
 * the app shows "Ordnung isn't running" instead of the splash forever.
 */
export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: ({ signal }) => api.health(withTimeout(signal, HEALTH_TIMEOUT_MS)).then(rememberClient, notPairedHere),
    staleTime: 5 * MINUTE,
    retry: 1,
  });
}

/** Health says who this tab is (`clientKind()`, for code outside React). */
function rememberClient(health: Health): Health {
  setClientKind(health.client);
  return health;
}

/** Only the phone listener refuses with `phone_not_paired` (a phone that was removed, or never paired). */
function notPairedHere(err: unknown): never {
  if (err instanceof ApiError && err.code === "phone_not_paired") setClientKind("phone");
  throw err;
}

/** "Run check" (`GET /health?probe=1`): the doctor's checks plus one tiny live call; the answer
 * replaces the cached health. At most once a minute (the API answers 429 otherwise). */
export function useProbeHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.probeHealth(),
    meta: { errorTitle: "Couldn't run the check" },
    onSuccess: (health) => qc.setQueryData(qk.health, rememberClient(health)),
  });
}

/** The day the rules catalog was last checked against the law ("Based on the law as of …"). */
export function useRulesLastChecked(): string | null {
  return useHealth().data?.rules_last_checked ?? null;
}

export function useProfile() {
  return useQuery({ queryKey: qk.profile, queryFn: api.profile, staleTime: 10 * MINUTE });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: ProfilePatch) => api.updateProfile(p),
    meta: { errorTitle: "Couldn't save your profile" },
    onSuccess: (profile) => {
      qc.setQueryData(qk.profile, profile);
      void invalidateLedger(qc); // region/postal buffer change recomputes dates
    },
  });
}

/** The app's settings (computer only: on a phone pass `enabled: false`). */
export function useSettings(opts: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: qk.settings, queryFn: api.settings, staleTime: 10 * MINUTE, enabled: opts.enabled ?? true });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (s: SettingsPatch) => api.updateSettings(s),
    meta: { errorTitle: "Couldn't save your settings" },
    onSuccess: (settings) => {
      qc.setQueryData(qk.settings, settings);
      void qc.invalidateQueries({ queryKey: qk.folder }); // a new folder restarts the watcher
    },
  });
}

/**
 * "Delete everything": wipes the data folder; afterwards every cached query is stale. `true` is hand-off sync's
 * second confirmation (no other computer has this one's latest changes yet).
 */
export function useDeleteEverything() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (unreceivedOk: boolean = false) => api.deleteEverything(unreceivedOk),
    meta: { silent: true },
    onSuccess: () => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "health" });
      void qc.invalidateQueries();
    },
  });
}

/** The wizard shows a failure next to its "Finish setup" button (a toast would outlive a retry). */
export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingRequest) => api.onboarding(body),
    meta: { silent: true },
    onSuccess: (profile) => {
      qc.setQueryData(qk.profile, profile);
      void qc.invalidateQueries({ queryKey: qk.health });
    },
  });
}

// ------------------------------------------------------------------------------------------------
// Documents
// ------------------------------------------------------------------------------------------------

export function useDocuments(params: DocumentListParams = {}, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.documents.list(params),
    queryFn: () => api.documents(params),
    staleTime: 30_000,
    placeholderData: params.q !== undefined ? keepPreviousData : undefined,
    enabled: opts.enabled,
  });
}

/** How many matches the letter search lists before it links to all of them in the Inbox. */
export const SEARCH_LIMIT = 8;

/**
 * Full-text search over letters (`GET /documents?q=`). Asks for one more than {@link SEARCH_LIMIT},
 * so the search box knows whether there are more to show. Disabled for queries < 2 chars.
 */
export function useSearchDocuments(q: string) {
  const query = q.trim();
  return useDocuments({ q: query, limit: SEARCH_LIMIT + 1 }, { enabled: query.length >= 2 });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: qk.documents.detail(id ?? ""),
    queryFn: () => api.document(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

/** "How it was read": the reading `run` of letter `id` (default: the newest kept) with its steps. */
export function useDocumentTrace(id: string | undefined, run: string | null = null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.documents.trace(id ?? "", run),
    queryFn: () => api.documentTrace(id!, run),
    enabled: Boolean(id) && (opts.enabled ?? true),
    staleTime: 30_000,
    // switching readings keeps the one shown until the other arrives (no flash of the skeleton)
    placeholderData: (previous) => (previous?.doc_id === id ? previous : undefined),
  });
}

/** What reading `head` of letter `id` decided differently from reading `base`. */
export function useTraceComparison(id: string | undefined, base: string | null, head: string | null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.documents.traceComparison(id ?? "", base, head),
    queryFn: () => api.traceComparison(id!, { base, head }),
    enabled: Boolean(id) && (opts.enabled ?? true),
    staleTime: 30_000,
  });
}

export function useUpdateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: DocumentPatch }) => api.updateDocument(id, patch),
    meta: { errorTitle: "Couldn't save the change to this letter" },
    onSuccess: () => invalidateLedger(qc),
  });
}

/** Delete a letter for good: the file, its page images, everything read from it and its cached answers
 * (docs/privacy.md "Delete means delete" — the app has no trash to empty later). */
export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteDocument(id, { purge: true }),
    meta: { errorTitle: "Couldn't delete the letter" },
    // not awaited: the open letter's own refetch answers 404 and unmounts the page that asked, and then its
    // "Letter deleted" and the way back to the Inbox would never run (e2e/real-app-letters.spec.ts)
    onSuccess: () => void invalidateLedger(qc),
  });
}

export function useReprocessDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.reprocessDocument(id),
    meta: { errorTitle: "Couldn't read the letter again" },
    onSuccess: () => invalidateLedger(qc),
  });
}

/** "Try again" for every letter that couldn't be read (Today's card): each one is read again. */
export function useReprocessDocuments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: readonly string[]) => Promise.all(ids.map((id) => api.reprocessDocument(id))),
    meta: { errorTitle: "Couldn't read the letters again" },
    onSuccess: () => invalidateLedger(qc),
  });
}

/** {@link useReprocessDocument} from inside a panel, which shows the error itself (a toast would wait
 * behind a phone's sheet, or cover the panel's footer). */
export function useReadLetterAgain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.reprocessDocument(id),
    meta: { silent: true },
    onSuccess: () => invalidateLedger(qc),
  });
}

// ------------------------------------------------------------------------------------------------
// The watched folder
// ------------------------------------------------------------------------------------------------

/** `GET /folder`: the watched folder's state, how many letters wait and the last files it brought in. */
export function useFolder(opts: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: qk.folder, queryFn: api.folder, staleTime: 30_000, enabled: opts.enabled });
}

/** The most letters one answer request names (the API's limit); more go in several requests. */
export const HELD_CHUNK = 500;

/**
 * An answer for many waiting letters, sent `HELD_CHUNK` ids at a time and merged into one result
 * (a folder of old scans can hold more than one request may name). Stops at the first failure.
 */
export async function answerInChunks(ids: readonly string[], send: (chunk: string[]) => Promise<HeldResult>): Promise<HeldResult> {
  const merged: HeldResult = { documents: [], jobs: [], skipped: [] };
  for (let at = 0; at < ids.length; at += HELD_CHUNK) {
    const res = await send(ids.slice(at, at + HELD_CHUNK));
    merged.documents.push(...res.documents);
    merged.jobs.push(...res.jobs);
    merged.skipped.push(...res.skipped);
  }
  return merged;
}

/** "Read these N": the waiting letters (as shown) may be sent to Claude; they are queued for reading. */
export function useReadHeld() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docIds: string[]) => answerInChunks(docIds, api.readHeld),
    meta: { errorTitle: "Couldn't start reading them" },
    onSettled: () => invalidateLedger(qc), // a failure halfway still answered the first ones
  });
}

/** "Keep private": the waiting letters stay on this computer and are never sent to Claude. */
export function useKeepHeldPrivate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docIds: string[]) => answerInChunks(docIds, api.keepHeldPrivate),
    meta: { errorTitle: "Couldn't keep them private" },
    onSettled: () => invalidateLedger(qc),
  });
}

/** Undo "Keep private" (the toast's action): those letters wait for the person again. */
export function useWaitAgain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docIds: string[]) => answerInChunks(docIds, api.waitAgain),
    meta: { errorTitle: "Couldn't undo that" },
    onSettled: () => invalidateLedger(qc),
  });
}

export function useUploadDocuments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ files, ...opts }: { files: File[] } & UploadOptions) => api.uploadDocuments(files, opts),
    meta: { errorTitle: "Couldn't add your letters" },
    onSuccess: () => invalidateLedger(qc),
  });
}

// ------------------------------------------------------------------------------------------------
// To-dos & dates
// ------------------------------------------------------------------------------------------------

export function useItems(params: ItemListParams = {}) {
  return useQuery({ queryKey: qk.items.list(params), queryFn: () => api.items(params), staleTime: 30_000 });
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (item: ItemCreate) => api.createItem(item), meta: { errorTitle: "Couldn't add the to-do" }, onSuccess: () => invalidateLedger(qc) });
}

/** PATCH an item — mark done (`{status: "done"}`), snooze, move a date (becomes "manual"). */
export function useUpdateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ItemPatch }) => api.updateItem(id, patch),
    meta: { errorTitle: "Couldn't update the to-do" },
    onSuccess: () => invalidateLedger(qc),
  });
}

export function useDeleteItem() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.deleteItem(id), meta: { errorTitle: "Couldn't delete the to-do" }, onSuccess: () => invalidateLedger(qc) });
}

/** "Yes, that's right" on a "Please check" item. */
export function useConfirmItem() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.confirmItem(id), meta: { errorTitle: "Couldn't confirm the date" }, onSuccess: () => invalidateLedger(qc) });
}

/**
 * "These match the letter": the person compared a payment's transfer details with the letter,
 * which unlocks its GiroCode. The letter's detail is updated in place with the answer (and refetched).
 * A refusal (the details changed meanwhile …) shows in the GiroCode block itself — a toast would wait
 * behind a phone's sheet — and the detail is refetched, so the block shows the details as they are now.
 */
export function useConfirmGiroCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, values }: { itemId: string; docId: string; values: TransferValues }) => api.confirmGiroCode(itemId, values),
    meta: { silent: true },
    onError: (_err, { docId }) => qc.invalidateQueries({ queryKey: qk.documents.detail(docId) }),
    onSuccess: (code, { docId }) => {
      qc.setQueryData<DocumentDetail>(qk.documents.detail(docId), (detail) =>
        detail ? { ...detail, girocodes: detail.girocodes.map((g) => (g.item_id === code.item_id ? code : g)) } : detail,
      );
      return qc.invalidateQueries({ queryKey: qk.documents.detail(docId) });
    },
  });
}

// ------------------------------------------------------------------------------------------------
// Contracts, people & organisations, threads
// ------------------------------------------------------------------------------------------------

export function useContracts(params: ContractListParams = {}) {
  return useQuery({ queryKey: qk.contracts.list(params), queryFn: () => api.contracts(params), staleTime: MINUTE });
}

export function useUpdateContract() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ContractPatch }) => api.updateContract(id, patch),
    meta: { errorTitle: "Couldn't update the contract" },
    onSuccess: () => invalidateLedger(qc),
  });
}

export function useParties() {
  return useQuery({ queryKey: qk.parties.list(), queryFn: api.parties, staleTime: MINUTE });
}

/**
 * Set the Land a sender is in. The drawer shows it at once; the server recomputed the dates of its letters,
 * so every ledger view refreshes.
 */
export function useUpdateParty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: PartyPatch }) => api.updateParty(id, patch),
    meta: { errorTitle: "Couldn't save their state" },
    onSuccess: (party) => {
      qc.setQueryData<PartyDetail>(qk.parties.detail(party.id), (detail) => (detail ? { ...detail, party } : detail));
      return invalidateLedger(qc);
    },
  });
}

export function useParty(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.parties.detail(id ?? ""),
    queryFn: () => api.party(id!),
    enabled: Boolean(id),
    staleTime: MINUTE,
  });
}

export function useCase(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.cases.detail(id ?? ""),
    queryFn: () => api.case(id!),
    enabled: Boolean(id),
    staleTime: MINUTE,
  });
}

// ------------------------------------------------------------------------------------------------
// Views
// ------------------------------------------------------------------------------------------------

export function useDashboard({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: qk.dashboard, queryFn: api.dashboard, staleTime: 30_000, enabled });
}

/** `GET /numbers` — My numbers (derived from the letters, refreshed with the ledger). */
export function useNumbers() {
  return useQuery({ queryKey: qk.numbers, queryFn: api.numbers, staleTime: MINUTE });
}

/** `GET /week` — the weekly review (Today asks it whether to suggest one). */
export function useWeek(opts: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: qk.week, queryFn: api.week, staleTime: 30_000, enabled: opts.enabled ?? true });
}

/** "Done" at the end of the weekly review: remembered, and the answer is the review afterwards. */
export function useWeekDone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.weekDone,
    meta: { errorTitle: "Couldn't save your weekly review" },
    onSuccess: (week) => {
      qc.setQueryData(qk.week, week);
      void qc.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

/** "Not now" on Today's prompt: it stays away until the session is due again. */
export function useWeekDismiss() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.weekDismiss,
    meta: { errorTitle: "Couldn't hide the weekly review" },
    onSuccess: (week) => qc.setQueryData(qk.week, week),
  });
}

export function useTimeline(from?: string, to?: string) {
  return useQuery({
    queryKey: qk.timeline(from, to),
    queryFn: () => api.timeline(from, to),
    staleTime: MINUTE,
    placeholderData: keepPreviousData,
  });
}

export function useLanes(from?: string, to?: string) {
  return useQuery({
    queryKey: qk.lanes(from, to),
    queryFn: () => api.lanes(from, to),
    staleTime: MINUTE,
    placeholderData: keepPreviousData,
  });
}

// ------------------------------------------------------------------------------------------------
// Ideas & brief
// ------------------------------------------------------------------------------------------------

export function useSuggestions(params: SuggestionListParams = {}) {
  return useQuery({
    queryKey: qk.suggestions.list(params),
    queryFn: () => api.suggestions(params),
    staleTime: 30_000,
  });
}

/** Accept / dismiss ("Not relevant") / snooze ("Remind me in a week") an Idea. */
export function useUpdateSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: SuggestionPatch }) => api.updateSuggestion(id, patch),
    meta: { errorTitle: "Couldn't update the Idea" },
    onSuccess: () => invalidateLedger(qc),
  });
}

/** Start a review (202); its Ideas arrive later with the `suggestions.updated` event. */
export function useRunReview() {
  return useMutation({ mutationFn: () => api.runReview(), meta: { errorTitle: "Couldn't start the review" } });
}

export function useBrief() {
  return useQuery({ queryKey: qk.brief, queryFn: api.brief, staleTime: 5 * MINUTE });
}

export function useRegenerateBrief() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.regenerateBrief(),
    meta: { errorTitle: "Couldn't write a new note" },
    onSuccess: (brief) => qc.setQueryData(qk.brief, brief),
  });
}

// ------------------------------------------------------------------------------------------------
// Ask
// ------------------------------------------------------------------------------------------------

export function useChat(threadId: string | null | undefined) {
  return useQuery({
    queryKey: qk.chat(threadId ?? ""),
    queryFn: () => api.chat(threadId!),
    enabled: Boolean(threadId),
    staleTime: Infinity,
  });
}

export type AskStatus = "idle" | "streaming" | "done" | "error";

export interface AskToolCall {
  name: string;
  input?: Record<string, unknown>;
  /** summary text from the matching tool_result, once it arrived */
  result?: string;
}

export interface AskState {
  status: AskStatus;
  question: string | null;
  /** the answer text so far (may contain `[doc:ID]` citation markers) */
  text: string;
  toolCalls: AskToolCall[];
  citations: SuggestionRef[];
  messageId: string | null;
  threadId: string | null;
  error: string | null;
  events: StreamEvent[];
}

const IDLE_ASK: AskState = {
  status: "idle",
  question: null,
  text: "",
  toolCalls: [],
  citations: [],
  messageId: null,
  threadId: null,
  error: null,
  events: [],
};

/** Pure reducer used by {@link useAsk} (exported for tests). */
export function reduceAsk(state: AskState, ev: StreamEvent): AskState {
  const events = [...state.events, ev];
  switch (ev.type) {
    case "tool_use":
      return { ...state, events, toolCalls: [...state.toolCalls, { name: ev.name ?? "tool", input: ev.input ?? undefined }] };
    case "tool_result": {
      const calls = [...state.toolCalls];
      for (let i = calls.length - 1; i >= 0; i--) {
        if (calls[i].result === undefined && (!ev.name || calls[i].name === ev.name)) {
          calls[i] = { ...calls[i], result: ev.text ?? "" };
          break;
        }
      }
      return { ...state, events, toolCalls: calls };
    }
    case "text":
      return { ...state, events, text: state.text + (ev.text ?? "") };
    case "done":
      return {
        ...state,
        events,
        status: "done",
        citations: ev.citations ?? state.citations,
        messageId: ev.message_id ?? state.messageId,
        threadId: ev.thread_id ?? state.threadId,
      };
    case "error":
      return { ...state, events, status: "error", error: ev.error ?? "Something went wrong." };
    default:
      return state;
  }
}

/**
 * Streamed Ask. `ask(question)` starts a new answer (cancelling a running one); the state updates
 * as tool calls and text arrive. Pass the `threadId` from a previous answer to continue a chat.
 */
export function useAsk() {
  const qc = useQueryClient();
  const [state, setState] = useState<AskState>(IDLE_ASK);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState((s) => (s.status === "streaming" ? { ...s, status: "done" } : s));
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(IDLE_ASK);
  }, []);

  const ask = useCallback(
    async (question: string, threadId?: string | null) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setState({ ...IDLE_ASK, status: "streaming", question, threadId: threadId ?? null });
      let finalThread: string | null = threadId ?? null;
      try {
        for await (const ev of api.ask({ question, thread_id: threadId ?? null }, ctrl.signal)) {
          if (ctrl.signal.aborted) return;
          if (ev.thread_id) finalThread = ev.thread_id;
          setState((s) => reduceAsk(s, ev));
        }
        setState((s) => (s.status === "streaming" ? { ...s, status: "done" } : s));
        if (finalThread) void qc.invalidateQueries({ queryKey: qk.chat(finalThread) });
      } catch (err) {
        if (ctrl.signal.aborted) return;
        const message =
          err instanceof ApiError ? err.message : "The answer was interrupted. Please try again.";
        setState((s) => ({ ...s, status: "error", error: message }));
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
      }
    },
    [qc],
  );

  return { ...state, ask, cancel, reset };
}

// ------------------------------------------------------------------------------------------------
// Letters (drafts)
// ------------------------------------------------------------------------------------------------

export function useDrafts() {
  return useQuery({ queryKey: qk.drafts.list(), queryFn: api.drafts, staleTime: 30_000 });
}

export function useDraft(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.drafts.detail(id ?? ""),
    queryFn: () => api.draft(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

/** Letters drafted about a letter are listed on it (`DocumentDetail.drafts`), so its detail refreshes too. */
export function useCreateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DraftCreate) => api.createDraft(body),
    meta: { errorTitle: "Couldn't draft the letter" },
    onSuccess: (draft) => {
      qc.setQueryData(qk.drafts.detail(draft.id), draft);
      void qc.invalidateQueries({ queryKey: qk.drafts.all });
      void qc.invalidateQueries({ queryKey: qk.documents.all });
    },
  });
}

export function useUpdateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: DraftPatch }) => api.updateDraft(id, patch),
    meta: { errorTitle: "Couldn't save the letter" },
    onSuccess: (draft) => {
      qc.setQueryData(qk.drafts.detail(draft.id), draft);
      void qc.invalidateQueries({ queryKey: qk.drafts.list() });
    },
  });
}

/** "Re-translate": a fresh translation of the letter as it now stands (errors are handled by the caller). */
export function useTranslateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.translateDraft(id),
    meta: { silent: true },
    onSuccess: (draft) => {
      qc.setQueryData(qk.drafts.detail(draft.id), draft);
      void qc.invalidateQueries({ queryKey: qk.drafts.list() });
    },
  });
}

export function useDeleteDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: string | { id: string; keepProofFiles?: boolean }) =>
      typeof args === "string" ? api.deleteDraft(args) : api.deleteDraft(args.id, args.keepProofFiles),
    meta: { errorTitle: "Couldn't delete the letter" },
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: qk.drafts.all }),
        qc.invalidateQueries({ queryKey: qk.documents.all }), // the letter it was about lists it; kept proof files join
        qc.invalidateQueries({ queryKey: qk.waiting }),
      ]),
  });
}

/** Mark a letter as sent (creates a 21-day follow-up to-do). */
export function useMarkDraftSent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & MarkSentRequest) => api.markDraftSent(id, body),
    meta: { errorTitle: "Couldn't mark the letter as sent" },
    onSuccess: () => invalidateLedger(qc),
  });
}

// ------------------------------------------------------------------------------------------------
// Proof of a sent letter, "Waiting for" and call notes
// ------------------------------------------------------------------------------------------------

/** A letter's proof: tracking number, proofs, timeline, what's missing and what it waits for. */
export function useDraftProof(id: string | null | undefined, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.drafts.proof(id ?? ""),
    queryFn: () => api.draftProof(id!),
    enabled: Boolean(id) && (opts.enabled ?? true),
    staleTime: 30_000,
  });
}

/** Every proof write answers the new overview: show it at once, then refresh what derives from it. */
function proofChanged(qc: QueryClient, overview: ProofOverview) {
  qc.setQueryData(qk.drafts.proof(overview.draft_id), overview);
  void qc.invalidateQueries({ queryKey: qk.drafts.detail(overview.draft_id) });
  void qc.invalidateQueries({ queryKey: qk.waiting });
  void qc.invalidateQueries({ queryKey: qk.suggestions.all }); // "Keep the proof" Ideas come and go
  void qc.invalidateQueries({ queryKey: qk.dashboard });
}

/** Save (or with `null` remove) the tracking number. A mistyped check digit fails with the server's reason. */
export function useSetTracking() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, trackingNumber }: { id: string; trackingNumber: string | null }) => api.setTracking(id, { tracking_number: trackingNumber }),
    meta: { errorTitle: "Couldn't save the tracking number" },
    onSuccess: (overview) => proofChanged(qc, overview),
  });
}

export function useAddProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, upload }: { id: string; upload: ProofUpload }) => api.addProof(id, upload),
    meta: { errorTitle: "Couldn't add the proof" },
    onSuccess: (overview) => proofChanged(qc, overview),
  });
}

export function useUpdateProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, proofId, patch }: { id: string; proofId: string; patch: ProofPatch }) => api.updateProof(id, proofId, patch),
    meta: { errorTitle: "Couldn't change the proof" },
    onSuccess: (overview) => proofChanged(qc, overview),
  });
}

export function useRemoveProof() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, proofId }: { id: string; proofId: string }) => api.removeProof(id, proofId),
    meta: { errorTitle: "Couldn't remove the proof" },
    onSuccess: (overview) => proofChanged(qc, overview),
  });
}

/** "It's answered" (with the letter that answered, or `null`) — and its Undo. Closes or reopens the follow-up. */
export function useMarkAnswered() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, docId, answered }: { id: string; docId?: string | null; answered: boolean }) =>
      answered ? api.markAnswered(id, docId ?? null) : api.unmarkAnswered(id),
    meta: { errorTitle: "Couldn't save that" },
    onSuccess: (overview) => {
      proofChanged(qc, overview);
      void qc.invalidateQueries({ queryKey: qk.items.all }); // the follow-up to-do closed or reopened
    },
  });
}

/** Replies, money and callbacks the person is owed (worked out on read by the server). */
export function useWaiting() {
  return useQuery({ queryKey: qk.waiting, queryFn: api.waiting, staleTime: 30_000 });
}

export function useCalls(params: CallListParams, opts: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: qk.calls.list(params), queryFn: () => api.calls(params), staleTime: 30_000, enabled: opts.enabled ?? true });
}

/** Call notes feed "Waiting for" (a dated promise) and the activity log. */
function callsChanged(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: qk.calls.all }),
    qc.invalidateQueries({ queryKey: qk.waiting }),
    qc.invalidateQueries({ queryKey: qk.activity }),
  ]).then(() => undefined);
}

export function useCreateCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CallNoteCreate) => api.createCall(body),
    meta: { errorTitle: "Couldn't save the call note" },
    onSuccess: () => callsChanged(qc),
  });
}

/** Say a call's promise was kept (or take that back). */
export function useUpdateCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, kept }: { id: string; kept: boolean }) => api.updateCall(id, { kept }),
    meta: { errorTitle: "Couldn't update the call note" },
    onSuccess: () => callsChanged(qc),
  });
}

export function useDeleteCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteCall(id),
    meta: { errorTitle: "Couldn't delete the call note" },
    onSuccess: () => callsChanged(qc),
  });
}

// ------------------------------------------------------------------------------------------------
// Calendar, privacy & AI usage, jobs
// ------------------------------------------------------------------------------------------------

/** Call after the user downloaded `calendar.ics` so the "new dates" Idea resets. */
export function useMarkCalendarExported() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.calendarExported(), meta: { errorTitle: "Couldn't note the calendar download" }, onSuccess: () => invalidateLedger(qc) });
}

/**
 * The morning desktop notification: its tool, today's text in each mode, and start at login.
 * `preview: false` (the check for background problems on every page) skips the texts, which the
 * server builds from the agenda.
 */
export function useDesktopReminders({ preview = true, enabled = true }: { preview?: boolean; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["reminders", "desktop", preview ? "preview" : "status"] as const,
    queryFn: () => api.desktopReminders(preview),
    staleTime: 30_000,
    enabled,
  });
}

/** "Send a test notification" (the answer says whether the system showed it, and why not). */
export function useTestDesktopNotification() {
  return useMutation({ mutationFn: (mode: DesktopMode) => api.testDesktopNotification(mode), meta: { errorTitle: "Couldn't send a test notification" } });
}

const BACKUP_INFO_KEY = ["backup", "info"] as const;

/** What an encrypted backup made now would hold (letters, files, size), and when the newest copy was made. */
export function useBackupInfo() {
  return useQuery({ queryKey: BACKUP_INFO_KEY, queryFn: api.backupInfo, staleTime: 30_000 });
}

/**
 * The encrypted backup as a Blob; its errors are shown in the backup dialog, next to the passphrase. Once made, Settings'
 * "Last backup" line, the weekly review's reminder and the privacy log are asked again (the server noted the backup).
 */
export function useDownloadBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ passphrase, signal }: { passphrase: string; signal?: AbortSignal }) => api.downloadBackup(passphrase, signal),
    meta: { silent: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BACKUP_INFO_KEY });
      void qc.invalidateQueries({ queryKey: qk.week });
      void qc.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

const CALENDAR_SYNC_KEY = ["calendar", "sync"] as const;

/** Calendar sync: whether it can be used here, the connected calendar and the last sync. */
export function useCalendarSync(enabled = true) {
  return useQuery({ queryKey: CALENDAR_SYNC_KEY, queryFn: api.calendarSync, staleTime: 30_000, enabled });
}

/** Exactly what each event would contain in `mode` (nothing is sent). */
export function useCalendarSyncPreview(mode: CalendarSyncMode, enabled = true) {
  return useQuery({ queryKey: [...CALENDAR_SYNC_KEY, "preview", mode] as const, queryFn: () => api.calendarSyncPreview(mode), staleTime: 30_000, enabled });
}

/** Find the calendars of an account; errors are shown next to the field they concern (`ApiError.code`). */
export function useDiscoverCalendars() {
  return useMutation({ mutationFn: (body: CalendarSyncFind) => api.discoverCalendars(body), meta: { silent: true } });
}

/**
 * Connect or change the mode; errors are shown next to the field they concern (`ApiError.code`).
 * A connected calendar gets the dates by itself: the "import the calendar file" Idea goes (the
 * ledger's queries, Ideas included, are fetched again).
 */
export function useConnectCalendarSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CalendarSyncConnect) => api.connectCalendarSync(body),
    meta: { silent: true },
    onSuccess: (status) => {
      qc.setQueryData(CALENDAR_SYNC_KEY, status);
      void qc.invalidateQueries({ queryKey: qk.activity });
      void invalidateLedger(qc);
    },
  });
}

/** "Sync now" (the answer's `last_sync` says what happened, errors included). */
export function useRunCalendarSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runCalendarSync(),
    meta: { errorTitle: "Couldn't sync the calendar" },
    onSuccess: (status) => {
      qc.setQueryData(CALENDAR_SYNC_KEY, status);
      void qc.invalidateQueries({ queryKey: qk.activity });
    },
  });
}

/** Forget the calendar (and its app password), removing Ordnung's events first if asked. */
export function useDisconnectCalendarSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (removeEvents: boolean) => api.disconnectCalendarSync(removeEvents),
    meta: { silent: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CALENDAR_SYNC_KEY });
      void qc.invalidateQueries({ queryKey: qk.activity });
      void invalidateLedger(qc); // the calendar file is the way to a calendar again (its Idea may come back)
    },
  });
}

/** The privacy log, newest first; `device`: only what one paired phone did. */
export function useActivity(limit = 100, device: string | null = null) {
  return useQuery({ queryKey: [...qk.activity, limit, device], queryFn: () => api.activity(limit, device), staleTime: 30_000 });
}

export function useUsage() {
  return useQuery({ queryKey: qk.usage, queryFn: api.usage, staleTime: MINUTE });
}

export function useRules() {
  return useQuery({ queryKey: qk.rules, queryFn: api.rules, staleTime: Infinity });
}

export function useJobs(activeOnly = false) {
  return useQuery({ queryKey: [...qk.jobs, activeOnly], queryFn: () => api.jobs(activeOnly), staleTime: 5_000 });
}

// ------------------------------------------------------------------------------------------------
// Phone access (Settings → Phone on the computer; pairing on the phone)
// ------------------------------------------------------------------------------------------------

/** How often Settings → Phone asks again while the pairing dialog is open (the API sends no event for it). */
export const PHONE_POLL_MS = 2_000;

/**
 * Settings → Phone (computer only: on a phone pass `enabled: false`). `poll` asks again every
 * {@link PHONE_POLL_MS} — while the pairing dialog waits for a phone to open the page, pair, or be stopped.
 */
export function usePhone({ enabled = true, poll = false }: { enabled?: boolean; poll?: boolean } = {}) {
  return useQuery({
    queryKey: qk.phone,
    queryFn: api.phone,
    staleTime: 30_000,
    enabled,
    refetchInterval: poll ? PHONE_POLL_MS : false,
  });
}

/** A phone-access answer replaces the status shown; the privacy log has a new line. */
function phoneChanged(qc: QueryClient, status: PhoneStatus) {
  qc.setQueryData(qk.phone, status);
  void qc.invalidateQueries({ queryKey: qk.activity });
}

/** Turn phone access on or off, choose its address or port, or confirm "This is my home network". */
export function useUpdatePhone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (change: PhoneAccessChange) => api.updatePhone(change),
    meta: { errorTitle: "Couldn't change phone access" },
    onSuccess: (status) => phoneChanged(qc, status),
  });
}

/**
 * {@link useUpdatePhone} for the dialog that turns phone access on or moves it to another address: it shows a
 * refusal in place (no toast, which would wait behind it).
 */
export function useChangePhoneAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (change: PhoneAccessChange) => api.updatePhone(change),
    meta: { silent: true },
    onSuccess: (status) => phoneChanged(qc, status),
  });
}

/**
 * A new pairing code: the answer is the only place it appears (keep it in the dialog's state, not in a cache). The
 * pairing dialog shows a refusal itself ("Couldn't make a pairing code"), so no toast.
 */
export function useCreatePhonePairing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.createPhonePairing(),
    meta: { silent: true },
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.phone }),
  });
}

/** Cancel the open code when the dialog closes (quietly: a code nobody cancelled still ends by itself in minutes). */
export function useCancelPhonePairing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelPhonePairing(),
    meta: { silent: true },
    onSettled: () => void qc.invalidateQueries({ queryKey: qk.phone }),
  });
}

/** Remove a paired phone: it is signed out at once (the dialog asking first shows a refusal itself, so no toast). */
export function useRemovePhone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.removePhone(id),
    meta: { silent: true },
    onSuccess: (status) => phoneChanged(qc, status),
  });
}

/**
 * "Start over": phone access off, every phone removed, a new certificate when it is turned on again (its
 * confirmation dialog shows a refusal itself, so no toast).
 */
export function useResetPhone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetPhone(),
    meta: { silent: true },
    onSuccess: (status) => phoneChanged(qc, status),
  });
}

/** On a phone that isn't paired: pair it with the code (the pairing page shows a refusal itself, so no toast). */
export function usePairPhone() {
  return useMutation({ mutationFn: (body: PairRequest) => api.pairPhone(body), meta: { silent: true } });
}

// ------------------------------------------------------------------------------------------------
// Hand-off sync (computer only: Settings → Your computers, the standing-by screen, /join)
// ------------------------------------------------------------------------------------------------

/** How often the sync status is asked again while something is under way (a save, a take-over waiting, a pull). */
export const SYNC_POLL_MS = 3_000;

/** Something is under way that the status follows (the server also says so with `sync.updated`). */
export function syncBusy(status: Pick<SyncStatus, "activity" | "take_over_waiting" | "mode"> | undefined): boolean {
  return Boolean(status && (status.activity !== "idle" || status.take_over_waiting || status.mode === "starting"));
}

/**
 * Hand-off sync's status, answered from the server's memory (it never reads the folder or the password store, so
 * every page may ask). On a phone pass `false`: sync is the computer's (the API refuses it there). Asked again every
 * {@link SYNC_POLL_MS} while something is under way.
 */
export function useSync(enabled = true) {
  return useQuery({
    queryKey: qk.sync,
    queryFn: api.sync,
    staleTime: 30_000,
    enabled,
    refetchInterval: (query) => (syncBusy(query.state.data) ? SYNC_POLL_MS : false),
  });
}

/**
 * This computer's data was just replaced (a take-over, a choice, a change brought in): every cached page is stale,
 * as after "Delete everything" — except health and sync's own status, which say what to show meanwhile.
 */
export function resetAfterReplace(qc: QueryClient): void {
  qc.removeQueries({ predicate: (q) => !["health", "sync"].includes(String(q.queryKey[0])) });
  void qc.invalidateQueries();
}

/** A sync answer replaces the status shown; the privacy log may have a new line. */
function syncChanged(qc: QueryClient, status: SyncStatus) {
  qc.setQueryData(qk.sync, status);
  void qc.invalidateQueries({ queryKey: qk.activity });
}

/** The answer of a take-over or a choice: in use here now, so what the pages show came from the other computer. */
function tookOver(qc: QueryClient, status: SyncStatus) {
  if (status.mode === "in_use") resetAfterReplace(qc);
  qc.setQueryData(qk.sync, status);
}

/** What a folder would be for sync (nothing is written); a refusal is shown under the folder field. */
export function useInspectSyncFolder() {
  return useMutation({ mutationFn: (folder: string) => api.inspectSyncFolder(folder), meta: { silent: true } });
}

/**
 * Set up a new sync folder or join one; a refusal is shown next to the field it concerns (`ApiError.code`). Joining
 * brings the other computer's Ordnung over (the profile, settings and ledger are asked again).
 */
export function useConnectSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SyncConnect) => api.connectSync(body),
    meta: { silent: true },
    onSuccess: (result) => {
      if (result.choice) return; // nothing is connected yet: the choice comes first
      syncChanged(qc, result.status);
      void qc.invalidateQueries({ queryKey: qk.profile });
      void qc.invalidateQueries({ queryKey: qk.settings });
      void invalidateLedger(qc);
    },
  });
}

/** Rename this computer, answer a problem or dismiss a notice (refusals are shown where it was asked). */
export function useUpdateSync() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (change: SyncChange) => api.updateSync(change), meta: { silent: true }, onSuccess: (status) => syncChanged(qc, status) });
}

/** Disconnect this computer (its dialog shows a refusal, and asks again while no other computer has its latest changes). */
export function useDisconnectSync() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: SyncDisconnect) => api.disconnectSync(body), meta: { silent: true }, onSuccess: (status) => syncChanged(qc, status) });
}

/**
 * "Use Ordnung here": in use here now (every page loads again: the data came from the other computer), waiting
 * until everything has arrived, or the choice to make. A refusal is shown on the standing-by screen.
 */
export function useTakeOver() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: SyncUseHere = {}) => api.takeOver(body), meta: { silent: true }, onSuccess: (status) => tookOver(qc, status) });
}

/** Which computer's Ordnung to keep (the choice dialog shows a refusal itself). */
export function useChooseSync() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (keep: number) => api.chooseSync(keep), meta: { silent: true }, onSuccess: (status) => tookOver(qc, status) });
}

/** "Save now" (and, with `hand_over`, stand by). */
export function useSaveSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SyncSave = {}) => api.saveSync(body),
    meta: { errorTitle: "Couldn't save to the sync folder" },
    onSuccess: (status) => syncChanged(qc, status),
  });
}

/** The passphrase typed again (a wrong one is said under its field). */
export function useSyncPassphrase() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (passphrase: string) => api.syncPassphrase(passphrase), meta: { silent: true }, onSuccess: (status) => syncChanged(qc, status) });
}

/** "Fill it again from this computer" (an emptied folder; the problem's callout shows a refusal). */
export function useRefillSync() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.refillSync(), meta: { silent: true }, onSuccess: (status) => syncChanged(qc, status) });
}

/** Forget a lost computer (its dialog shows a refusal). */
export function useForgetComputer() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (key: number) => api.forgetComputer(key), meta: { silent: true }, onSuccess: (status) => syncChanged(qc, status) });
}

/** A kept copy as a file (the browser saves it). */
export function useDownloadKept() {
  return useMutation({ mutationFn: (name: string) => api.downloadKept(name), meta: { errorTitle: "Couldn't download the saved copy" } });
}

/** Delete a kept copy for good. */
export function useDeleteKept() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteKept(name),
    meta: { errorTitle: "Couldn't delete the saved copy" },
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.sync }),
  });
}

// ------------------------------------------------------------------------------------------------
// Demo
// ------------------------------------------------------------------------------------------------

export function useTour(enabled = true) {
  return useQuery({ queryKey: qk.tour, queryFn: api.tour, staleTime: Infinity, enabled });
}

export function useUpdateTour() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: TourPatch) => api.updateTour(patch),
    meta: { errorTitle: "Couldn't update the tour" },
    onSuccess: (tour) => qc.setQueryData(qk.tour, tour),
  });
}

/**
 * The demo's suggested Ask questions, served by the backend so they always match its recordings — none once
 * the letters or to-dos changed since the demo started (the recorded answers no longer fit), so a ledger key.
 */
export function useDemoQuestions(enabled = true) {
  return useQuery({ queryKey: qk.questions, queryFn: api.demoQuestions, enabled });
}

export function useMailTray(enabled = true) {
  return useQuery({ queryKey: qk.mail, queryFn: api.mailTray, staleTime: 30_000, enabled });
}

/** Open a letter from the demo's New-mail tray (it is then processed live; watch `useEvents`). */
export function useOpenMail() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.openMail(id),
    meta: { errorTitle: "Couldn't open the letter" },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.mail });
      void invalidateLedger(qc);
    },
  });
}
