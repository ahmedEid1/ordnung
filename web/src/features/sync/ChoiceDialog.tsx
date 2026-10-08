/**
 * "Which Ordnung do you want to keep?" (design §12.2): both computers changed something while they couldn't see
 * each other, and the two can't be combined. One radio per side — none chosen at first — with its letters, how many
 * were added since the two last agreed and the newest titles; its open and done dates and to-dos, its notes, its
 * latest changes and when it was saved (sides that differ only in to-dos or edits are told apart by these). The side not kept is saved as an encrypted copy on
 * its own computer, so nothing is thrown away. A side still arriving can be chosen: the dialog then waits for it,
 * with Cancel. Choosing makes this computer the one in use.
 */
import { useEffect, useId, useState } from "react";
import { Check, Hourglass, X } from "lucide-react";
import { ApiError } from "@/api/client";
import { useChooseSync, useTakeOver } from "@/api/hooks";
import type { SyncChoice, SyncSide, SyncStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { focusWhenReady } from "@/features/today/focus";
import { chosenMessage, choiceSideLine, sideArrivingLine, sideContentsLine, sideLatestLine, sideName, waitingLine } from "@/features/settings/sync";
import { formatDate, formatDateTime, formatTimeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const ERROR_ID = "sync-choice-error";

const failed = (err: unknown) => (err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?");

/** One side of the choice as a radio card: who, how many letters, the newest titles, and whether it is all here. */
export function SideOption({
  side,
  name,
  checked,
  onChoose,
  joining = false,
  disabled = false,
}: {
  side: SyncSide;
  name: string;
  checked: boolean;
  onChoose: () => void;
  joining?: boolean;
  disabled?: boolean;
}) {
  const arriving = sideArrivingLine(side);
  const latest = sideLatestLine(side);
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition-colors",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-line-strong",
        disabled && "cursor-default opacity-70",
      )}
    >
      <input type="radio" name={name} value={side.key} checked={checked} onChange={onChoose} disabled={disabled} className="mt-1 size-4 shrink-0 accent-[var(--color-accent)]" />
      <span className="min-w-0 flex-1 text-[13.5px] leading-5">
        <span className="block font-semibold text-ink [overflow-wrap:anywhere]">{sideName(side)}</span>
        <span className="block text-ink/85">
          {choiceSideLine(side, joining)}
          {side.newest.length && !joining ? ": " : null}
          {!joining
            ? side.newest.map((letter, i) => (
                <span key={`${letter.label}-${i}`}>
                  {i > 0 ? ", " : null}
                  <em className="not-italic font-medium text-ink" title={`Added ${formatDate(letter.added_on, { style: "medium" })}`}>
                    {letter.label}
                  </em>
                </span>
              ))
            : null}
        </span>
        {!joining ? <span className="block text-ink/85">{sideContentsLine(side)}</span> : null}
        {!joining && latest ? <span className="block text-[12.5px] text-muted [overflow-wrap:anywhere]">{latest}</span> : null}
        {!side.this && side.saved_at ? (
          <span className="block text-[12.5px] text-muted">
            Saved there {formatDateTime(side.saved_at)}
            {side.arrived_at ? `, arrived here ${formatTimeAgo(side.arrived_at)}` : ""}
          </span>
        ) : !side.this && side.arrived_at ? (
          <span className="block text-[12.5px] text-muted">Arrived here {formatTimeAgo(side.arrived_at)}</span>
        ) : null}
        {arriving ? (
          <span className="mt-0.5 flex items-center gap-1 text-[12.5px] font-medium text-warn-ink">
            <Hourglass className="size-3.5 shrink-0" aria-hidden />
            {arriving}
          </span>
        ) : null}
      </span>
    </label>
  );
}

/** "this computer (desktop) and anna-thinkpad" — who changed something. */
function whoChanged(sides: SyncSide[]) {
  const names = sides.map((s) => (s.this ? `this computer (${s.computer})` : s.computer));
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : (names[0] ?? "");
}

/** The dialog, open while `open` and the status holds a choice. */
export function ChoiceDialog({ open, onClose, status }: { open: boolean; onClose: () => void; status: SyncStatus }) {
  const choose = useChooseSync();
  const cancel = useTakeOver();
  const [picked, setPicked] = useState<number | null>(null);
  const name = useId();
  const choice: SyncChoice | null = status.choice;
  const sides = choice?.sides ?? [];
  const waitingFor = choice?.chosen != null ? sides.find((s) => s.key === choice.chosen) : undefined;
  const pending = choose.isPending || cancel.isPending;

  const close = () => {
    if (pending) return;
    choose.reset();
    setPicked(null);
    onClose();
  };

  const keep = () => {
    const side = sides.find((s) => s.key === picked);
    if (!side) return;
    choose.mutate(side.key, {
      onSuccess: (after) => {
        if (after.choice?.chosen === side.key) return; // it is still arriving: the dialog waits for it
        setPicked(null);
        onClose();
        const said = chosenMessage(side, sides);
        toast.success(said.title, { description: said.description });
      },
      onError: () => focusWhenReady(() => document.getElementById(ERROR_ID), 5000, { always: true }),
    });
  };

  const stopWaiting = () => cancel.mutate({ cancel: true }, { onSuccess: () => setPicked(null) });

  // the choice went (answered here or on the other computer, or its waiting side arrived): the dialog goes with it,
  // so a later choice doesn't open it by itself
  useEffect(() => {
    if (open && !choice && !pending) onClose();
  }, [open, choice, pending, onClose]);

  return (
    <Dialog
      open={open && choice !== null}
      onClose={close}
      size="md"
      title="Which Ordnung do you want to keep?"
      description={
        <>
          Since you last switched, Ordnung was changed on {whoChanged(sides)}, and the two can't be combined. Choose one. The other is saved as an
          encrypted backup on its own computer, so nothing is thrown away.
        </>
      }
      dismissible={!pending}
      footer={
        waitingFor ? (
          <Button icon={X} onClick={stopWaiting} loading={cancel.isPending}>
            Cancel
          </Button>
        ) : (
          <>
            <Button onClick={close} disabled={pending}>
              Not now
            </Button>
            <Button variant="primary" icon={Check} disabled={picked === null} loading={choose.isPending} onClick={keep}>
              Keep this one
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        {waitingFor ? (
          <Callout title={`Waiting for ${waitingFor.computer}'s Ordnung`} icon={Hourglass}>
            <p>
              {sideArrivingLine(waitingFor) ?? "Everything has arrived."} {waitingLine(waitingFor.computer)}
            </p>
          </Callout>
        ) : (
          <fieldset>
            <legend className="sr-only">Keep the Ordnung of</legend>
            <div className="space-y-2">
              {sides.map((side) => (
                <SideOption key={side.key} side={side} name={name} checked={picked === side.key} onChoose={() => setPicked(side.key)} disabled={pending} />
              ))}
            </div>
          </fieldset>
        )}
        {!waitingFor ? <p className="text-[12.5px] leading-5 text-muted">Choosing makes this computer the one in use.</p> : null}
        {choose.error || cancel.error ? (
          <div id={ERROR_ID} tabIndex={-1} className="rounded-xl">
            <Callout tone="danger" alert title="Nothing was changed">
              <span className="[overflow-wrap:anywhere]">{failed(choose.error ?? cancel.error)}</span>
            </Callout>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
