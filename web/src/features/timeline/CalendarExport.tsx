/**
 * "Add your dates to your calendar" — downloads every open date (with reminders) as `ordnung.ics`, records the
 * export (so the "new dates since your last calendar update" Idea resets) and shows a short guide
 * for Google, Apple and Outlook. The file downloads by itself on the first open only; after that
 * the dialog offers "Download again".
 */
import { useState } from "react";
import { Link } from "react-router";
import { BellRing, CalendarPlus, Download, ExternalLink, HardDrive } from "lucide-react";
import { useMarkCalendarExported, useProfile } from "@/api/hooks";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { usePhoneCompanion } from "@/features/phone/client";
import { theComputer } from "@/features/phone/copy";
import { CALENDAR_GUIDES, downloadCalendarFile, reminderDays, type CalendarApp, type CalendarGuide, type GuideStep } from "./calendar";

function StepText({ step }: { step: GuideStep }) {
  const [before, after] = step.text.split("{link}");
  if (!step.link || after === undefined) return <>{step.text}</>;
  return (
    <>
      {before}
      <a
        href={step.link.href}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 rounded-sm font-medium text-accent underline underline-offset-2 hover:no-underline"
      >
        {step.link.label}
        <ExternalLink className="size-3 shrink-0" aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
      {after}
    </>
  );
}

/**
 * The import steps for one calendar app — each way (Mac, iPhone; web, Windows) numbered on its own,
 * under its own small heading.
 */
export function CalendarGuideSteps({ guide, headingLevel = 3, className }: { guide: CalendarGuide; headingLevel?: 3 | 4; className?: string }) {
  const Heading = headingLevel === 4 ? "h4" : "h3";
  return (
    <div aria-live="polite" className={className}>
      <div className="space-y-4">
        {guide.sections.map((section) => (
          <div key={section.title ?? guide.app}>
            {section.title ? <Heading className="mb-2 text-sm font-semibold text-ink">{section.title}</Heading> : null}
            <ol className="space-y-2.5">
              {section.steps.map((s, i) => (
                <li key={s.text} className="flex gap-3 text-base leading-relaxed text-ink">
                  <span aria-hidden className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <StepText step={s} />
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      {guide.note ? <p className="mt-2.5 pl-9 text-sm text-muted">{guide.note}</p> : null}
    </div>
  );
}

export function CalendarExport({ variant = "secondary", size = "md", className }: Pick<ButtonProps, "variant" | "size" | "className">) {
  const [open, setOpen] = useState(false);
  // "downloading" right after a download started, "earlier" when the dialog opens again without one
  const [file, setFile] = useState<"none" | "downloading" | "earlier">("none");
  const [app, setApp] = useState<CalendarApp>("google");
  const exported = useMarkCalendarExported();
  const profile = useProfile();
  const phone = usePhoneCompanion();

  const download = () => {
    downloadCalendarFile();
    exported.mutate(undefined);
    setFile("downloading");
  };
  const guide = CALENDAR_GUIDES.find((g) => g.app === app) ?? CALENDAR_GUIDES[0]!;
  const reminders = reminderDays(profile.data?.reminder_days?.deadline);
  // the calendar file is a copy of the records: it stays on the computer, which the phone's API refuses anyway
  if (phone) return null;

  return (
    <>
      {/* one name for it everywhere: the button, the dialog it opens and Settings say "Add your dates to your
          calendar". Ask's prompt names this button (src/ordnung/llm/prompts/ask_system.md), so its label
          changes only with it (and a re-recording of Ask's answers) */}
      <Button
        variant={variant}
        size={size}
        icon={CalendarPlus}
        className={className}
        onClick={() => {
          if (file === "none") download();
          else setFile("earlier");
          setOpen(true);
        }}
      >
        Add your dates to your calendar
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        // anchored at the top: switching the calendar app changes the steps' height, not the dialog's place
        align="top"
        title="Add your dates to your calendar"
        description={
          file === "earlier"
            ? "Your calendar file (ordnung.ics) is in your Downloads. It has every open date and send-by day, with reminders. Download it again when new letters bring new dates."
            : "Your calendar file (ordnung.ics) is downloading. It has every open date and send-by day, with reminders. Import it once — do it again when new letters bring new dates."
        }
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
          <CalendarGuideSteps guide={guide} />
          <ul className="space-y-1.5 rounded-lg bg-surface-2/70 px-3.5 py-3 text-sm leading-5 text-muted">
            <li className="flex gap-2">
              <BellRing className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                {reminders ? `Reminders: ${reminders}` : "Reminders follow your settings"} (
                <Link to="/settings?section=reminders" onClick={() => setOpen(false)} className="font-medium text-accent underline underline-offset-2 hover:no-underline">
                  change them in Settings
                </Link>
                ).
              </span>
            </li>
            <li className="flex gap-2">
              <HardDrive className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              The file is made on {theComputer(phone)} — nothing is uploaded anywhere.
            </li>
          </ul>
        </div>
      </Dialog>
    </>
  );
}
