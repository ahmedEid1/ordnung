/** Settings → Calendar → calendar sync (CalDAV): pure helpers (the policy lives in `calendar/caldav.py`). */
import type { CalendarChoice, CalendarEventPreview, CalendarSyncMode, CalendarSyncReport } from "@/api/types";
import { formatDate, formatTimeAgo } from "@/lib/format";

export const SYNC_MODES: { value: CalendarSyncMode; label: string; shortLabel?: string }[] = [
  { value: "discreet", label: "Discreet" },
  { value: "full", label: "With details", shortLabel: "Details" },
];

/** What each choice sends to the calendar provider, in one line under the choice. */
export const SYNC_MODE_HINTS: Record<CalendarSyncMode, string> = {
  discreet: "Only the date, the time and the alarms, titled like “Ordnung: deadline” — no names, organisations or amounts leave this computer.",
  full: "Each event says what it is about: the title, what to do, amounts and who it is with. Your calendar provider stores all of it.",
};

/** Where to find a calendar's address and an app password, by provider. */
export const PROVIDER_HINTS: { name: string; address: string; password: string }[] = [
  { name: "Nextcloud", address: "your Nextcloud's own, like https://cloud.example.org", password: "Settings → Security → Create new app password" },
  { name: "iCloud", address: "https://caldav.icloud.com", password: "account.apple.com → Sign-In and Security → App-Specific Passwords" },
  { name: "mailbox.org", address: "https://dav.mailbox.org", password: "Settings → Security → App passwords" },
];

export type SyncField = "url" | "username" | "password" | "form";

/** Which field an API refusal (`ApiError.code`) belongs next to. */
export function fieldFor(code: string | null | undefined): SyncField {
  switch (code) {
    case "address":
    case "not_found":
    case "not_calendar":
      return "url";
    case "auth":
    case "forbidden":
      return "password";
    default:
      return "form";
  }
}

export interface SyncProblem {
  field: Exclude<SyncField, "form">;
  message: string;
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

function parseUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/** What must be fixed before asking the server (null: nothing). The server checks it all again. */
export function syncFormProblem(values: { url: string; username: string; password: string }, needPassword = true): SyncProblem | null {
  const parsed = parseUrl(values.url.trim());
  if (!parsed || !["https:", "http:"].includes(parsed.protocol)) return { field: "url", message: "Enter the calendar's address, starting with https://." };
  if (parsed.protocol === "http:" && !LOOPBACK.has(parsed.hostname))
    return { field: "url", message: "Use the https:// address: over http:// the app password and your dates would travel unencrypted." };
  if (parsed.username || parsed.password) return { field: "url", message: "Leave the user name and password out of the address — they have their own fields." };
  if (!values.username.trim()) return { field: "username", message: "Enter the user name you sign in to your calendar with." };
  if (needPassword && !values.password) return { field: "password", message: "Enter the app password for this calendar." };
  return null;
}

/** The calendar to preselect: one named "Ordnung", else the first. */
export function preferredCalendar(calendars: CalendarChoice[]): string | null {
  return (calendars.find((c) => c.name?.trim().toLowerCase() === "ordnung") ?? calendars[0])?.url ?? null;
}

/** "cloud.example.org" from a calendar address (the address itself if it can't be read). */
export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/** "Found 1 calendar: Privat." / "Found 3 calendars — choose one." (the footer says what was found). */
export function foundLine(calendars: CalendarChoice[]): string {
  if (calendars.length !== 1) return `Found ${calendars.length} calendars — choose one.`;
  const name = calendars[0]!.name?.trim();
  return name ? `Found 1 calendar: ${name}.` : "Found 1 calendar (it has no name).";
}

/** An event whose day is before `today` (an overdue date: its alarms have rung already). */
export function isPastEvent(event: Pick<CalendarEventPreview, "start">, today: string): boolean {
  return event.start.slice(0, 10) < today;
}

/**
 * The preview's order: what is still to come first (by date, as the API sends it), then the dates
 * that have passed — so the first events shown are ones whose alarms will ring.
 */
export function previewOrder<T extends Pick<CalendarEventPreview, "start">>(events: T[], today: string): { events: T[]; past: number } {
  const upcoming = events.filter((e) => !isPastEvent(e, today));
  const past = events.filter((e) => isPastEvent(e, today));
  return { events: [...upcoming, ...past], past: past.length };
}

/** When an event is: "Tue 29 Sep" (all day) or "Wed 14 Oct, 10:00" (its own wall-clock time). */
export function eventWhen(event: Pick<CalendarEventPreview, "start" | "all_day">, today?: string): string {
  const day = formatDate(event.start.slice(0, 10), { today });
  return event.all_day ? day : `${day}, ${event.start.slice(11, 16)}`;
}

const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The last sync in words, and how it went. */
export function lastSyncLine(report: CalendarSyncReport | null | undefined, now: Date = new Date()): { tone: "ok" | "warn" | "neutral"; text: string } {
  if (!report) return { tone: "neutral", text: "Not synced yet." };
  const when = formatTimeAgo(report.at, now);
  if (report.error) {
    const done = report.sent || report.removed ? ` (${count(report.sent, "event")} sent, ${report.removed} removed)` : "";
    return { tone: "warn", text: `Last sync ${when}${done}: ${report.error}` };
  }
  if (!report.sent && !report.removed) return { tone: "ok", text: `Up to date — checked ${when}, nothing had changed.` };
  const parts = [report.sent ? `${count(report.sent, "event")} sent` : null, report.removed ? `${report.removed} removed` : null].filter(Boolean);
  return { tone: "ok", text: `Synced ${when}: ${parts.join(", ")}.` };
}

/** "Discreet" / "With details" for a badge. */
export function modeLabel(mode: CalendarSyncMode): string {
  return SYNC_MODES.find((m) => m.value === mode)?.label ?? mode;
}
