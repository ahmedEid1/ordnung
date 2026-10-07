/**
 * What works while nobody looks — the watched folder, calendar sync, the morning notification, phone access — and
 * has stopped working: said once on Today ("Needs your attention") and as a dot on Settings, not only inside
 * Settings, where nobody goes to look. Each problem links to its own Settings section. Phone access also raises
 * what the person must know at once (a pairing code used twice, a phone's sign-in used from two places).
 */
import { useCalendarSync, useDesktopReminders, useFolder, usePhone, useSettings } from "@/api/hooks";
import type { AppSettings, CalendarSyncStatus, DesktopReminders, FolderStatus, PhoneStatus } from "@/api/types";
import { usePhoneCompanion } from "@/features/phone/client";
import { failureLine } from "./desktop";
import type { SectionId } from "./logic";
import { NOTICE_TITLES } from "./phoneAccess";

export interface BackgroundProblem {
  section: SectionId;
  /** What stopped, in a few words ("Not watching your folder"). */
  title: string;
  /** Why, as Settings says it. */
  detail: string;
}

/** The problems of the background features (pure: what their Settings cards show). */
export function backgroundProblems(state: {
  folder?: Pick<FolderStatus, "folder" | "state" | "problem"> | null;
  calendar?: Pick<CalendarSyncStatus, "connected" | "paused" | "password_saved" | "last_sync"> | null;
  desktop?: Pick<DesktopReminders, "last_failure" | "last_failure_on" | "last_shown_on"> | null;
  settings?: Pick<AppSettings, "desktop_notifications"> | null;
  phone?: Pick<PhoneStatus, "enabled" | "problem" | "notice"> | null;
}): BackgroundProblem[] {
  const found: BackgroundProblem[] = [];
  const { folder, calendar, desktop, settings, phone } = state;
  if (folder?.folder && folder.state === "problem" && folder.problem) {
    found.push({ section: "folder", title: "Not watching your folder", detail: `New scans don't arrive: ${folder.problem}` });
  }
  if (calendar?.connected) {
    if (calendar.paused || !calendar.password_saved) {
      const why = calendar.paused ? "the server refused the app password" : "the app password isn't saved on this computer";
      found.push({ section: "calendar", title: "Calendar sync is paused", detail: `New dates don't reach your calendar: ${why}.` });
    } else if (calendar.last_sync?.error) {
      found.push({ section: "calendar", title: "Calendar sync didn't finish", detail: calendar.last_sync.error });
    }
  }
  const failed = settings && settings.desktop_notifications !== "off" ? failureLine(desktop ?? undefined) : null;
  if (failed) found.push({ section: "reminders", title: "The morning notification didn't show", detail: failed });
  // one line for phone access: a notice (danger: someone else may be involved) before a pause
  if (phone?.notice) {
    found.push({ section: "phone", title: NOTICE_TITLES[phone.notice.code], detail: phone.notice.detail });
  } else if (phone?.enabled && phone.problem) {
    found.push({ section: "phone", title: "Phones can't reach Ordnung", detail: phone.problem.detail });
  }
  return found;
}

/**
 * The background problems now (shares the Settings cards' queries; the notification's without its texts). None
 * on a phone: they are fixed in Settings on the computer, and a phone may not ask for them (`computer_only`).
 */
export function useBackgroundProblems(): BackgroundProblem[] {
  const onComputer = !usePhoneCompanion();
  const folder = useFolder({ enabled: onComputer });
  const calendar = useCalendarSync(onComputer);
  const desktop = useDesktopReminders({ preview: false, enabled: onComputer });
  const settings = useSettings({ enabled: onComputer });
  const phone = usePhone({ enabled: onComputer });
  if (!onComputer) return [];
  return backgroundProblems({ folder: folder.data, calendar: calendar.data, desktop: desktop.data, settings: settings.data, phone: phone.data });
}
