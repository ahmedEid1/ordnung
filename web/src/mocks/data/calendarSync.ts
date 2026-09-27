/**
 * Mock calendar sync (CalDAV). The preview is worked out from the mock's open dated to-dos the way
 * `src/ordnung/calendar/caldav.py` words it (discreet: "Ordnung: deadline" and a pointer, nothing
 * else — "Ordnung: money in" for money coming in, and "— check the date" on a date that couldn't be
 * confirmed; full: the calendar file's title and description), with the alarms from Sam's reminder days.
 * `?mock=1` pretends a calendar answers (an https address, a user name and an app password are
 * enough; the password "wrong" is refused like a server would); the static demo can't reach any
 * calendar and says so.
 */
import type {
  CalendarChoice,
  CalendarEventPreview,
  CalendarSyncConnect,
  CalendarSyncFind,
  CalendarSyncMode,
  CalendarSyncReport,
  CalendarSyncStatus,
  Item,
} from "@/api/types";
import type { MockDb } from "../db";

export const CALENDAR_SYNC_STATIC_MESSAGE =
  "The online demo can't reach your calendar. Install Ordnung to sync your own dates to Nextcloud, iCloud or any CalDAV calendar.";
export const DISCREET_DESCRIPTION = "Open Ordnung on your computer to see what this is — the details stay there.";

const KIND_SYMBOLS: Record<string, string> = { deadline: "⚑", payment: "€", appointment: "◷", task: "☐", expiry: "⌛", reminder: "•", milestone: "★" };
const DISCREET_TITLES: Record<string, string> = { payment: "Ordnung: payment", appointment: "Ordnung: appointment" };
const DISCREET_INCOMING = "Ordnung: money in";
const DISCREET_CHECK_TITLE = " — check the date";
const DISCREET_CHECK = "This date couldn't be confirmed in the letter: check it in Ordnung before you rely on it.";
const CHECK_PREFIX = "⚠ check: ";
const ALARM_HOUR = "09:00";

interface MockConnection {
  url: string;
  username: string;
  mode: CalendarSyncMode;
  calendar_name: string | null;
  synced: Set<string>;
  last: CalendarSyncReport | null;
}

const connections = new WeakMap<MockDb, MockConnection>();

/** Refusals shaped like the API's (`code` says which field). */
export class CalendarSyncRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string,
  ) {
    super(message);
  }
}

const euros = (n: number) => `€${n.toLocaleString("en-GB", { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 })}`;

/** The UTC offset of Europe/Berlin on `day` ("+02:00" in summer). */
function berlinOffset(day: string): string {
  try {
    const name = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", timeZoneName: "longOffset" })
      .formatToParts(new Date(`${day}T12:00:00Z`))
      .find((p) => p.type === "timeZoneName")?.value;
    const m = /GMT([+-]\d{2}:\d{2})/.exec(name ?? "");
    if (m) return m[1]!;
  } catch {
    // an engine without longOffset: Berlin's summer time is close enough for the mock
  }
  return "+02:00";
}

function alarmLabel(days: number, clock: string): string {
  if (days === 0) return `on the day at ${clock}`;
  if (days === 1) return `the day before at ${clock}`;
  return `${days} days before at ${clock}`;
}

function description(db: MockDb, i: Item): string {
  const party = db.party(i.party_id)?.name;
  const lines = [
    i.action ? `What to do: ${i.action}` : null,
    i.consequence ? `If ignored: ${i.consequence}` : null,
    i.amount != null && (i.currency ?? "EUR") === "EUR" ? `Amount: ${euros(i.amount)}` : null,
    party ? `With: ${party}` : null,
    "Not legal advice.",
  ];
  return lines.filter(Boolean).join("\n");
}

/** A date read from a letter that the person hasn't confirmed and Ordnung couldn't verify (`ics.needs_check`). */
function needsCheck(i: Item): boolean {
  if (i.origin !== "extracted" || i.grounding === "user") return false;
  return i.grounding === "unverified" || (i.evidence ?? []).some((e) => !e.value_consistent) || i.computation?.confidence === "low";
}

