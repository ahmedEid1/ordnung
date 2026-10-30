import { Fragment, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import { qk, useHealth, useUpdateSettings } from "@/api/hooks";
import type { AppSettings, Health, PictureTextStatus } from "@/api/types";
import { Switch } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { isStaticDemo } from "@/mocks/mode";
import { cn } from "@/lib/utils";
import { SaveBar, SettingsCard } from "./SettingsCard";

/** The card's words (ADR 0024). Code in backticks is set as code. */
export const PICTURE_TEXT_COPY = {
  title: "Text in pictures",
  description: "Words in photos and scans Claude isn't reading, read on this computer so search can find those letters.",
  switchLabel: "Read the words in photos and scans Claude isn't reading",
  switchDescription:
    "With Tesseract installed, Ordnung reads them here, for search only: never checked, never shown and never sent to Claude. Off: those letters are found by their name only, and the words read before are deleted.",
  /** Before the doctor's install line, when Tesseract isn't installed. */
  notInstalled: "Not installed on this computer (optional).",
  /** Above the switch while `ORDNUNG_OCR=off` turns it off on this computer. */
  variable:
    "Turned off by `ORDNUNG_OCR=off` while Ordnung runs: it reads no pictures, whatever this switch says. Your choice here counts once the variable is unset and Ordnung is started again.",
  /** The static demo has no computer to look at. */
  staticDemo: "In Ordnung on your computer, this line says whether Tesseract is installed there.",
  toastOff: ["Text in pictures is off.", "The words Ordnung had read in pictures are deleted. Search finds those letters by their name."],
  toastOn: ["Text in pictures is on.", "Ordnung reads the pictures of letters Claude isn't reading, one page at a time."],
  toastInstall: ["Text in pictures is on.", "Install Tesseract to have pictures read (see the line under the switch)."],
  /** On, where Tesseract is there but can't be used (too old, no German or English data, no answer). */
  toastFix: ["Text in pictures is on.", "Tesseract needs a fix before pictures are read (see the line under the switch)."],
  /** On, in the static demo: nothing is read there. */
  toastStaticDemo: [
    "Text in pictures is on.",
    "In Ordnung on your computer, this reads the pictures of letters Claude isn't reading, with Tesseract installed there.",
  ],
  toastVariable: ["Saved.", "It counts once ORDNUNG_OCR is unset."],
} as const;

const code = "rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-ink";

/** A line with its `commands` set as code (never literal backticks), as Claude connection shows the check's words. */
function WithCode({ text }: { text: string }) {
  return (
    <>
      {text.split(/`([^`]+)`/).map((part, i) =>
        i % 2 ? (
          <code key={i} className={cn(code, "break-words")}>
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

type Tone = "muted" | "info" | "warn";

/** The line under the switch for this computer's state (none while off: the switch says it). */
function statusLine(status: PictureTextStatus | null | undefined): { tone: Tone; text: string } | null {
  if (!status) return null;
  switch (status.state) {
    case "reading":
      return { tone: "muted", text: status.detail };
    case "not_installed":
      return { tone: "info", text: [PICTURE_TEXT_COPY.notInstalled, status.fix].filter(Boolean).join(" ") };
    case "not_usable":
      return { tone: "warn", text: status.fix ? `${status.detail}. ${status.fix}` : status.detail };
    default:
      return null; // off, off_by_variable (the callout above the switch says it)
  }
}

const TONE: Record<Tone, string> = { muted: "text-muted", info: "text-ink/85", warn: "text-warn-ink" };

/** The toast after turning it on: pictures are read only where Tesseract reads; else it points to the line. */
function onToast(state: PictureTextStatus["state"] | undefined): readonly [string, string] {
  switch (state) {
    case "not_installed":
      return PICTURE_TEXT_COPY.toastInstall;
    case "not_usable":
      return PICTURE_TEXT_COPY.toastFix;
    case "off_by_variable":
      return PICTURE_TEXT_COPY.toastVariable;
    default:
      return PICTURE_TEXT_COPY.toastOn; // reading
  }
}

/**
 * Settings → Data → *Text in pictures* (ADR 0024): whether this computer reads the words in photos and scans Claude
 * isn't reading, for search only. Saved off, those words are deleted and search finds such letters by their name;
 * `ORDNUNG_OCR=off` turns it off on a computer whatever the switch says (the card says so, like the model pin under
 * Claude connection). The line under the switch is this computer's state in the doctor's words
 * (`health.picture_text`), asked again after a save. A paired phone has no Settings, so no card.
 */
export function PictureTextCard({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const qc = useQueryClient();
  const status = useHealth().data?.picture_text;
  const saved = settings.read_picture_text;
  const [read, setRead] = useState(saved);
  const dirty = read !== saved;
  const byVariable = status?.state === "off_by_variable";
  const staticDemo = isStaticDemo();
  const line = staticDemo ? (status && status.state !== "off" ? { tone: "muted" as const, text: PICTURE_TEXT_COPY.staticDemo } : null) : statusLine(status);

  const save = () =>
    update.mutateAsync({ read_picture_text: read }).then(async (s) => {
      setRead(s.read_picture_text);
      await qc.invalidateQueries({ queryKey: qk.health }); // the line follows what was saved
      const now = qc.getQueryData<Health>(qk.health)?.picture_text;
      const [title, description] = byVariable
        ? PICTURE_TEXT_COPY.toastVariable
        : !s.read_picture_text
          ? PICTURE_TEXT_COPY.toastOff
          : staticDemo
            ? PICTURE_TEXT_COPY.toastStaticDemo
            : onToast(now?.state);
      toast.success(title, { description });
    });

  return (
    <SettingsCard
      title={PICTURE_TEXT_COPY.title}
      id="set-data-picture-text"
      description={PICTURE_TEXT_COPY.description}
      footer={<SaveBar dirty={dirty} saving={update.isPending} onSave={save} onDiscard={() => setRead(saved)} />}
    >
      {byVariable && !staticDemo ? (
        <p
          data-testid="picture-text-variable"
          className="mb-4 flex items-start gap-2 rounded-xl border border-warn/30 bg-warn-soft/70 px-3.5 py-2.5 text-[13px] leading-5 text-ink/90"
        >
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <span>
            <WithCode text={PICTURE_TEXT_COPY.variable} />
          </span>
        </p>
      ) : null}
      <Switch checked={read} onCheckedChange={setRead} label={PICTURE_TEXT_COPY.switchLabel} description={PICTURE_TEXT_COPY.switchDescription} />
      {line ? (
        <p data-testid="picture-text-status" data-tone={line.tone} className={cn("mt-3 flex items-start gap-2 text-sm leading-5", TONE[line.tone])}>
          {line.tone === "warn" ? (
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          ) : line.tone === "info" ? (
            <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
          ) : null}
          <span className="min-w-0 wrap-anywhere">
            <WithCode text={line.text} />
          </span>
        </p>
      ) : null}
    </SettingsCard>
  );
}
