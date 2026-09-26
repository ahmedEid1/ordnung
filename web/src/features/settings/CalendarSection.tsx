import { useState } from "react";
import { CalendarPlus, HardDrive, RefreshCw } from "lucide-react";
import { useMarkCalendarExported, useProfile } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { toast } from "@/components/ui/Toast";
import { CALENDAR_GUIDES, downloadCalendarFile, reminderSentence, type CalendarApp } from "@/features/timeline/calendar";
import { CalendarGuideSteps } from "@/features/timeline/CalendarExport";
import { SectionHeading, SettingsCard } from "./SettingsCard";

/** "Calendar": download all dates as .ics and how to import it (Google, Apple, Outlook). */
export function CalendarSection() {
  const exported = useMarkCalendarExported();
  const profile = useProfile();
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
              <p className="mt-0.5 text-[13px] leading-5 text-muted">{reminderSentence(profile.data?.reminder_days?.deadline)}</p>
            </div>
            <Button variant="primary" icon={CalendarPlus} onClick={download} loading={exported.isPending}>
              Download .ics
            </Button>
          </div>
          <ul className="mt-5 grid gap-2 text-[12.5px] leading-5 text-muted sm:grid-cols-2">
            <li className="flex gap-2">
              <HardDrive className="mt-0.5 size-3.5 shrink-0" aria-hidden /> The file is made on this computer — nothing is uploaded.
            </li>
            <li className="flex gap-2">
              <RefreshCw className="mt-0.5 size-3.5 shrink-0" aria-hidden /> It's a snapshot: Ordnung tells you when new letters bring new dates.
            </li>
          </ul>
        </SettingsCard>

        <SettingsCard title="How to import it" id="set-cal-guide">
          <SegmentedControl label="Your calendar app" value={app} onChange={setApp} options={CALENDAR_GUIDES.map((g) => ({ value: g.app, label: g.label }))} />
          <CalendarGuideSteps guide={guide} headingLevel={4} className="mt-4" />
        </SettingsCard>

      </div>
    </section>
  );
}