function discreetTitle(i: Item): string {
  const title = i.kind === "payment" && i.direction === "in" ? DISCREET_INCOMING : (DISCREET_TITLES[i.kind] ?? "Ordnung: deadline");
  return needsCheck(i) ? `${title}${DISCREET_CHECK_TITLE}` : title;
}

/** Every event calendar sync would send in `mode` (open dated to-dos, by date). */
export function mockCalendarPreview(db: MockDb, mode: CalendarSyncMode): CalendarEventPreview[] {
  const days = db.state.profile.reminder_days ?? {};
  return db
    .openItems()
    .filter((i) => i.due_date)
    .sort((a, b) => a.due_date!.localeCompare(b.due_date!) || a.id.localeCompare(b.id))
    .map((i) => {
      const day = i.due_date!;
      const time = i.due_time?.slice(0, 5) ?? null;
      const clock = time ?? ALARM_HOUR;
      const alarms = [...new Set(days[i.kind] ?? [])].sort((a, b) => b - a).map((d) => alarmLabel(d, clock));
      const discreet = mode === "discreet";
      return {
        uid: `${i.id}@ordnung.local`,
        summary: discreet ? discreetTitle(i) : `${needsCheck(i) ? CHECK_PREFIX : ""}${KIND_SYMBOLS[i.kind] ?? "•"} ${i.title}`,
        start: time ? `${day}T${time}:00${berlinOffset(day)}` : day,
        all_day: !time,
        description: discreet ? (needsCheck(i) ? `${DISCREET_DESCRIPTION} ${DISCREET_CHECK}` : DISCREET_DESCRIPTION) : description(db, i),
        location: discreet ? null : (i.location ?? null),
        alarms,
      } satisfies CalendarEventPreview;
    });
}

function report(counts: Partial<CalendarSyncReport> = {}): CalendarSyncReport {
  return { at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), sent: 0, removed: 0, unchanged: 0, failed: 0, error: null, error_kind: null, ...counts };
}

export function mockCalendarSyncStatus(db: MockDb, staticDemo: boolean): CalendarSyncStatus {
  const c = connections.get(db);
  const mode = c?.mode ?? "discreet";
  return {
    available: !staticDemo,
    unavailable: staticDemo ? CALENDAR_SYNC_STATIC_MESSAGE : null,
    install_command: null,
    connected: Boolean(c),
    url: c?.url ?? null,
    username: c?.username ?? null,
    calendar_name: c?.calendar_name ?? null,
    mode,
    password_saved: Boolean(c),
    paused: false,
    events: mockCalendarPreview(db, mode).length,
    synced: c?.synced.size ?? 0,
    last_sync: c?.last ?? null,
  };
}

function checkAddress(raw: string): string {
  const url = raw.trim();
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new CalendarSyncRefusal(422, "Enter the calendar's address, starting with https://.", "address");
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  if (parsed.protocol === "http:" && !loopback)
    throw new CalendarSyncRefusal(422, "Use the https:// address: over http:// the app password and your dates would travel unencrypted.", "address");
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") throw new CalendarSyncRefusal(422, "Enter the calendar's address, starting with https://.", "address");
  if (parsed.username || parsed.password) throw new CalendarSyncRefusal(422, "Leave the user name and password out of the address — they have their own fields.", "address");
  return url.endsWith("/") ? url : `${url}/`;
}

function checkAccount(body: { url: string; username: string; password?: string | null }): { url: string; username: string } {
  const url = checkAddress(body.url);
  const username = body.username.trim();
  if (!username) throw new CalendarSyncRefusal(422, "Enter the user name you sign in to your calendar with.", "auth");
  if (body.password === "") throw new CalendarSyncRefusal(422, "Enter the app password for this calendar.", "auth");
  if (body.password === "wrong") throw new CalendarSyncRefusal(422, "The calendar server refused the user name or app password.", "auth");
  return { url, username };
}

