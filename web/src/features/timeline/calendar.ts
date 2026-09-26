/** "Add to my calendar": download `calendar.ics` and the import guides per calendar app. */
import { api } from "@/api/endpoints";

/** Start the download of all open dates as `ordnung.ics` (works for API URLs and mock data: URLs). */
export function downloadCalendarFile(): void {
  const a = document.createElement("a");
  a.href = api.calendarIcsUrl();
  a.download = "ordnung.ics";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export type CalendarApp = "google" | "apple" | "outlook";

export interface CalendarGuide {
  app: CalendarApp;
  label: string;
  steps: string[];
  note?: string;
}

export const CALENDAR_GUIDES: CalendarGuide[] = [
  {
    app: "google",
    label: "Google",
    steps: [
      "Open calendar.google.com on a computer (the phone app can't import files).",
      "Click the gear icon → Settings → “Import & export”.",
      "Choose “Select file from your computer”, pick ordnung.ics from your Downloads.",
      "Pick the calendar to add the dates to and click Import.",
    ],
    note: "The dates then appear on your phone too.",
  },
  {
    app: "apple",
    label: "Apple",
    steps: [
      "On a Mac: double-click ordnung.ics in your Downloads folder (or in Calendar choose File → Import…).",
      "Choose the calendar for your dates and click OK.",
      "On an iPhone or iPad: open the file from Files or Mail and tap “Add All”.",
    ],
  },
  {
    app: "outlook",
    label: "Outlook",
    steps: [
      "Outlook on the web: open Calendar → Add calendar → Upload from file.",
      "Browse to ordnung.ics, choose a calendar and click Import.",
      "Outlook for Windows: File → Open & Export → Import/Export → “Import an iCalendar (.ics)”.",
    ],
  },
];

/** "Reminders: 14, 7, 3 and 1 days before each deadline (change them in Settings)." */
export function reminderSentence(days: number[] | null | undefined): string {
  const list = [...new Set(days ?? [])].filter((d) => d > 0).sort((a, b) => b - a);
  if (!list.length) return "Reminders follow your settings (change them in Settings).";
  const words = list.length === 1 ? `${list[0]}` : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
  return `Reminders: ${words} ${list.length === 1 && list[0] === 1 ? "day" : "days"} before each deadline (change them in Settings).`;
}
