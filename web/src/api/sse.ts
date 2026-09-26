/**
 * Live updates from `GET /api/events` (Server-Sent Events).
 *
 * One shared EventSource per app (mounted by `useEventsConnection()` in the app shell). It
 * invalidates the right queries when the backend reports changes, keeps the latest job progress
 * per document (for the upload stepper) and the "Claude paused" state. Auto-reconnects with
 * backoff; after a reconnect everything ledger-related is refetched in case events were missed. A
 * connection that stays lost asks `/health`, so the app says when Ordnung stopped answering (and
 * "Back online" once it answers again — see `app/queryClient.ts`).
 *
 * Components read state with {@link useEvents} / {@link useJobProgress} and can react to raw events
 * with {@link useServerEvent}.
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { invalidateLedger, qk } from "./hooks";
import { apiPath } from "./client";
import type { JobProgressEvent, JobStatus, LlmPausedEvent, ServerEvent, ServerEventType } from "./types";

export interface JobProgress extends JobProgressEvent {
  /** ms timestamp of the first event seen for this document */
  startedAt: number;
  /** ms timestamp of the latest event */
  updatedAt: number;
}

export interface EventsState {
  connected: boolean;
  /** latest job progress per document id */
  jobs: Record<string, JobProgress>;
  /** set while the AI worker is paused (rate limit); cleared once `until` has passed */
  paused: LlmPausedEvent | null;
}

/** Every live event the backend publishes (keys of the generated `ServerEvents` schema). */
const EVENT_TYPES = [
  "job.progress",
  "document.processed",
  "document.updated",
  "document.deleted",
  "item.updated",
  "contract.updated",
  "suggestions.updated",
  "review.failed",
  "brief.updated",
  "day.changed",
  "llm.paused",
  "llm.resumed",
  "profile.updated",
  "draft.created",
  "draft.sent",
  "demo.mail",
] as const satisfies readonly ServerEventType[];

// compile-time: the list above names every event of the API (fails when the backend adds one)
type MissingEvents = Exclude<ServerEventType, (typeof EVENT_TYPES)[number]>;
const everyEvent: [MissingEvents] extends [never] ? true : MissingEvents = true;
void everyEvent;

/** Where the progress of a job is kept: its document (the upload stepper), else the job itself. */
const jobKey = (ev: JobProgressEvent) => ev.doc_id ?? ev.job_id ?? "job";

// ------------------------------------------------------------------------------------------------
// Store
// ------------------------------------------------------------------------------------------------

let state: EventsState = { connected: false, jobs: {}, paused: null };
const subscribers = new Set<() => void>();
const eventListeners = new Set<(ev: ServerEvent) => void>();

function setState(update: (s: EventsState) => EventsState) {
  state = update(state);
  subscribers.forEach((fn) => fn());
}

function subscribe(fn: () => void) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

const getSnapshot = () => state;

/** Remove a finished job from the progress list (e.g. after the toast was dismissed). */
export function dismissJob(docId: string): void {
  setState((s) => {
    if (!(docId in s.jobs)) return s;
    const jobs = { ...s.jobs };
    delete jobs[docId];
    return { ...s, jobs };
  });
}

/** Record progress locally (used right after an upload so the stepper appears instantly). */
export function seedJob(ev: JobProgressEvent): void {
  applyJobProgress(ev);
}

function applyJobProgress(ev: JobProgressEvent) {
  const key = jobKey(ev);
  const now = Date.now();
  setState((s) => {
    const prev = s.jobs[key];
    const next: JobProgress = { ...ev, startedAt: prev?.startedAt ?? now, updatedAt: now };
    return { ...s, jobs: { ...s.jobs, [key]: next } };
  });
}

// ------------------------------------------------------------------------------------------------
// Dispatch
// ------------------------------------------------------------------------------------------------

const FINAL: JobStatus[] = ["done", "failed"];

/** Apply one server event: update the store and invalidate affected queries. Exported for tests. */
export function handleServerEvent(qc: QueryClient, ev: ServerEvent): void {
  switch (ev.type) {
    case "job.progress": {
      const key = jobKey(ev.data);
      const isNew = !(key in state.jobs);
      applyJobProgress(ev.data);
      if (FINAL.includes(ev.data.status)) {
        void invalidateLedger(qc);
        void qc.invalidateQueries({ queryKey: qk.mail });
      } else if (isNew) {
        void qc.invalidateQueries({ queryKey: qk.documents.all });
      }
      break;
    }
    case "document.processed":
      void invalidateLedger(qc);
      void qc.invalidateQueries({ queryKey: qk.mail });
      break;
    case "suggestions.updated":
      void qc.invalidateQueries({ queryKey: qk.suggestions.all });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
      break;
    case "item.updated":
      void qc.invalidateQueries({ queryKey: qk.items.all });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
      void qc.invalidateQueries({ queryKey: ["timeline"] });
      void qc.invalidateQueries({ queryKey: ["lanes"] });
      break;
    case "day.changed":
      void qc.invalidateQueries({ queryKey: qk.health });
      void invalidateLedger(qc);
      break;
    case "document.updated":
    case "document.deleted":
    case "contract.updated":
    case "draft.sent":
      void invalidateLedger(qc);
      break;
    case "draft.created":
      void qc.invalidateQueries({ queryKey: qk.drafts.all });
      void qc.invalidateQueries({ queryKey: qk.documents.all }); // listed on the letter it is about
      break;
    case "brief.updated":
      void qc.invalidateQueries({ queryKey: qk.brief });
      break;
    case "profile.updated":
      void qc.invalidateQueries({ queryKey: qk.profile });
      break;
    case "demo.mail":
      void qc.invalidateQueries({ queryKey: qk.mail });
      void qc.invalidateQueries({ queryKey: qk.documents.all });
      break;
    case "llm.paused":
      setState((s) => ({ ...s, paused: ev.data }));
      break;
    case "llm.resumed":
      setState((s) => (s.paused ? { ...s, paused: null } : s));
      break;
    case "review.failed":
      break; // shown by whoever started the review (useServerEvent)
  }
  eventListeners.forEach((fn) => fn(ev));
}