/** The calendars the mock's server offers: the address itself when it looks like one calendar, else the account's two. */
export function mockDiscoverCalendars(body: CalendarSyncFind, staticDemo: boolean): { calendars: CalendarChoice[] } {
  if (staticDemo) throw new CalendarSyncRefusal(403, CALENDAR_SYNC_STATIC_MESSAGE, "static_demo");
  const { url, username } = checkAccount(body);
  const parsed = new URL(url);
  if (/\/calendars\/[^/]+\/[^/]+\/$/.test(parsed.pathname)) return { calendars: [{ url, name: "Ordnung" }] };
  const home = `${parsed.origin}/remote.php/dav/calendars/${encodeURIComponent(username)}/`;
  return { calendars: [{ url: `${home}ordnung/`, name: "Ordnung" }, { url: `${home}personal/`, name: "Personal" }] };
}

/** Everything the calendar holds now: all events sent (the mock's calendar always takes them). */
function send(db: MockDb, c: MockConnection): CalendarSyncReport {
  const events = mockCalendarPreview(db, c.mode).map((e) => e.uid);
  const removed = [...c.synced].filter((uid) => !events.includes(uid)).length;
  const sent = events.filter((uid) => !c.synced.has(uid)).length;
  c.synced = new Set(events);
  return report({ sent, removed, unchanged: events.length - sent });
}

export function mockConnectCalendar(db: MockDb, body: CalendarSyncConnect, staticDemo: boolean): CalendarSyncStatus {
  if (staticDemo) throw new CalendarSyncRefusal(403, CALENDAR_SYNC_STATIC_MESSAGE, "static_demo");
  const { url, username } = checkAccount(body);
  const existing = connections.get(db);
  if (existing && (existing.url !== url || existing.username !== username))
    throw new CalendarSyncRefusal(409, `Ordnung is connected to ${new URL(existing.url).hostname} already. Disconnect that calendar first.`, "conflict");
  if (body.password == null && !existing) throw new CalendarSyncRefusal(422, "The app password isn't saved on this computer — enter it again in Settings → Calendar.", "auth");
  const c: MockConnection = existing ?? { url, username, mode: body.mode ?? "discreet", calendar_name: "Ordnung", synced: new Set(), last: null };
  if (c.mode !== body.mode) c.synced = new Set(); // another mode: every event is sent again
  c.mode = body.mode ?? "discreet";
  c.last = send(db, c);
  connections.set(db, c);
  if (!existing) db.log("calendar.connected", `Connected the calendar at ${new URL(url).hostname} for calendar sync (${c.mode})`);
  // the calendar gets the dates by itself: no "import the calendar file" Idea (the triggers expire it)
  for (const idea of db.state.suggestions) if (idea.rule_id === "calendar_outdated" && idea.status === "new") idea.status = "expired";
  return mockCalendarSyncStatus(db, false);
}

export function mockRunCalendarSync(db: MockDb, staticDemo: boolean): CalendarSyncStatus {
  if (staticDemo) throw new CalendarSyncRefusal(403, CALENDAR_SYNC_STATIC_MESSAGE, "static_demo");
  const c = connections.get(db);
  if (!c) throw new CalendarSyncRefusal(409, "No calendar is connected.", "not_connected");
  c.last = send(db, c);
  return mockCalendarSyncStatus(db, false);
}

/** "Delete everything": Ordnung's events leave the connected calendar first (`null`: none was connected). */
export function mockForgetCalendar(db: MockDb): number | null {
  return connections.has(db) ? mockDisconnectCalendar(db, true).removed : null;
}

export function mockDisconnectCalendar(db: MockDb, removeEvents: boolean): { removed: number } {
  const c = connections.get(db);
  if (!c) return { removed: 0 };
  connections.delete(db);
  const removed = removeEvents ? c.synced.size : 0;
  db.log("calendar.disconnected", `Disconnected the calendar at ${new URL(c.url).hostname}${removeEvents ? `, removed ${removed} events` : ", its events were left in the calendar"}`);
  return { removed };
}
