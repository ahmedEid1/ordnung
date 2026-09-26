/**
 * "Add to my calendar" — downloads every open date (with reminders) as `ordnung.ics`, records the
 * export (so the "new dates since your last calendar update" Idea resets) and shows a short guide
 * for Google, Apple and Outlook.
 */
import { useState } from "react";
import { BellRing, CalendarPlus, Download, HardDrive } from "lucide-react";
import { useMarkCalendarExported, useProfile } from "@/api/hooks";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { CALENDAR_GUIDES, downloadCalendarFile, reminderSentence, type CalendarApp } from "./calendar";

export function CalendarExport({ variant = "secondary", size = "md", className }: Pick<ButtonProps, "variant" | "size" | "className">) {
  const [open, setOpen] = useState(false);
  const [app, setApp] = useState<CalendarApp>("google");
  const exported = useMarkCalendarExported();
  const profile = useProfile();

  const download = () => {
    downloadCalendarFile();
    exported.mutate(undefined);
  };
  const guide = CALENDAR_GUIDES.find((g) => g.app === app) ?? CALENDAR_GUIDES[0]!;

  return (
    <>
      <Button
        variant={variant}
        size={size}
        icon={CalendarPlus}
        className={className}
        onClick={() => {
          download();
          setOpen(true);
        }}
      >
        Add to my calendar
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Add your dates to your calendar"
        description="Your calendar file (ordnung.ics) is downloading. It has every open date and send-by day, with reminders. Import it once — do it again when new letters bring new dates."
        footer={
          <>
            <Button icon={Download} onClick={download} loading={exported.isPending}>
              Download again
            </Button>
            <Button variant="primary" onClick={() => setOpen(false)}>
              Done
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <SegmentedControl
            label="Your calendar app"
            value={app}
            onChange={setApp}
            fill
            options={CALENDAR_GUIDES.map((g) => ({ value: g.app, label: g.label }))}
          />
          <div aria-live="polite">
            <ol className="space-y-2.5">
              {guide.steps.map((s, i) => (
                <li key={s} className="flex gap-3 text-[14px] leading-relaxed text-ink">
                  <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent">
                    {i + 1}
                  </span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
            {guide.note ? <p className="mt-2.5 pl-9 text-[13px] text-muted">{guide.note}</p> : null}
          </div>
          <ul className="space-y-1.5 rounded-lg bg-surface-2/70 px-3.5 py-3 text-[13px] leading-5 text-muted">
            <li className="flex gap-2">
              <BellRing className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {reminderSentence(profile.data?.reminder_days?.deadline)}
            </li>
            <li className="flex gap-2">
              <HardDrive className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              The file is made on this computer — nothing is uploaded anywhere.
            </li>
          </ul>
        </div>
      </Dialog>
    </>
  );
}
