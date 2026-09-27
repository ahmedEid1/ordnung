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
import { api, type UploadOptions } from "./endpoints";
import { ApiError } from "./client";
import type {
  CalendarSyncConnect,
  CalendarSyncFind,
  CalendarSyncMode,
  ContractListParams,
  ContractPatch,
  DesktopMode,
  DocumentListParams,
  DocumentPatch,
  DraftCreate,
  DraftPatch,
  ItemCreate,
  ItemListParams,
  ItemPatch,
  MarkSentRequest,
  OnboardingRequest,
  ProfilePatch,
  SettingsPatch,
  StreamEvent,
  SuggestionListParams,
  SuggestionPatch,
  SuggestionRef,
  TourPatch,
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
  },
  activity: ["activity"] as const,
  usage: ["usage"] as const,
  rules: ["rules"] as const,
  jobs: ["jobs"] as const,
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
  qk.suggestions.all,
  qk.brief,
  qk.drafts.all,
  qk.activity,
  qk.jobs,
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
    queryFn: ({ signal }) => api.health(withTimeout(signal, HEALTH_TIMEOUT_MS)),
    staleTime: 5 * MINUTE,
    retry: 1,
  });
}

/** "Run check" (`GET /health?probe=1`): the doctor's checks plus one tiny live call; the answer
 * replaces the cached health. At most once a minute (the API answers 429 otherwise). */
export function useProbeHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.probeHealth(),
    meta: { errorTitle: "Couldn't run the check" },
    onSuccess: (health) => qc.setQueryData(qk.health, health),
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

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: api.settings, staleTime: 10 * MINUTE });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (s: SettingsPatch) => api.updateSettings(s),
    meta: { errorTitle: "Couldn't save your settings" },
    onSuccess: (settings) => qc.setQueryData(qk.settings, settings),
  });
}

/** "Delete everything": wipes the data folder; afterwards every cached query is stale. */
export function useDeleteEverything() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.deleteEverything(),
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
    onSuccess: () => invalidateLedger(qc),
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

export function useDashboard() {
  return useQuery({ queryKey: qk.dashboard, queryFn: api.dashboard, staleTime: 30_000 });
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
    mutationFn: (id: string) => api.deleteDraft(id),
    meta: { errorTitle: "Couldn't delete the letter" },
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: qk.drafts.all }),
        qc.invalidateQueries({ queryKey: qk.documents.all }), // the letter it was about lists it
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
// Calendar, privacy & AI usage, jobs
// ------------------------------------------------------------------------------------------------

/** Call after the user downloaded `calendar.ics` so the "new dates" Idea resets. */
export function useMarkCalendarExported() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.calendarExported(), meta: { errorTitle: "Couldn't note the calendar download" }, onSuccess: () => invalidateLedger(qc) });
}

/** The morning desktop notification: its tool, today's text in each mode, and start at login. */
export function useDesktopReminders() {
  return useQuery({ queryKey: ["reminders", "desktop"] as const, queryFn: api.desktopReminders, staleTime: 30_000 });
}

/** "Send a test notification" (the answer says whether the system showed it, and why not). */
export function useTestDesktopNotification() {
  return useMutation({ mutationFn: (mode: DesktopMode) => api.testDesktopNotification(mode), meta: { errorTitle: "Couldn't send a test notification" } });
}

/** What an encrypted backup made now would hold (letters, files, size). */
export function useBackupInfo() {
  return useQuery({ queryKey: ["backup", "info"] as const, queryFn: api.backupInfo, staleTime: 30_000 });
}

/** The encrypted backup as a Blob; its errors are shown in the backup dialog, next to the passphrase. */
export function useDownloadBackup() {
  return useMutation({
    mutationFn: ({ passphrase, signal }: { passphrase: string; signal?: AbortSignal }) => api.downloadBackup(passphrase, signal),
    meta: { silent: true },
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

export function useActivity(limit = 100) {
  return useQuery({ queryKey: [...qk.activity, limit], queryFn: () => api.activity(limit), staleTime: 30_000 });
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

/** The demo's suggested Ask questions, served by the backend so they always match its recordings. */
export function useDemoQuestions(enabled = true) {
  return useQuery({ queryKey: qk.questions, queryFn: api.demoQuestions, staleTime: Infinity, enabled });
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
