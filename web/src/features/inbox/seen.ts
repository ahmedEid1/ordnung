/**
 * Which letters the person has opened (their page was shown): the Inbox's "New" badge on a letter
 * read from New mail clears once it was looked at. Kept in this browser (localStorage), newest
 * last, capped; works without storage too (then only until a reload).
 */
import { useEffect, useSyncExternalStore } from "react";

const STORAGE_KEY = "ordnung.seen-letters";
/** Letters remembered (oldest dropped first): only recent New-mail letters need it. */
const MAX_SEEN = 200;

let ids: string[] | null = null;
let snapshot: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();

function load(): string[] {
  if (ids) return ids;
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    ids = Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    ids = [];
  }
  snapshot = new Set(ids);
  return ids;
}

function emit() {
  listeners.forEach((fn) => fn());
}

/** Note that a letter's page was shown. */
export function markLetterSeen(id: string): void {
  const current = load();
  if (snapshot.has(id)) return;
  ids = [...current, id].slice(-MAX_SEEN);
  snapshot = new Set(ids);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // private mode / storage full: remembered until a reload
  }
  emit();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  // another tab opened a letter
  const onStorage = (e: StorageEvent) => {
    if (e.key !== STORAGE_KEY) return;
    ids = null;
    load();
    fn();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

function getSnapshot(): ReadonlySet<string> {
  load();
  return snapshot;
}

/** The ids of the letters whose page was shown. */
export function useSeenLetters(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Mark a letter as seen while its page is on screen (pass null while it isn't ready). */
export function useMarkLetterSeen(id: string | null | undefined): void {
  useEffect(() => {
    if (id) markLetterSeen(id);
  }, [id]);
}

/** Test hook: forget everything. */
export function resetSeenLetters(): void {
  ids = [];
  snapshot = new Set();
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // nothing stored
  }
  emit();
}
