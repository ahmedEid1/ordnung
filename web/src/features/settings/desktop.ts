/** Settings → Reminders → the morning desktop notification: pure helpers (see `notify/desktop.py`). */
import type { AppSettings, DesktopMode, DesktopReminders, NotificationText } from "@/api/types";

export type DesktopSetting = AppSettings["desktop_notifications"];

/** What a switched-on notification shows; switching it on starts with `discreet`. */
export const DESKTOP_MODES: { value: DesktopMode; label: string; shortLabel?: string }[] = [
  { value: "discreet", label: "Discreet" },
  { value: "full", label: "With details", shortLabel: "Details" },
];

/** What each choice means, in one line under the choice. */
export const MODE_HINTS: Record<DesktopMode, string> = {
  discreet: "Only a count, like “2 things due this week” — no names or amounts, so nothing private shows on a lock screen.",
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

/** The toast after "Show a test notification". */
export function testOutcome(shown: boolean, detail: string | null | undefined): { tone: "success" | "warn"; title: string; description: string } {
  if (shown) return { tone: "success", title: "Test notification sent", description: "Look at the corner of your screen. The morning one still comes as planned." };
  return { tone: "warn", title: "No notification appeared", description: detail || "This computer couldn't show it. Your calendar alarms still work." };
}

/** Start at login, in words for the badge. */
export function autostartLabel(status: DesktopReminders["autostart"] | undefined): { text: string; tone: "ok" | "warn" | "neutral" } {
  if (!status?.enabled) return { text: "Off", tone: "neutral" };
  if (!status.points_here) return { text: "Starts another folder", tone: "warn" };
  return { text: "On", tone: "ok" };
}
