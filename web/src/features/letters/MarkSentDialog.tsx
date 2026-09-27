import { useId, useMemo, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import type { Draft, SendChannelKind } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Field";
import { SEND_CHANNEL_COPY, TONES, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { followUpDate, sendChoices, type SendChoice } from "./logic";

export interface MarkSentDialogProps {
  open: boolean;
  onClose: () => void;
  draft: Draft;
  onConfirm: (channel: SendChannelKind, date: string) => void;
  pending?: boolean;
}

function ChoiceRow({ c, selected, onSelect }: { c: SendChoice; selected: boolean; onSelect: () => void }) {
  const copy = copyFor(SEND_CHANNEL_COPY, c.channel);
  const Icon = copy.icon;
  const tone = TONES[c.allowed ? copy.tone : "neutral"];
  return (
    <label
      className={cn(
        "relative flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-line-strong",
      )}
    >
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", tone.soft, tone.icon)}>
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1 text-[14px] text-ink">
        <span className="block font-medium [overflow-wrap:anywhere]">{c.label}</span>
        {!c.allowed ? (
          <span className="block text-[12.5px] text-warn-ink">Not enough for this letter</span>
        ) : c.recommended ? (
          <span className="block text-[12.5px] text-ok-ink">Recommended</span>
        ) : null}
      </span>
      {/* the radio itself is the round mark on the right (the whole row is its label and shows the focus ring) */}
      <span className="relative grid size-6 shrink-0 place-items-center">
        <input
          type="radio"
          name="sent-channel"
          value={c.channel}
          checked={selected}
          onChange={onSelect}
          className="peer absolute inset-0 m-0 size-6 cursor-pointer appearance-none rounded-full border border-line-strong bg-surface outline-none checked:border-accent checked:bg-accent"
        />
        <Check className="pointer-events-none relative size-3.5 text-on-accent opacity-0 peer-checked:opacity-100" strokeWidth={3} aria-hidden />
      </span>
    </label>
  );
}

/**
 * "Mark as sent" (or, for a sent letter, "Change how it was sent"): how and when. The ways are the
 * ones "How to send it" names for this letter, in its words; the usual others wait behind "Another
 * way". The day can't be before the letter was drafted or after today. Ordnung then adds a to-do to
 * check for a reply in 21 days (35 for a data request).
 */
export function MarkSentDialog({ open, onClose, draft, onConfirm, pending }: MarkSentDialogProps) {
  const today = useTodayISO();
  const dateId = useId();
  const choices = useMemo(() => sendChoices(draft.send_guidance), [draft.send_guidance]);
  const resending = draft.status === "sent";
  const initial = (resending ? choices.find((c) => c.channel === draft.sent_channel) : null) ?? choices.find((c) => c.allowed && !c.other) ?? null;
  const [channel, setChannel] = useState<SendChannelKind | null>(initial?.channel ?? null);
  const [showOthers, setShowOthers] = useState(Boolean(initial?.other));
  const [date, setDate] = useState((resending && draft.sent_at?.slice(0, 10)) || today);
  const chosen = choices.find((c) => c.channel === channel) ?? null;
  const offered = choices.filter((c) => !c.other);
  const others = choices.filter((c) => c.other);

  // not before the letter was drafted, not in the future
  const drafted = draft.created_at.slice(0, 10);
  const earliest = drafted <= today ? drafted : today;
  const wellFormed = /^\d{4}-\d{2}-\d{2}$/.test(date);
  const validDate = wellFormed && date <= today && date >= earliest;
  const sendBy = draft.send_guidance?.send_by ?? null;
  const mustArrive = draft.send_guidance?.must_arrive_by ?? null;
  const late = validDate && ((sendBy && date > sendBy && (channel === "letter" || channel === "registered_letter")) || (mustArrive && date > mustArrive));
  const range = `Choose a day from ${formatDate(earliest, { style: "short", today })}, when you drafted it, to today.`;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={resending ? "Change how it was sent" : "Mark as sent"}
      description={
        resending
          ? "Correct the way or the day — the reminder to check for an answer moves with it."
          : "How and when did you send it? Ordnung adds a to-do to check for an answer — nothing is sent from here."
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={Check} disabled={!channel || !validDate} loading={pending} onClick={() => channel && onConfirm(channel, date)}>
            {resending ? "Save" : "Mark as sent"}
          </Button>
        </>
      }
    >
      <fieldset>
        <legend className="mb-2 text-[13px] font-medium text-ink">How did you send it?</legend>
        <div className="space-y-1.5">
          {offered.map((c) => (
            <ChoiceRow key={c.channel} c={c} selected={channel === c.channel} onSelect={() => setChannel(c.channel)} />
          ))}
          {others.length && !showOthers ? (
            <button
              type="button"
              onClick={() => setShowOthers(true)}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-[13px] font-medium text-accent hover:bg-accent-soft/60 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            >
              <ChevronDown className="size-3.5" aria-hidden />
              Another way
            </button>
          ) : null}
          {showOthers
            ? others.map((c) => <ChoiceRow key={c.channel} c={c} selected={channel === c.channel} onSelect={() => setChannel(c.channel)} />)
            : null}
        </div>
      </fieldset>

      {chosen && !chosen.allowed ? (
        <Callout tone="warn" className="mt-3" title="This way may not count">
          {draft.send_guidance?.form === "written_form"
            ? `This letter must be signed by hand on paper. If you only sent it this way, also post a signed copy${sendBy ? ` by ${formatDate(sendBy, { style: "short", today })}` : ""}.`
            : "This way of sending isn't accepted for this letter. Please also send it one of the recommended ways."}
        </Callout>
      ) : null}

      <div className="mt-5 flex flex-col gap-1.5">
        <label htmlFor={dateId} className="text-sm font-medium text-ink">
          When?
        </label>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Input
            id={dateId}
            type="date"
            value={date}
            min={earliest}
            max={today}
            onChange={(e) => setDate(e.target.value)}
            aria-describedby={`${dateId}-hint`}
            aria-invalid={wellFormed && !validDate ? true : undefined}
            className="w-44"
          />
          {validDate ? (
            <span className="text-[14px] font-medium text-ink" aria-hidden data-chosen-day>
              {formatDate(date, { style: "short", today })}
            </span>
          ) : null}
        </div>
        <p id={`${dateId}-hint`} className={cn("text-sm leading-5", wellFormed && !validDate ? "font-medium text-danger-ink" : "text-muted")}>
          {validDate ? `We'll remind you to check for a reply on ${formatDate(followUpDate(date, draft.kind), { style: "short", today })}.` : range}
        </p>
      </div>

      {late ? (
        <Callout tone="warn" className="mt-3" title="That's after the send-by date">
          It may arrive too late. Keep your proof of sending{mustArrive ? `, and if it matters, ask the recipient to confirm it arrived by ${formatDate(mustArrive, { today })}` : ""}.
        </Callout>
      ) : null}
    </Dialog>
  );
}
