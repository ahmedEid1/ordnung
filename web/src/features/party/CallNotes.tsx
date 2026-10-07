import { useEffect, useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { CircleCheck, Phone, PhoneCall, Trash2, TriangleAlert } from "lucide-react";
import { useCalls, useCreateCall, useDeleteCall, useUpdateCall } from "@/api/hooks";
import type { Case, CallNote } from "@/api/types";
import { Button, IconButton } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { DateText } from "@/components/ui/DateText";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Money } from "@/components/ui/Money";
import { MoneyInput, moneyReadBack } from "@/components/ui/MoneyInput";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useNoteCallRequest } from "@/lib/party-drawer";
import { useFormatDate, useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { focusWhenReady } from "@/features/today/focus";
import { ComputerOnly } from "@/features/phone/ComputerOnly";
import { CALL_FIELDS, callNoteProblems, clearCallDraft, draftHasText, keepCallDraft, loadCallDraft, promisedAmount, type CallNoteDraft as Draft } from "./calls";

const SUMMARY_MAX = 2000;
const PROMISE_MAX = 300;
/** From this many characters left, "What they promised" says how many remain. */
const PROMISE_COUNT_FROM = 50;
const CONTACT_MAX = 120;

/**
 * The drawer's check before it closes (Escape, the backdrop, ×): `true` means "not yet" — a call note
 * is half-written, and the form now asks whether to discard it.
 */
export type CloseGuard = RefObject<(() => boolean) | null>;

interface NoteFormProps {
  partyId: string;
  cases: Case[];
  caseId?: string;
  /** How often closing the drawer was tried while the note has text (0: not asked). */
  asking: number;
  /** Whether the form has anything typed (read by the drawer's close guard). */
  hasTextRef: RefObject<boolean>;
  onCancel: () => void;
  onSaved: () => void;
  onKeepWriting: () => void;
  onDiscard: () => void;
}

function NoteForm({ partyId, cases, caseId = "", asking, hasTextRef, onCancel, onSaved, onKeepWriting, onDiscard }: NoteFormProps) {
  const today = useTodayISO();
  const create = useCreateCall();
  // a note half-written before (the drawer closed, a link followed, a reload) comes back as it was
  const [d, setD] = useState<Draft>(() => {
    const kept = loadCallDraft(partyId);
    return kept ? { ...kept, caseId: caseId || kept.caseId } : { calledOn: today, contact: "", summary: "", promise: "", promiseDue: "", amount: "", caseId };
  });
  const [tried, setTried] = useState(false);
  const ids = useId();
  const fieldId = (k: keyof Draft) => `${ids}-${k}`;
  const problems = callNoteProblems(d, today);
  const shown = tried ? problems : {};
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setD((prev) => ({ ...prev, [k]: e.target.value }));
  const promiseLeft = PROMISE_MAX - d.promise.length;
  const keepRef = useRef<HTMLButtonElement>(null);
  const askRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // every keystroke is kept for this party at once
  useEffect(() => {
    keepCallDraft(partyId, d);
    hasTextRef.current = draftHasText(d);
  }, [partyId, d, hasTextRef]);
  useEffect(
    () => () => {
      hasTextRef.current = false;
    },
    [hasTextRef],
  );
  // closing was tried: the question comes into view, its safe answer focused
  useEffect(() => {
    if (!asking) return;
    askRef.current?.scrollIntoView?.({ block: "nearest" });
    keepRef.current?.focus({ preventScroll: true });
  }, [asking]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    const first = CALL_FIELDS.find((k) => problems[k]);
    if (first) {
      // the first field to fix, in the middle of the drawer (never under its header)
      const el = document.getElementById(fieldId(first));
      el?.scrollIntoView?.({ block: "center" });
      el?.focus({ preventScroll: true });
      return;
    }
    create
      .mutateAsync({
        party_id: partyId,
        case_id: d.caseId || null,
        called_on: d.calledOn,
        contact: d.contact.trim() || null,
        summary: d.summary.trim(),
        // a promise is one line wherever it is shown
        promise: d.promise.replace(/\s+/g, " ").trim() || null,
        promise_due: d.promiseDue || null,
        promise_amount: promisedAmount(d),
      })
      .then(
        (note) => {
          // saved: nothing half-written is left, even when the drawer was closed meanwhile
          clearCallDraft(partyId);
          toast.success("Call noted", {
            description: note.promise_due ? "Its promise is on your Waiting for list." : "Kept with this contact.",
          });
          if (mounted.current) onSaved();
        },
        () => undefined, // the error is said by the mutation; the note stays as typed
      );
  };

  const askId = `${ids}-ask`;
  return (
    <form id={`${ids}-form`} onSubmit={submit} noValidate aria-label="Note a call" className="space-y-3 rounded-xl border border-line bg-surface p-3.5">
      {asking ? (
        <div
          ref={askRef}
          role="group"
          aria-labelledby={askId}
          className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-warn/30 bg-warn-soft/70 px-3 py-2.5 text-[13px] leading-5"
        >
          <p id={askId} className="flex min-w-0 flex-1 basis-52 items-start gap-2 text-ink">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn-ink" aria-hidden />
            <span>
              <span className="font-medium">Discard this call note?</span> It isn't saved yet.
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            <Button ref={keepRef} size="sm" onClick={onKeepWriting}>
              Keep writing
            </Button>
            <Button size="sm" variant="danger" onClick={onDiscard}>
              Discard
            </Button>
          </div>
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={fieldId("calledOn")} label="When" error={shown.calledOn}>
          <Input type="date" value={d.calledOn} max={today} onChange={set("calledOn")} required autoFocus />
        </Field>
        <Field id={fieldId("contact")} label="Who you spoke to" optional>
          <Input value={d.contact} onChange={set("contact")} maxLength={CONTACT_MAX} placeholder="e.g. Frau Weber, billing" autoComplete="off" />
        </Field>
      </div>
      <Field id={fieldId("summary")} label="What was said" error={shown.summary}>
        <Textarea value={d.summary} onChange={set("summary")} maxLength={SUMMARY_MAX} rows={3} className="min-h-20" required />
      </Field>
      <Field
        id={fieldId("promise")}
        label="What they promised"
        optional
        error={shown.promise}
        hint={
          <>
            A promise with a day goes on your Waiting for list.
            {promiseLeft <= PROMISE_COUNT_FROM ? ` ${promiseLeft} ${promiseLeft === 1 ? "character" : "characters"} left.` : null}
          </>
        }
      >
        {/* a few lines that grow with the text: a long promise can be read whole while it is written */}
        <Textarea
          value={d.promise}
          onChange={set("promise")}
          maxLength={PROMISE_MAX}
          rows={2}
          placeholder="e.g. Refund of the September fee"
          autoComplete="off"
          className="min-h-16 max-h-48 [field-sizing:content]"
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={fieldId("promiseDue")} label="By" optional error={shown.promiseDue}>
          <Input type="date" value={d.promiseDue} min={d.calledOn || undefined} onChange={set("promiseDue")} />
        </Field>
        <Field id={fieldId("amount")} label="Amount" optional error={shown.amount} hint={moneyReadBack(d.amount)}>
          <MoneyInput value={d.amount} onChange={set("amount")} />
        </Field>
      </div>
      {cases.length ? (
        <Field id={fieldId("caseId")} label="Thread" optional hint="A letter in this thread after the call is shown as a possible answer.">
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
        <Button onClick={onCancel}>Cancel</Button>
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

/** A usable button (a busy one is disabled, and focus can't rest on it). */
const ready = (el: HTMLButtonElement | null) => (el && !el.disabled ? el : null);

function NoteRow({ note, headingId }: { note: CallNote; headingId: string }) {
  const today = useTodayISO();
  const fmt = useFormatDate();
  const update = useUpdateCall();
  const remove = useDeleteCall();
  const [confirming, setConfirming] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const trashRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const rowId = `call-note-${note.id}`;
  // the question opens where you are: its "Delete" focused (Tab goes on to "Keep it")
  useEffect(() => {
    if (confirming) deleteRef.current?.focus();
  }, [confirming]);
  return (
    <li id={rowId} className="rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="flex items-start gap-2">
        <PhoneCall className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
        <p className="min-w-0 flex-1 text-[13px] text-muted">
          <DateText date={note.called_on} style="short" className="font-medium text-ink" />
          {note.contact ? <span className="[overflow-wrap:anywhere]"> · {note.contact}</span> : null}
        </p>
        {/* notes are deleted on the computer (a paired phone adds and corrects them) */}
        <ComputerOnly what="Delete this note">
          <IconButton
            ref={trashRef}
            icon={Trash2}
            label={`Delete the note of the call on ${fmt(note.called_on)}`}
            size="sm"
            className="-mr-1.5 -mt-1"
            onClick={() => setConfirming(true)}
          />
        </ComputerOnly>
      </div>
      {/* right under the header row, so it comes next after the trash button in the Tab order */}
      {confirming ? (
        <div role="group" aria-label="Delete this note?" className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-2 text-[13px]">
          <span className="text-ink">Delete this note for good?</span>
          <Button
            ref={deleteRef}
            size="sm"
            variant="danger"
            loading={remove.isPending}
            onClick={() =>
              remove.mutateAsync(note.id).then(
                () => {
                  toast.success("Note deleted");
                  // once its row is gone, focus the section heading (never <body>)
                  focusWhenReady(() => (document.getElementById(rowId) ? null : document.getElementById(headingId)));
                },
                // not deleted: back to the question's "Delete" (it was busy, so focus had left it)
                () => focusWhenReady(() => ready(deleteRef.current)),
              )
            }
          >
            Delete
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setConfirming(false);
              trashRef.current?.focus(); // "Keep it" leaves with the question: focus goes back where it began
            }}
          >
            Keep it
          </Button>
        </div>
      ) : null}
      <p className="mt-1 whitespace-pre-line text-[13.5px] leading-relaxed text-ink/90 [overflow-wrap:anywhere]">{note.summary}</p>
      <PromiseLine note={note} today={today} />
      {note.promise ? (
        <div className="mt-2">
          <Button
            ref={toggleRef}
            variant="link"
            size="sm"
            icon={note.promise_kept_on ? undefined : CircleCheck}
            loading={update.isPending}
            onClick={() =>
              update.mutate(
                { id: note.id, kept: !note.promise_kept_on },
                {
                  onSuccess: (n) => toast.success(n.promise_kept_on ? "Marked as kept" : "Waiting for it again", { description: note.promise ?? undefined }),
                  // busy, the button was disabled and focus fell to <body>: it comes back to the button (now saying the opposite)
                  onSettled: () => focusWhenReady(() => ready(toggleRef.current)),
                },
              )
            }
          >
            {note.promise_kept_on ? "Not kept after all" : "They kept it"}
          </Button>
        </div>
      ) : null}
    </li>
  );
}

export interface CallNotesProps {
  partyId: string;
  cases: Case[];
  /** The section heading's id (the drawer's jump links and focus land on it). */
  headingId?: string;
  /** Filled with the check the drawer runs before it closes (see {@link CloseGuard}). */
  closeGuardRef?: CloseGuard;
  /** "Discard" was chosen while closing: the note is gone, close the drawer now. */
  onDiscarded?: () => void;
}

/**
 * "Calls" in the People & organisations drawer: phone calls the person noted (Gesprächsnotizen)
 * and an inline form to note one — when, with whom, what was said, what they promised. A promise
 * with a day is waited for. Nothing is sent anywhere; no AI reads it. Opened with `?call=` (Waiting
 * for's "Note a call"), the form is open from the start, with the letter's or the call's thread chosen.
 *
 * A half-written note is never lost: it is kept for the party (`calls.ts`) and the form opens with it
 * again; closing the drawer while it has text first asks "Discard this call note?".
 */
export function CallNotes({ partyId, cases, headingId: givenId, closeGuardRef, onDiscarded }: CallNotesProps) {
  const q = useCalls({ party_id: partyId });
  const request = useNoteCallRequest();
  const asked = request.asked;
  // a note left half-written opens again with the drawer
  const [opened, setOpen] = useState(() => loadCallDraft(partyId) !== null);
  const [asking, setAsking] = useState(0);
  // open when the person asked here, or came asking (also again while the drawer is open)
  const open = opened || asked !== null;
  const ownId = useId();
  const headingId = givenId ?? ownId;
  const noteButtonId = `${headingId}-note`;
  const notes = q.data ?? [];
  const askedCase = asked && cases.some((c) => c.id === asked) ? asked : "";
  const section = useRef<HTMLElement>(null);
  const hasTextRef = useRef(false);
  // came to note a call: the section comes to the top of the drawer, the form's first field focused below
  useEffect(() => {
    if (asked !== null) section.current?.scrollIntoView?.({ block: "start" });
  }, [asked]);
  // the drawer asks before it closes: a note with text is not thrown away unasked
  useEffect(() => {
    if (!closeGuardRef) return;
    closeGuardRef.current = () => {
      if (!open || !hasTextRef.current) return false;
      setAsking((n) => n + 1);
      return true;
    };
    return () => {
      closeGuardRef.current = null;
    };
  }, [closeGuardRef, open]);
  // the form goes: back to the button that opened it (the request is done: a reload doesn't reopen it)
  const close = () => {
    setOpen(false);
    setAsking(0);
    request.done();
    focusWhenReady(() => document.getElementById(noteButtonId));
  };
  const cancel = () => {
    clearCallDraft(partyId);
    close();
  };
  const keepWriting = () => {
    setAsking(0);
    const form = section.current?.querySelector("form");
    // back to where the words are
    form?.querySelector<HTMLElement>("textarea")?.focus();
  };
  const discard = () => {
    clearCallDraft(partyId);
    hasTextRef.current = false;
    setAsking(0);
    setOpen(false); // (the drawer's content stays while it slides away: without the note)
    if (onDiscarded) onDiscarded();
    else close();
  };
  return (
    <section ref={section} aria-labelledby={headingId} className="mt-7 scroll-mt-4 first:mt-0">
      {/* with no calls noted this row is the whole section: the heading and "Note a call" */}
      <div className={cn("flex min-h-8 items-center gap-2", (open || notes.length || q.isPending || q.isError) && "mb-2.5")}>
        <h3 id={headingId} tabIndex={-1} className="eyebrow flex-1 scroll-mt-4 outline-none">
          Calls
          {notes.length ? <span className="ml-1 font-medium text-muted">· {notes.length}</span> : null}
        </h3>
        {!open ? (
          <Button id={noteButtonId} size="sm" variant="soft" icon={Phone} onClick={() => setOpen(true)}>
            Note a call
          </Button>
        ) : null}
      </div>
      {open ? (
        <NoteForm
          key={askedCase}
          partyId={partyId}
          cases={cases}
          caseId={askedCase}
          asking={asking}
          hasTextRef={hasTextRef}
          onCancel={cancel}
          onSaved={close}
          onKeepWriting={keepWriting}
          onDiscard={discard}
        />
      ) : null}
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
            <NoteRow key={n.id} note={n} headingId={headingId} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
