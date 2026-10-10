/**
 * Mock answers for reminders outside the browser (the desktop notification, start at login, the
 * app-menu shortcut) and the encrypted backup. The preview is worked out from the mock's open to-dos the way
 * `src/ordnung/notify/desktop.py` words it (what ends today first — deadlines and appointments before
 * tasks, tasks before payments — then what is overdue, then the week by day; counts only when
 * discreet, today's apart), so it follows what the visitor ticks off in the demo. The static demo can't touch a computer:
 * showing a notification or making a backup is refused there with a friendly message.
 */
import { addDays, differenceInCalendarDays, format, parseISO } from "date-fns";
import type { AutostartInfo, BackupCopy, BackupInfo, DesktopMode, DesktopReminders, NotificationText, ShortcutInfo } from "@/api/types";
import type { MockDb } from "../db";

export const DESKTOP_STATIC_MESSAGE =
  "The online demo can't show notifications on your computer. Install Ordnung to get the morning notification.";
export const BACKUP_STATIC_MESSAGE =
  "The online demo keeps nothing on your computer, so there is nothing to back up. Install Ordnung to make encrypted backups of your own letters.";

export const MOCK_AUTOSTART: AutostartInfo = {
  enabled: false,
  kind: "systemd user service",
  path: "/home/sam/.config/systemd/user/ordnung.service",
  points_here: false,
  command: "ordnung autostart enable",
};

export const MOCK_SHORTCUT: ShortcutInfo = {
  added: false,
  kind: "app menu entry",
  path: "/home/sam/.local/share/applications/ordnung.desktop",
  points_here: false,
  current: false,
  foreign: false,
  command: "ordnung shortcut",
};

export const SAMPLE_NOTIFICATION: NotificationText = {
  title: "Ordnung",
  body: "Nothing is due this week. This is how Ordnung will tell you.",
};

