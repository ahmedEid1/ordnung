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
 * A pause and a letter's reason to wait are said once, when they start: on connecting (a reload, a
 * new tab) the server sends a pause under way first, and the queue (`GET /jobs`) says which letters
 * wait and why — see {@link seedFromQueue}.
 *
 * Components read state with {@link useEvents} / {@link useJobProgress} and can react to raw events
 * with {@link useServerEvent}.
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { invalidateLedger, qk, resetAfterReplace } from "./hooks";
import { apiPath } from "./client";
import { api } from "./endpoints";
import type { Job, JobProgressEvent, JobStatus, LlmPausedEvent, ServerEvent, ServerEventType } from "./types";

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
  /**
   * set while the AI worker is paused: a usage limit (cleared once `until` has passed), or Claude not
   * installed or not signed in (`until` empty: cleared when `llm.resumed` says Claude is ready)
   */
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
  "folder.updated",
  "sync.updated",
] as const satisfies readonly ServerEventType[];

// compile-time: the list above names every event of the API (fails when the backend adds one)
type MissingEvents = Exclude<ServerEventType, (typeof EVENT_TYPES)[number]>;
const everyEvent: [MissingEvents] extends [never] ? true : MissingEvents = true;
void everyEvent;

/** Where the progress of a job is kept: its document (the upload stepper), else the job itself. */
const jobKey = (ev: JobProgressEvent) => ev.doc_id ?? ev.job_id ?? "job";

/** How a job's `waiting_reason` starts while its letter waits for Claude (`WAITING_FOR_CLAUDE` in `ingest/worker.py`). */
export const WAITING_FOR_CLAUDE = "Waiting for Claude";

/**
 * Why a letter waits for Claude — not installed or not signed in, or its usage limit — from its job's
 * progress: "Waiting for Claude: …"; null while it doesn't.
 */
/**
 * A wait for Claude Code itself — not installed or not signed in — that only a Claude check ends (a usage limit
 * ends by itself, and the server says so while it runs): the reason that may show the banner on connecting.
 */
const CLAUDE_NOT_READY = `${WAITING_FOR_CLAUDE}: Claude Code isn't `;

export function claudeWaitReason(job: Pick<JobProgressEvent, "status" | "waiting_reason"> | undefined): string | null {
  const reason = job?.status === "queued" ? job.waiting_reason : null;
  return reason?.startsWith(WAITING_FOR_CLAUDE) ? reason : null;
}

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

/**
 * Record progress locally (used right after an upload or a "Read again" so the stepper appears
 * instantly). A seed never overwrites what the server already reported for the same job: callers
 * seed in their mutation's `onSuccess`, which runs after the ledger refetch, and by then a short
 * reading may have sent its final `done` or `failed` event (the card would otherwise stay on
 * "Opening the file…" for good).
 */
export function seedJob(ev: JobProgressEvent): void {
  const prev = state.jobs[jobKey(ev)];
  if (prev && ev.job_id != null && prev.job_id === ev.job_id) return;
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

/**
 * On connecting, what the queue says (`GET /jobs`): the letters that wait, with why — the server says it only
 * when a letter starts waiting, so a reload or a new tab showed "Opening the file…" for good (final check,
 * F-M2). A letter heard of since the connection opened (`openedAt`) keeps what it heard. A letter waiting for
 * Claude shows the banner too when the server sent no pause first (it sends one under way): right after a
 * restart, before the worker tried the letter again — `llm.paused` or `llm.resumed` follows that try.
 * Exported for tests.
 */
export async function seedFromQueue(openedAt: number): Promise<void> {
  let jobs: Job[];
  try {
    jobs = await api.jobs(true);
  } catch {
    return; // the live events still say what changes
  }
  let forClaude = false;
  for (const job of jobs) {
    if (!job.doc_id || job.status !== "queued" || !job.waiting_reason) continue;
    if ((state.jobs[job.doc_id]?.updatedAt ?? -Infinity) >= openedAt) continue;
    const seed: JobProgressEvent = { job_id: job.id, doc_id: job.doc_id, stage: "intake", progress: 0, status: "queued", waiting_reason: job.waiting_reason };
    applyJobProgress(seed);
    forClaude ||= job.waiting_reason.startsWith(CLAUDE_NOT_READY);
  }
  if (forClaude) setState((s) => (s.paused ? s : { ...s, paused: { until: "", reason: "" } }));
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
      // a letter's detail carries its to-dos and their GiroCodes (an amount changed elsewhere)
      void qc.invalidateQueries({ queryKey: qk.documents.all });
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
    case "folder.updated":
      // the watcher started, stopped or brought in a file (a waiting one sends no job events)
      void qc.invalidateQueries({ queryKey: qk.folder });
      if (ev.data.doc_id) void invalidateLedger(qc);
      break;
    case "sync.updated":
      // hand-off sync's status changed; `replaced`: this computer's data was just replaced (a take-over, a
      // choice, a late change brought in), so every page loads again — health and the status itself stay
      if (ev.data.replaced) resetAfterReplace(qc);
      else void qc.invalidateQueries({ queryKey: qk.sync });
      break;
    case "llm.paused":
      setState((s) => ({ ...s, paused: ev.data }));
      void qc.invalidateQueries({ queryKey: qk.health }); // Claude's status (Settings, the upload dialog)
      break;
    case "llm.resumed":
      setState((s) => (s.paused ? { ...s, paused: null } : s));
      void qc.invalidateQueries({ queryKey: qk.health });
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
    void seedFromQueue(Date.now());
    if (everConnected) {
      // we may have missed events while offline; a successful refetch also says "Back online"
      void invalidateLedger(qc);
      void qc.invalidateQueries({ queryKey: qk.health });
      void qc.invalidateQueries({ queryKey: qk.sync }); // another computer may have taken over meanwhile
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

  // clear the paused banner automatically once `until` has passed (waiting for Claude has no end)
  const paused = useSyncExternalStore(subscribe, () => state.paused, () => null);
  useEffect(() => {
    if (pauseTimer) clearTimeout(pauseTimer);
    if (!paused?.until) return;
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