// ------------------------------------------------------------------------------------------------
// Connection
// ------------------------------------------------------------------------------------------------

let refCount = 0;
let source: EventSource | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let pauseTimer: ReturnType<typeof setTimeout> | null = null;
let backoff = 1000;
let everConnected = false;
let offlineTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * A dropped connection that hasn't come back after this long asks `/health` again: if Ordnung
 * doesn't answer, the query client's "Can't reach Ordnung" notice shows (a restart stays quiet).
 */
export const OFFLINE_GRACE_MS = 3000;

function clearOfflineTimer() {
  if (offlineTimer) clearTimeout(offlineTimer);
  offlineTimer = null;
}

function open(qc: QueryClient) {
  if (typeof EventSource === "undefined") return;
  const es = new EventSource(apiPath("/events"), { withCredentials: true });
  source = es;
  es.onopen = () => {
    backoff = 1000;
    clearOfflineTimer();
    if (everConnected) {
      // we may have missed events while offline; a successful refetch also says "Back online"
      void invalidateLedger(qc);
      void qc.invalidateQueries({ queryKey: qk.health });
    }
    everConnected = true;
    setState((s) => ({ ...s, connected: true }));
  };
  es.onerror = () => {
    if (state.connected && !offlineTimer) {
      offlineTimer = setTimeout(() => {
        offlineTimer = null;
        if (!state.connected && refCount > 0) void qc.refetchQueries({ queryKey: qk.health });
      }, OFFLINE_GRACE_MS);
    }
    setState((s) => (s.connected ? { ...s, connected: false } : s));
    if (es.readyState === EventSource.CLOSED && source === es) {
      es.close();
      source = null;
      scheduleReconnect(qc);
    }
  };
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (e) => {
      let data: unknown;
      try {
        data = JSON.parse((e as MessageEvent<string>).data || "{}");
      } catch {
        return;
      }
      handleServerEvent(qc, { type, data } as ServerEvent);
    });
  }
}

function scheduleReconnect(qc: QueryClient) {
  if (retryTimer || refCount === 0) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    if (refCount > 0 && !source) open(qc);
  }, backoff);
  backoff = Math.min(backoff * 2, 30_000);
}

/** Open the shared connection (ref-counted). Returns a disconnect function. */
export function connectEvents(qc: QueryClient): () => void {
  refCount += 1;
  if (refCount === 1 && !source) open(qc);
  return () => {
    refCount -= 1;
    if (refCount === 0) {
      source?.close();
      source = null;
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = null;
      clearOfflineTimer();
      setState((s) => ({ ...s, connected: false }));
    }
  };
}

// ------------------------------------------------------------------------------------------------
// Hooks
// ------------------------------------------------------------------------------------------------

/** Mount once (the app shell does this) to keep the live connection open. */
export function useEventsConnection(): void {
  const qc = useQueryClient();
  useEffect(() => connectEvents(qc), [qc]);

  // clear the paused banner automatically once `until` has passed
  const paused = useSyncExternalStore(subscribe, () => state.paused, () => null);
  useEffect(() => {
    if (pauseTimer) clearTimeout(pauseTimer);
    if (!paused) return;
    const ms = new Date(paused.until).getTime() - Date.now();
    const clear = () => setState((s) => ({ ...s, paused: null }));
    if (!Number.isFinite(ms) || ms <= 0) {
      clear();
      return;
    }
    pauseTimer = setTimeout(clear, Math.min(ms, 2_147_000_000));
    return () => {
      if (pauseTimer) clearTimeout(pauseTimer);
    };
  }, [paused]);
}

/** Live state: connection, job progress per document, paused banner. */
export function useEvents(): EventsState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Latest progress of the job processing `docId` (undefined when none is known). */
export function useJobProgress(docId: string | null | undefined): JobProgress | undefined {
  const s = useEvents();
  return docId ? s.jobs[docId] : undefined;
}

/** Run `handler` for every server event of `type` (e.g. show "A new Idea arrived"). */
export function useServerEvent<T extends ServerEventType>(
  type: T,
  handler: (data: Extract<ServerEvent, { type: T }>["data"]) => void,
): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    const fn = (ev: ServerEvent) => {
      if (ev.type === type) (ref.current as (data: unknown) => void)(ev.data);
    };
    eventListeners.add(fn);
    return () => {
      eventListeners.delete(fn);
    };
  }, [type]);
}

/** Test helper: reset the module state. */
export function __resetEventsForTests(): void {
  clearOfflineTimer();
  state = { connected: false, jobs: {}, paused: null };
  subscribers.clear();
  eventListeners.clear();
}
