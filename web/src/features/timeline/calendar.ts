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

export interface GuideStep {
  /** the step; `{link}` marks where `link` goes */
  text: string;
  /** a site to open, in a new tab */
  link?: { label: string; href: string };
}

/** Steps for one way of importing (numbered from 1 — "On a Mac" and "On an iPhone" are alternatives). */
export interface GuideSection {
  /** "On a Mac" — none when the app has only one way */
  title?: string;
  steps: GuideStep[];
}

export interface CalendarGuide {
  app: CalendarApp;
  label: string;
  sections: GuideSection[];
  note?: string;
}

export const CALENDAR_GUIDES: CalendarGuide[] = [
  {
    app: "google",
    label: "Google",
    sections: [
      {
        steps: [
          {
            text: "Open {link} on a computer (the phone app can't import files).",
            link: { label: "calendar.google.com", href: "https://calendar.google.com/calendar/r/settings/export" },
          },
          { text: "In Settings → “Import & export”, choose “Select file from your computer” and pick ordnung.ics from your Downloads." },
          { text: "Pick the calendar to add the dates to and click Import." },
        ],
      },
    ],
    note: "The dates then appear on your phone too.",
  },
  {
    app: "apple",
    label: "Apple",
    sections: [
      {
        title: "On a Mac",
        steps: [
          { text: "Double-click ordnung.ics in your Downloads folder (or in Calendar choose File → Import…)." },
          { text: "Choose the calendar for your dates and click OK." },
        ],
      },
      {
        title: "On an iPhone or iPad",
        steps: [{ text: "Open ordnung.ics from Files or Mail and tap “Add All”." }],
      },
    ],
  },
  {
    app: "outlook",
    label: "Outlook",
    sections: [
      {
        title: "Outlook on the web",
        steps: [{ text: "Open Calendar → Add calendar → Upload from file." }, { text: "Browse to ordnung.ics, choose a calendar and click Import." }],
      },
      {
        title: "Outlook for Windows",
        steps: [{ text: "File → Open & Export → Import/Export → “Import an iCalendar (.ics)”, then pick ordnung.ics." }],
      },
    ],
  },
];

/** "14, 7, 3 and 1 days before each deadline" (null when the profile has none). */
export function reminderDays(days: number[] | null | undefined): string | null {
  const list = [...new Set(days ?? [])].filter((d) => d > 0).sort((a, b) => b - a);
  if (!list.length) return null;
  const words = list.length === 1 ? `${list[0]}` : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
  return `${words} ${list.length === 1 && list[0] === 1 ? "day" : "days"} before each deadline`;
}

/** "Reminders: 14, 7, 3 and 1 days before each deadline (change them in Settings)." */
export function reminderSentence(days: number[] | null | undefined): string {
  const when = reminderDays(days);
  return when ? `Reminders: ${when} (change them in Settings).` : "Reminders follow your settings (change them in Settings).";
}
