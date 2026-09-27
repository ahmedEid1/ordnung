import { useId, useState, type FormEvent } from "react";
import { CircleCheck, Phone, PhoneCall, Trash2 } from "lucide-react";
import { useCalls, useCreateCall, useDeleteCall, useUpdateCall } from "@/api/hooks";
import type { Case, CallNote } from "@/api/types";
import { Button, IconButton } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Money } from "@/components/ui/Money";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { callNoteProblems, type CallNoteDraft as Draft } from "./calls";

const SUMMARY_MAX = 2000;
const PROMISE_MAX = 300;
const CONTACT_MAX = 120;

function NoteForm({ partyId, cases, onDone }: { partyId: string; cases: Case[]; onDone: () => void }) {
  const today = useTodayISO();
  const create = useCreateCall();
  const [d, setD] = useState<Draft>({ calledOn: today, contact: "", summary: "", promise: "", promiseDue: "", amount: "", caseId: "" });
  const [tried, setTried] = useState(false);
  const problems = callNoteProblems(d, today);
  const shown = tried ? problems : {};
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setD((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (Object.keys(problems).length) return;
    create.mutate(
      {
        party_id: partyId,
        case_id: d.caseId || null,
        called_on: d.calledOn,
        contact: d.contact.trim() || null,
        summary: d.summary.trim(),
        promise: d.promise.trim() || null,
        promise_due: d.promiseDue || null,
        promise_amount: d.amount.trim() ? Number(d.amount.replace(",", ".")) : null,
      },
      {
        onSuccess: (note) => {
          toast.success("Call noted", {
            description: note.promise_due ? "Its promise is on your Waiting for list." : "Kept with this contact.",
          });
          onDone();
        },
      },
    );
  };

  return (
    <form onSubmit={submit} noValidate aria-label="Note a call" className="space-y-3 rounded-xl border border-line bg-surface p-3.5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="When" error={shown.calledOn}>
          <Input type="date" value={d.calledOn} max={today} onChange={set("calledOn")} required />
        </Field>
        <Field label="Who you spoke to" optional>
          <Input value={d.contact} onChange={set("contact")} maxLength={CONTACT_MAX} placeholder="e.g. Frau Weber, billing" autoComplete="off" />
        </Field>
      </div>
      <Field label="What was said" error={shown.summary}>
        <Textarea value={d.summary} onChange={set("summary")} maxLength={SUMMARY_MAX} rows={3} className="min-h-20" required />
      </Field>
      <Field label="What they promised" optional error={shown.promise} hint="A promise with a day goes on your Waiting for list.">
        <Input value={d.promise} onChange={set("promise")} maxLength={PROMISE_MAX} placeholder="e.g. Refund of the September fee" autoComplete="off" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="By" optional error={shown.promiseDue}>
          <Input type="date" value={d.promiseDue} min={d.calledOn || undefined} onChange={set("promiseDue")} />
        </Field>
        <Field label="Amount (€)" optional error={shown.amount}>
          <Input value={d.amount} onChange={set("amount")} inputMode="decimal" placeholder="29.90" autoComplete="off" />
        </Field>
      </div>
      {cases.length ? (
        <Field label="Thread" optional hint="A letter in this thread after the call is shown as a possible answer.">
          <Select value={d.caseId} onChange={set("caseId")}>
            <option value="">No thread</option>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2 pt-1">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Save note
        </Button>
      </div>
    </form>
  );
}

function PromiseLine({ note, today }: { note: CallNote; today: string }) {
  if (!note.promise) return null;
  const kept = Boolean(note.promise_kept_on);
  return (
    <p className={cn("mt-2 rounded-lg px-2.5 py-1.5 text-[13px] leading-5", kept ? "bg-ok-soft text-ok-ink" : "bg-surface-2 text-ink")}>
      <span className="font-medium">Promised: </span>
      <span className="[overflow-wrap:anywhere]">{note.promise}</span>
      {note.promise_amount != null ? (
        <>
          {" · "}
          <Money amount={note.promise_amount} />
        </>
      ) : null}
      {kept ? (
        <span className="block">
          Kept · <DateText date={note.promise_kept_on} style="short" />
        </span>
      ) : note.promise_due ? (
        <span className="block">
          By <Countdown date={note.promise_due} showDate className={note.promise_due < today ? "" : "text-muted"} />
        </span>
      ) : null}
    </p>
  );
}

function NoteRow({ note }: { note: CallNote }) {
  const today = useTodayISO();
  const fmt = useFormatDate();
  const update = useUpdateCall();
  const remove = useDeleteCall();
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="flex items-start gap-2">
        <PhoneCall className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
        <p className="min-w-0 flex-1 text-[13px] text-muted">
          <DateText date={note.called_on} style="short" className="font-medium text-ink" />
          {note.contact ? <span className="[overflow-wrap:anywhere]"> · {note.contact}</span> : null}
        </p>
        <IconButton icon={Trash2} label={`Delete the note of the call on ${fmt(note.called_on)}`} size="sm" className="-mr-1.5 -mt-1" onClick={() => setConfirming(true)} />
      </div>
      <p className="mt-1 whitespace-pre-line text-[13.5px] leading-relaxed text-ink/90 [overflow-wrap:anywhere]">{note.summary}</p>
      <PromiseLine note={note} today={today} />
      {note.promise ? (
        <div className="mt-2">
          <Button
            variant="link"
            size="sm"
            icon={note.promise_kept_on ? undefined : CircleCheck}
            loading={update.isPending}
            onClick={() =>
              update.mutate(
                { id: note.id, kept: !note.promise_kept_on },
                { onSuccess: (n) => toast.success(n.promise_kept_on ? "Marked as kept" : "Waiting for it again", { description: note.promise ?? undefined }) },
              )
            }
          >
            {note.promise_kept_on ? "Not kept after all" : "They kept it"}
          </Button>
        </div>
      ) : null}
      {confirming ? (
        <div role="group" aria-label="Delete this note?" className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2 text-[13px]">
          <span className="text-ink">Delete this note for good?</span>
          <Button size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutateAsync(note.id).then(() => toast.success("Note deleted"), () => undefined)}>
            Delete
          </Button>
          <Button size="sm" onClick={() => setConfirming(false)}>
            Keep it
          </Button>
        </div>
      ) : null}
    </li>
  );
}

/**
 * "Calls" in the People & organisations drawer: phone calls the person noted (Gesprächsnotizen)
 * and an inline form to note one — when, with whom, what was said, what they promised. A promise
 * with a day is waited for. Nothing is sent anywhere; no AI reads it.
 */
export function CallNotes({ partyId, cases }: { partyId: string; cases: Case[] }) {
  const q = useCalls({ party_id: partyId });
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const notes = q.data ?? [];
  return (
    <section aria-labelledby={headingId} className="mt-7 first:mt-0">
      <div className="mb-2.5 flex items-center gap-2">
        <h3 id={headingId} tabIndex={-1} className="flex-1 text-[12px] font-semibold uppercase tracking-[0.07em] text-muted outline-none">
          Calls
          {notes.length ? <span className="ml-1 font-medium text-muted">· {notes.length}</span> : null}
        </h3>
        {!open ? (
          <Button size="sm" variant="soft" icon={Phone} onClick={() => setOpen(true)}>
            Note a call
          </Button>
        ) : null}
      </div>
      {open ? <NoteForm partyId={partyId} cases={cases} onDone={() => setOpen(false)} /> : null}
      {q.isPending ? (
        <Skeleton className="h-16 w-full rounded-xl" />
      ) : q.isError ? (
        <p className="text-[13px] text-muted">
          Couldn't load the call notes.{" "}
          <Button variant="link" size="sm" onClick={() => void q.refetch()}>
            Try again
          </Button>
        </p>
      ) : notes.length ? (
        <ul className={cn("space-y-2", open && "mt-3")}>
          {notes.map((n) => (
            <NoteRow key={n.id} note={n} />
          ))}
        </ul>
      ) : !open ? (
        <p className="text-[13px] leading-5 text-muted">No calls noted. After a call, note what was said and what they promised — a promise with a day is waited for.</p>
      ) : null}
    </section>
  );
}
