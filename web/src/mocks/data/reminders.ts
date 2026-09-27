/**
 * Mock answers for reminders outside the browser (the desktop notification, start at login) and
 * the encrypted backup. The preview is worked out from the mock's open to-dos the way
 * `src/ordnung/notify/desktop.py` words it (overdue first, then by day; a count only when discreet),
 * so it follows what the visitor ticks off in the demo. The static demo can't touch a computer:
 * showing a notification or making a backup is refused there with a friendly message.
 */
import { addDays, differenceInCalendarDays, format, parseISO } from "date-fns";
import type { AutostartInfo, BackupInfo, DesktopMode, DesktopReminders, NotificationText } from "@/api/types";
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

export const SAMPLE_NOTIFICATION: NotificationText = {
  title: "Ordnung",
  body: "Nothing is due this week. This is how Ordnung will tell you.",
};

const WEEK = 7;
const MAX_LISTED = 3;
const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const euros = (n: number) => `€${Number.isInteger(n) ? n.toLocaleString("en-GB") : n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function dayWord(day: string, today: string): string {
  const days = differenceInCalendarDays(parseISO(day), parseISO(today));
  if (days <= 0) return "today";
  if (days === 1) return "by tomorrow";
  const d = parseISO(day);
  return days < WEEK ? `by ${WEEKDAY[d.getDay()]}` : `by ${WEEKDAY[d.getDay()]} ${format(d, "d MMM")}`;
}

interface Thing {
  text: string;
  day: string;
  overdue: boolean;
}

function thingsDue(db: MockDb): Thing[] {
  const today = db.today;
  const weekEnd = format(addDays(parseISO(today), WEEK), "yyyy-MM-dd");
  const things: Thing[] = [];
  for (const i of db.openItems()) {
    const due = i.due_date;
    if (!due || (i.kind === "payment" && i.direction === "in")) continue;
    const act = i.send_by && i.send_by < due ? i.send_by : due;
    const amount = i.kind === "payment" && i.amount != null && (i.currency ?? "EUR") === "EUR" ? ` ${euros(i.amount)}` : "";
    if (due < today) things.push({ text: `${i.title}${amount} — overdue`, day: due, overdue: true });
    else if (act <= weekEnd) things.push({ text: `${i.title}${amount} ${dayWord(act < today ? today : act, today)}`, day: act, overdue: false });
  }
  return things.sort((a, b) => Number(a.overdue === false) - Number(b.overdue === false) || a.day.localeCompare(b.day));
}

function summary(things: Thing[]): string {
  const overdue = things.filter((t) => t.overdue).length;
  const upcoming = things.length - overdue;
  const n = (c: number) => `${c} ${c === 1 ? "thing" : "things"}`;
  if (overdue && upcoming) return `${overdue} overdue · ${upcoming} due this week`;
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
  return {
    system: "linux",
    tool: "notify-send",
    missing: null,
    preview: { discreet: mockNotification(db, "discreet"), full: mockNotification(db, "full") },
    last_shown_on: null,
    autostart: MOCK_AUTOSTART,
  };
}

/** The mock's "what a backup would hold": Sam's letters, their pages and a database. */
export function mockBackupInfo(db: MockDb): BackupInfo {
  const letters = db.liveDocuments();
  const pages = letters.reduce((n, d) => n + Math.max(1, d.pages ?? 1), 0);
  return {
    letters: letters.length,
    files: letters.length + pages + 1,
    bytes: letters.length * 180_000 + pages * 240_000 + 2_100_000,
    file_name: `ordnung-backup-${db.today}.ordnung-backup`,
    min_passphrase: 12,
    format_version: 1,
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
