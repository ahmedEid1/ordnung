import { useMemo, useState } from "react";
import { Check } from "lucide-react";
import type { Draft, SendChannelKind } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { SEND_CHANNEL_COPY, TONES, copyFor } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { followUpDate, sendChoices } from "./logic";

export interface MarkSentDialogProps {
  open: boolean;
  onClose: () => void;
  draft: Draft;
  onConfirm: (channel: SendChannelKind, date: string) => void;
  pending?: boolean;
}

/** "Mark as sent": how and when — Ordnung then adds a to-do to check for a reply in 21 days. */
export function MarkSentDialog({ open, onClose, draft, onConfirm, pending }: MarkSentDialogProps) {
  const today = useTodayISO();
  const choices = useMemo(() => sendChoices(draft.send_guidance), [draft.send_guidance]);
  const [channel, setChannel] = useState<SendChannelKind | null>(choices.find((c) => c.allowed)?.channel ?? null);
  const [date, setDate] = useState(today);
  const chosen = choices.find((c) => c.channel === channel) ?? null;
  const sendBy = draft.send_guidance?.send_by ?? null;
  const mustArrive = draft.send_guidance?.must_arrive_by ?? null;
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= today;
  const late = validDate && ((sendBy && date > sendBy && (channel === "letter" || channel === "registered_letter")) || (mustArrive && date > mustArrive));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Mark as sent"
      description="How and when did you send it? Ordnung adds a to-do to check for an answer — nothing is sent from here."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={Check} disabled={!channel || !validDate} loading={pending} onClick={() => channel && onConfirm(channel, date)}>
            Mark as sent
          </Button>
        </>
      }
    >
      <fieldset>
        <legend className="mb-2 text-[13px] font-medium text-ink">How did you send it?</legend>
        <div className="space-y-1.5">
          {choices.map((c) => {
            const copy = copyFor(SEND_CHANNEL_COPY, c.channel);
            const Icon = copy.icon;
            const selected = channel === c.channel;
            return (
              <label
                key={c.channel}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors",
                  "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-line-strong",
                )}
              >
                <input type="radio" name="sent-channel" value={c.channel} checked={selected} onChange={() => setChannel(c.channel)} className="sr-only" />
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", TONES[copy.tone].soft, TONES[copy.tone].icon)}>
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 text-[14px] text-ink">
                  <span className="block truncate font-medium">{c.label}</span>
                  {!c.allowed ? <span className="block text-[12.5px] text-warn-ink">Not enough for this letter</span> : c.recommended ? <span className="block text-[12.5px] text-ok-ink">Recommended</span> : null}
                </span>
                <span className={cn("grid size-5 shrink-0 place-items-center rounded-full border", selected ? "border-accent bg-accent text-on-accent" : "border-line-strong")} aria-hidden>
                  {selected ? <Check className="size-3" strokeWidth={3} /> : null}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {chosen && !chosen.allowed ? (
        <Callout tone="warn" className="mt-3" title="This way may not count">
          {draft.send_guidance?.form === "written_form"
            ? "This letter must be signed by hand on paper. If you only sent it this way, please also post a signed copy."
            : "This way of sending isn't accepted for this letter. Please also send it one of the recommended ways."}
        </Callout>
      ) : null}

      <Field label="When?" className="mt-5" hint={validDate ? `We'll remind you to check for a reply on ${formatDate(followUpDate(date, draft.kind), { style: "short", today })}.` : "Choose a date up to today."}>
        <Input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} className="w-48" />
      </Field>

      {late ? (
        <Callout tone="warn" className="mt-3" title="That's after the send-by date">
          It may arrive too late. Keep your proof of sending{mustArrive ? `, and if it matters, ask the recipient to confirm it arrived by ${formatDate(mustArrive, { today })}` : ""}.
        </Callout>
      ) : null}
    </Dialog>
  );
}
