/** Settings → Reminders → the morning desktop notification: pure helpers (see `notify/desktop.py`). */
import type { AppSettings, DesktopMode, DesktopReminders, NotificationText } from "@/api/types";
import { formatDate } from "@/lib/format";

export type DesktopSetting = AppSettings["desktop_notifications"];

/** What a switched-on notification shows; switching it on starts with `discreet`. */
export const DESKTOP_MODES: { value: DesktopMode; label: string; shortLabel?: string }[] = [
  { value: "discreet", label: "Discreet" },
  { value: "full", label: "With details", shortLabel: "Details" },
];

/** What each choice means, in one line under the choice. */
export const MODE_HINTS: Record<DesktopMode, string> = {
  discreet: "Only counts, like “1 due today · 2 more this week” — no names or amounts, so nothing private shows on a lock screen.",
  full: "What is due, with amounts and the day to act. Anyone who can see your screen can read it.",
};

/** `HH:MM`, 24 hours — what the API accepts. */
export const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Why a typed time can't be saved (null: it can). */
export function timeError(value: string): string | null {
  return TIME_PATTERN.test(value) ? null : "Choose a time, like 08:00";
}

/** The mode a test notification is shown in: the chosen one, or discreet while it is off. */
export function testMode(setting: DesktopSetting): DesktopMode {
  return setting === "full" ? "full" : "discreet";
}

/** Today's notification in the chosen mode (null when off or nothing is due). */
export function previewFor(status: DesktopReminders | undefined, setting: DesktopSetting): NotificationText | null {
  if (!status || setting === "off") return null;
  return status.preview[setting] ?? null;
}

/**
 * Where to look when the system took the notification but nothing appeared: the tool's "done" only
 * means the system has it — macOS keeps it back without permission, Focus or Do not disturb hide it.
 */
export const NOTHING_APPEARED: Record<DesktopReminders["system"], string> = {
  macos: "Nothing appeared? Open System Settings → Notifications and allow notifications for Script Editor (macOS shows them under that name), and check that Focus is off.",
  windows: "Nothing appeared? Open Settings → System → Notifications: notifications on, also for Windows PowerShell, and Do not disturb off.",
  linux: "Nothing appeared? Check that your desktop shows notifications and that Do not disturb is off.",
};

/**
 * The toast after "Show a test notification". `morning`: the saved setting (`dirty`: the card's
 * choice isn't saved yet) — only a saved switch brings the morning one.
 */
export function testOutcome(
  shown: boolean,
  detail: string | null | undefined,
  morning: { system: DesktopReminders["system"] | undefined; saved: DesktopSetting; dirty: boolean; time: string },
): { tone: "success" | "warn"; title: string; description: string } {
  if (!shown) return { tone: "warn", title: "No notification appeared", description: detail || "This computer couldn't show it. Your calendar alarms still work." };
  const next = morning.dirty ? `Save to get it each morning at ${morning.time}.` : morning.saved === "off" ? "" : `The morning one comes at ${morning.time}.`;
  const help = morning.system ? NOTHING_APPEARED[morning.system] : "";
  return { tone: "success", title: "Test notification sent to your system", description: [help, next].filter(Boolean).join(" ") };
}

/** What the save bar says after its "Saved." (the demos can't notify on their own). */
export function savedNote(setting: DesktopSetting, time: string, demo: "static" | "demo" | null): string {
  if (setting === "off") return "No desktop notification from now on.";
  if (demo === "static") return "For this visit only — the online demo can't show notifications on your computer.";
  if (demo === "demo") return "The demo doesn't notify on its own — the preview shows what it would say.";
  return `Once a day at ${time}, while Ordnung runs.`;
}

/**
 * The last notification the system couldn't show, in words — only while it is the latest news (a
 * notification shown since clears it; one given up on after its tries is shown until another day's).
 */
export function failureLine(status: Pick<DesktopReminders, "last_failure" | "last_failure_on" | "last_shown_on"> | undefined): string | null {
  if (!status?.last_failure || !status.last_failure_on) return null;
  if (status.last_shown_on && status.last_shown_on > status.last_failure_on) return null;
  return `The last notification (${formatDate(status.last_failure_on)}) couldn't be shown on this computer. Check that your desktop shows notifications, then send a test notification.`;
}

/** The system tool's own words about that failure (folded away under the sentence above). */
export function failureDetail(status: Pick<DesktopReminders, "last_failure"> | undefined): string | null {
  return status?.last_failure?.trim() || null;
}

/** Start at login, in words for the badge. */
export function autostartLabel(status: DesktopReminders["autostart"] | undefined): { text: string; tone: "ok" | "warn" | "neutral" } {
  if (!status?.enabled) return { text: "Off", tone: "neutral" };
  if (!status.points_here) return { text: "Starts another folder", tone: "warn" };
  return { text: "On", tone: "ok" };
}

/** Where `ordnung shortcut` puts Ordnung on each system, as the person knows it (`ordnung.shortcut.WHERE`). */
export const MENU_NAME: Record<DesktopReminders["system"], string> = {
  linux: "app menu",
  macos: "Applications folder",
  windows: "Start menu",
};

/**
 * The app-menu shortcut, in words for the badge. A launcher Ordnung didn't write counts as not added, with a
 * warning: it is in the way of `ordnung shortcut`. One that runs another installation of Ordnung (maybe gone)
 * needs updating.
 */
export function shortcutLabel(status: DesktopReminders["shortcut"] | undefined): { text: string; tone: "ok" | "warn" | "neutral" } {
  if (!status?.added) return { text: "Not added", tone: status?.foreign ? "warn" : "neutral" };
  if (!status.points_here) return { text: "Opens another folder", tone: "warn" };
  if (!status.current) return { text: "Needs updating", tone: "warn" };
  return { text: "Added", tone: "ok" };
}

/** After "Ordnung is in your Applications folder": macOS has two, and Finder's sidebar shows the other one. */
export const MENU_PLACE_NOTE: Record<DesktopReminders["system"], string> = {
  linux: "",
  macos: " (the one in your home folder; Launchpad and Spotlight find it)",
  windows: "",
};

/** A launcher's kind after "Set up as": "an app menu entry", "a Start menu shortcut". */
export function withArticle(kind: string): string {
  return `${/^[aeiou]/i.test(kind) ? "an" : "a"} ${kind}`;
}
