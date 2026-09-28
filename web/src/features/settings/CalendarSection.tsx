import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { BellRing, CalendarCheck, CalendarPlus, HardDrive, RefreshCw } from "lucide-react";
import { api } from "@/api/endpoints";
import { useCalendarSync, useMarkCalendarExported, useProfile } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { toast } from "@/components/ui/Toast";
import { CALENDAR_GUIDES, downloadCalendarFile, reminderSentence, type CalendarApp } from "@/features/timeline/calendar";
import { CalendarGuideSteps } from "@/features/timeline/CalendarExport";
import { hostOf } from "./calendarSync";
import { CalendarSyncCard } from "./CalendarSyncCard";
import { SectionHeading, SettingsCard } from "./SettingsCard";

/**
 * How many dates the calendar file holds — its events, counted in the file itself (to-dos and
 * contract dates, exactly what a download gets). Under "timeline", so new dates refresh it.
 */
export const CALENDAR_FILE_KEY = ["timeline", "calendar-file"] as const;

function useCalendarFileDates() {
  return useQuery({
    queryKey: CALENDAR_FILE_KEY,
    queryFn: async ({ signal }) => {
      const res = await fetch(api.calendarIcsUrl(), { signal });
      if (!res.ok) throw new Error(`calendar.ics answered ${res.status}`);
      return (await res.text()).match(/^BEGIN:VEVENT/gm)?.length ?? 0;
    },
    staleTime: 60_000,
    retry: false,
  });
}

/** What the calendar file will hold: "12 open dates…", or why there's nothing to download yet. */
export function calendarFileSummary(dates: number | null): string {
  if (dates === null) return "Every open date and send-by day, in one file for your calendar.";
  if (dates === 0) return "No dates yet — add letters first, and their dates come here.";
  return `${dates} open ${dates === 1 ? "date" : "dates"} in one file for your calendar, send-by days included.`;
}

/**
 * "Calendar": download all dates as .ics and how to import it (Google, Apple, Outlook) — the file and
 * its guide side by side — then calendar sync. While a calendar is connected the file card says the
 * dates already go there: importing the file into it too would add every date twice.
 */
export function CalendarSection() {
  const exported = useMarkCalendarExported();
  const profile = useProfile();
  const file = useCalendarFileDates();
  const sync = useCalendarSync();
  const syncedTo = sync.data?.connected ? (sync.data.calendar_name ?? hostOf(sync.data.url)) : null;
  const openDates = file.data ?? null;
  const nothing = openDates === 0;
  const alarms = reminderSentence(profile.data?.reminder_days?.deadline);
  const [app, setApp] = useState<CalendarApp>("google");
  const guide = CALENDAR_GUIDES.find((g) => g.app === app) ?? CALENDAR_GUIDES[0]!;

  const download = () => {
    downloadCalendarFile();
    exported.mutate(undefined, { onSuccess: () => toast.success("Calendar file downloaded", { description: "Import ordnung.ics into your calendar — see the steps below." }) });
  };

  return (
    <section aria-labelledby="set-calendar">
      <SectionHeading id="set-calendar" title="Calendar" description="Put every open date and send-by day into the calendar you already use — with alarms." />
      <div className="space-y-5">
        <SettingsCard>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent">
              <CalendarPlus className="size-6" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-semibold text-ink">Add my dates to my calendar</p>
              <p className="mt-0.5 text-[13px] leading-5 text-muted">{calendarFileSummary(openDates)}</p>
            </div>
            <Button variant={nothing || syncedTo ? "secondary" : "primary"} icon={CalendarPlus} onClick={download} loading={exported.isPending} disabled={nothing}>
              Download .ics
            </Button>
          </div>
          <ul className="mt-5 grid gap-2 text-[12.5px] leading-5 text-muted sm:grid-cols-2">
            <li className="flex gap-2 sm:col-span-2">
              <BellRing className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                Alarms: {alarms ?? "none for deadlines"} —{" "}
                <Link to="/settings?section=reminders" preventScrollReset className="font-medium text-accent underline underline-offset-2 hover:no-underline">
                  change them in Reminders
                </Link>
                .
              </span>
            </li>
            <li className="flex gap-2">
              <HardDrive className="mt-0.5 size-3.5 shrink-0" aria-hidden /> The file is made on this computer — nothing is uploaded.
            </li>
            {syncedTo ? (
              <li className="flex gap-2 sm:col-span-2">
                <CalendarCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
                <span className="min-w-0 [overflow-wrap:anywhere]">
                  Your dates already go to “{syncedTo}” by calendar sync (below) and stay current there. Use the file only for another calendar — imported into
                  that one too, every date would be there twice.
                </span>
              </li>
            ) : (
              <li className="flex gap-2">
                <RefreshCw className="mt-0.5 size-3.5 shrink-0" aria-hidden /> It's a snapshot: Ordnung tells you when new letters bring new dates.
              </li>
            )}
          </ul>
        </SettingsCard>

        <SettingsCard title="How to import it" id="set-cal-guide">
          <SegmentedControl label="Your calendar app" value={app} onChange={setApp} options={CALENDAR_GUIDES.map((g) => ({ value: g.app, label: g.label }))} />
          <CalendarGuideSteps guide={guide} headingLevel={4} className="mt-4" />
        </SettingsCard>

        <CalendarSyncCard />
      </div>
    </section>
  );
}