const WEEK = 7;
const MAX_LISTED = 3;
const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const euros = (n: number) => `€${Number.isInteger(n) ? n.toLocaleString("en-GB") : n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function shortDay(day: string, today: string): string {
  const days = differenceInCalendarDays(parseISO(day), parseISO(today));
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  const d = parseISO(day);
  return days < WEEK ? WEEKDAY[d.getDay()]! : `${WEEKDAY[d.getDay()]} ${format(d, "d MMM")}`;
}

/** "today" / "by Thu" — an appointment "today 09:15" / "on Thu 10:30". */
function dayWord(item: { kind: string; due_time?: string | null }, day: string, today: string): string {
  const label = shortDay(day, today);
  if (item.kind !== "appointment") return label === "today" ? "today" : `by ${label}`;
  const on = label === "today" || label === "tomorrow" ? label : `on ${label}`;
  const time = item.due_time?.slice(0, 5);
  return time ? `${on} ${time}` : on;
}

type When = "today" | "overdue" | "upcoming";

interface Thing {
  text: string;
  day: string;
  when: When;
  rank: number;
}

const GROUP: Record<When, number> = { today: 0, overdue: 1, upcoming: 2 };
/** deadlines, decisions and appointments before tasks, tasks before payments (desktop.py's policy) */
const RANK: Record<string, number> = { deadline: 0, expiry: 0, appointment: 0, payment: 2 };

function thingsDue(db: MockDb): Thing[] {
  const today = db.today;
  const weekEnd = format(addDays(parseISO(today), WEEK), "yyyy-MM-dd");
  const things: Thing[] = [];
  for (const i of db.openItems()) {
    const due = i.due_date;
    if (!due || (i.kind === "payment" && i.direction === "in")) continue;
    const act = i.send_by && i.send_by < due ? i.send_by : due;
    const amount = i.kind === "payment" && i.amount != null && (i.currency ?? "EUR") === "EUR" ? ` ${euros(i.amount)}` : "";
    const rank = RANK[i.kind] ?? 1;
    if (due < today) things.push({ text: `${i.title}${amount} — overdue`, day: due, when: "overdue", rank });
    else if (act <= weekEnd) {
      const day = act < today ? today : act;
      things.push({ text: `${i.title}${amount} ${dayWord(i, day, today)}`, day, when: day === today ? "today" : "upcoming", rank });
    }
  }
  return things.sort(
    (a, b) => GROUP[a.when] - GROUP[b.when] || (a.when === "today" ? a.rank - b.rank : 0) || a.day.localeCompare(b.day),
  );
}

function summary(things: Thing[]): string {
  const today = things.filter((t) => t.when === "today").length;
  const overdue = things.filter((t) => t.when === "overdue").length;
  const upcoming = things.length - today - overdue;
  const n = (c: number) => `${c} ${c === 1 ? "thing" : "things"}`;
  const parts = [today ? `${today} due today` : null, overdue ? `${overdue} overdue` : null, upcoming ? `${upcoming} ${today ? "more" : "due"} this week` : null].filter(Boolean);
  if (parts.length > 1) return parts.join(" · ");
  if (today) return `${n(today)} due today`;
  if (overdue) return `${n(overdue)} overdue`;
  return `${n(upcoming)} due this week`;
}

/** Today's notification in `mode` (null: nothing is due). */
export function mockNotification(db: MockDb, mode: DesktopMode): NotificationText | null {
  const things = thingsDue(db);
  if (!things.length) return null;
  const count = summary(things);
  if (mode === "discreet") return { title: "Ordnung", body: count };
  const listed = things.slice(0, MAX_LISTED).map((t) => t.text);
  if (things.length > MAX_LISTED) listed.push(`and ${things.length - MAX_LISTED} more`);
  return { title: `Ordnung · ${count}`, body: listed.join(" · ") };
}

export function mockDesktopReminders(db: MockDb): DesktopReminders {
  const demo = Boolean(db.state.health.demo);
  return {
    system: "linux",
    tool: "notify-send",
    missing: null,
    preview: { discreet: mockNotification(db, "discreet"), full: mockNotification(db, "full") },
    last_shown_on: null,
    last_failure: null,
    last_failure_on: null,
    demo,
    // the demo is started with `ordnung demo`, never at login: no command to offer
    autostart: demo ? { ...MOCK_AUTOSTART, command: null } : MOCK_AUTOSTART,
    // and opens with `ordnung demo`, never from the app menu
    shortcut: demo ? { ...MOCK_SHORTCUT, command: null } : MOCK_SHORTCUT,
  };
}

/** The mock's "what a backup would hold": Sam's letters (the trash too, as a backup holds it), their pages and a database. */
export function mockBackupInfo(db: MockDb): BackupInfo {
  const letters = db.state.documents;
  const pages = letters.reduce((n, d) => n + Math.max(1, d.pages ?? 1), 0);
  return {
    letters: letters.length,
    files: letters.length + pages + 1,
    bytes: letters.length * 180_000 + pages * 240_000 + 2_100_000,
    file_name: `ordnung-backup-${db.today}.ordnung-backup`,
    left_out: [],
    min_passphrase: 12,
    format_version: 1,
    last_copy: mockLastCopy(db),
  };
}

/**
 * The newest copy kept elsewhere, as the mock knows it: a backup downloaded in this session (calendar days counted to the
 * mock's today). The mock has no hand-off sync, and like the real demo it never says a backup is due.
 */
function mockLastCopy(db: MockDb): BackupCopy {
  const at = db.state.lastBackupAt;
  return {
    last_backup_at: at,
    last_backup_restored: false,
    sync_saved_at: null,
    sync_standing_by: false,
    days: at === null ? null : Math.max(0, differenceInCalendarDays(parseISO(db.today), parseISO(at.slice(0, 10)))),
    due: false,
    due_after_days: 30,
  };
}

/** Stand-in bytes for `?mock=1` (not a real backup: the browser can't encrypt Sam's files). */
export function mockBackupFile(): Uint8Array<ArrayBuffer> {
  const head = new TextEncoder().encode("ORDNUNG-BACKUP\n");
  const bytes = new Uint8Array(head.length + 4096);
  bytes.set(head);
  crypto.getRandomValues(bytes.subarray(head.length));
  return bytes;
}
