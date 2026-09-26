/**
 * Where a detail page ("/documents/…") was opened from — Today, Timeline, Ask, Contracts… — so its
 * breadcrumb and phone back button say "Back to Today" instead of always "Inbox".
 *
 * Every link and `navigate()` in the app counts without passing anything: the shell records the
 * last section page the person was on, and pins it to each detail page's history entry
 * (`location.key`, kept in sessionStorage), so Back/Forward and a reload keep the same parent.
 */
import { useEffect, useSyncExternalStore } from "react";
import { useLocation, type Location } from "react-router";
import { sectionAt, type NavItem } from "./nav";

const STORAGE_KEY = "ordnung.nav-origin";
/** History entries remembered (oldest dropped first). */
const MAX_ENTRIES = 50;
/** The first entry of a page load has this key; it would collide across loads, so it is never pinned. */
const INITIAL_KEY = "default";

/** The last section page visited (pathname + search). */
let lastSection: string | null = null;
let byKey: Record<string, string> | null = null;
const listeners = new Set<() => void>();

function entries(): Record<string, string> {
  if (byKey) return byKey;
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}");
    byKey = parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    byKey = {};
  }
  return byKey;
}

function save(next: Record<string, string>) {
  const keys = Object.keys(next);
  byKey = keys.length > MAX_ENTRIES ? Object.fromEntries(keys.slice(-MAX_ENTRIES).map((k) => [k, next[k]!])) : next;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(byKey));
  } catch {
    // private mode / storage full: the parent still works until a reload
  }
}

/** Note a location the person reached (the shell calls this once per navigation). */
export function recordLocation(location: Pick<Location, "pathname" | "search" | "key">): void {
  if (sectionAt(location.pathname)) {
    lastSection = `${location.pathname}${location.search}`;
  } else if (location.key !== INITIAL_KEY && lastSection && !entries()[location.key]) {
    save({ ...entries(), [location.key]: lastSection });
  } else return;
  listeners.forEach((fn) => fn());
}

/** Test hook: forget everything. */
export function resetOrigins(): void {
  lastSection = null;
  byKey = {};
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Records every navigation (mount once, in the app shell). */
export function useRecordOrigin(): void {
  const location = useLocation();
  useEffect(() => recordLocation(location), [location]);
}

export interface Crumb {
  to: string;
  label: string;
}

/**
 * The section this page was opened from, as a breadcrumb parent — or `fallback` (its usual home)
 * when it was opened directly.
 *
 * @example const parent = useOriginParent({ to: "/inbox", label: "Inbox" })
 */
export function useOriginParent(fallback: Crumb): Crumb {
  const { key } = useLocation();
  // before the shell pins this entry (its effect runs after the page renders), the last section is it
  const from = useSyncExternalStore(
    subscribe,
    () => entries()[key] ?? (key === INITIAL_KEY ? null : lastSection),
    () => null,
  );
  const section: NavItem | undefined = from ? sectionAt(from.split("?")[0]!) : undefined;
  return from && section ? { to: from, label: section.label } : fallback;
}
