/**
 * Browser notifications while Ordnung is open (SPEC §12) — opt-in per browser (Settings →
 * Reminders). Pure helpers: what deserves a notification today, its wording, and the per-browser
 * memory (localStorage) that shows each one at most once a day.
 *
 * What is notified: open to-dos & dates due (or to be posted) today or tomorrow, and urgent Ideas
 * whose date has passed. Nothing leaves the computer — the browser shows the notification.
 */
import { addDays, parseISO } from "date-fns";
import type { Item, Suggestion } from "@/api/types";
import { formatMoney, toISODate } from "@/lib/format";

/** localStorage: `true` once the person turned notifications on in this browser. */
export const NOTIFY_ENABLED_KEY = "ordnung.notify.enabled";
/** localStorage: `{ [key]: day }` — what was shown on which day (kept a week). */
export const NOTIFY_SENT_KEY = "ordnung.notify.sent";
/** More than this at once become one summary notification. */
export const MAX_AT_ONCE = 3;
const KEEP_DAYS = 7;

export type NotifyPermission = "unsupported" | "default" | "granted" | "denied";

export interface PlannedNotification {
  /** Dedupe key (`item:ID` / `idea:ID`): shown at most once per day. */
  key: string;
  title: string;
  body: string;
  /** In-app link opened when the notification is clicked. */
  href: string;
}

// ------------------------------------------------------------------------------------------------
// Permission & preference
// ------------------------------------------------------------------------------------------------

/** The Notification API's permission, or `unsupported` (old browsers, some in-app webviews). */
export function notifyPermission(): NotifyPermission {
  if (typeof window === "undefined" || typeof window.Notification === "undefined") return "unsupported";
  const p = window.Notification.permission;
  return p === "granted" || p === "denied" ? p : "default";
}

export function readNotifyEnabled(): boolean {
  try {
    return localStorage.getItem(NOTIFY_ENABLED_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeNotifyEnabled(on: boolean): void {
  try {
    if (on) localStorage.setItem(NOTIFY_ENABLED_KEY, "true");
    else localStorage.removeItem(NOTIFY_ENABLED_KEY);
  } catch {
    /* storage unavailable: notifications simply stay off */
  }
}

// ------------------------------------------------------------------------------------------------
// Once a day per item
// ------------------------------------------------------------------------------------------------

type SentLog = Record<string, string>;

export function readSentLog(): SentLog {
  try {
    const raw = JSON.parse(localStorage.getItem(NOTIFY_SENT_KEY) ?? "{}") as unknown;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as SentLog) : {};
  } catch {
    return {};
  }
}

/** Remember `keys` as shown on `today` (entries older than a week are dropped). */
export function recordSent(keys: string[], today: string): void {
  const cutoff = toISODate(addDays(parseISO(today), -KEEP_DAYS));
  const log = Object.fromEntries(Object.entries(readSentLog()).filter(([, day]) => day >= cutoff));
  for (const key of keys) log[key] = today;
  try {
    localStorage.setItem(NOTIFY_SENT_KEY, JSON.stringify(log));
  } catch {
    /* storage full or blocked: at worst a notification repeats */
  }
}

/** The planned notifications not yet shown today. */
export function notYetShown(planned: PlannedNotification[], today: string, log: SentLog = readSentLog()): PlannedNotification[] {
  return planned.filter((n) => log[n.key] !== today);
}

// ------------------------------------------------------------------------------------------------
// What to notify
// ------------------------------------------------------------------------------------------------

function itemHref(i: Pick<Item, "doc_id">): string {
  return i.doc_id ? `/documents/${encodeURIComponent(i.doc_id)}` : "/";
}

function itemBody(i: Item): string {
  const money = i.amount !== null && i.amount !== undefined ? formatMoney(i.amount, { currency: i.currency ?? "EUR" }) : null;
  const parts = [i.action?.trim() || null, money];
  return parts.filter(Boolean).join(" · ") || "Open Ordnung to see the details.";
}

/**
 * Open to-dos & dates due — or to be posted — today or tomorrow, and critical Ideas whose date has
 * passed; most urgent first.
 */
export function planNotifications(items: Item[], ideas: Suggestion[], today: string): PlannedNotification[] {
  const tomorrow = toISODate(addDays(parseISO(today), 1));
  const soon = (d: string | null | undefined): "today" | "tomorrow" | null => (d === today ? "today" : d === tomorrow ? "tomorrow" : null);
  const out: (PlannedNotification & { rank: string })[] = [];

  for (const i of items) {
    if (i.status !== "open") continue;
    const post = soon(i.send_by);
    const due = soon(i.due_date);
    if (!post && !due) continue;
    // "post by" comes first: it is the earlier date to act on
    const when = post ?? due!;
    const verb = post ? "Post by" : i.kind === "appointment" ? "" : "Due";
    const title = verb ? `${verb} ${when}: ${i.title}` : `${when === "today" ? "Today" : "Tomorrow"}: ${i.title}`;
    out.push({ key: `item:${i.id}`, title, body: itemBody(i), href: itemHref(i), rank: `${when === "today" ? 0 : 1}${post ? 0 : 1}` });
  }

  for (const s of ideas) {
    if (s.priority !== "critical" || s.status !== "new" || !s.due_date || s.due_date >= today) continue;
    const firstSentence = s.body.split(/(?<=[.!?])\s/)[0] ?? s.body;
    out.push({ key: `idea:${s.id}`, title: `Overdue: ${s.title}`, body: firstSentence, href: "/", rank: "00" });
  }

  return out.sort((a, b) => a.rank.localeCompare(b.rank) || a.title.localeCompare(b.title)).map(({ rank: _rank, ...n }) => n);
}

/**
 * What to actually show: up to {@link MAX_AT_ONCE} notifications; beyond that the rest become one
 * summary ("3 more dates need you today or tomorrow"), so a busy day never floods the screen. Every
 * pending key counts as shown (the summary covers the rest).
 */
export function batchForDisplay(pending: PlannedNotification[]): PlannedNotification[] {
  if (pending.length <= MAX_AT_ONCE) return pending;
  const shown = pending.slice(0, MAX_AT_ONCE - 1);
  const rest = pending.length - shown.length;
  return [...shown, { key: "summary", title: `${rest} more dates need you today or tomorrow`, body: "Open Ordnung to see them all.", href: "/" }];
}
