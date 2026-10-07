import { useId, useState } from "react";
import { Lock, Plus, Save } from "lucide-react";
import type { ProofEntry, ProofKind } from "@/api/types";
import { useAddProof, useUpdateProof } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { usePhoneCompanion } from "@/features/phone/client";
import { theComputer } from "@/features/phone/copy";
import { PROOF_KIND_COPY, copyFor } from "@/lib/copy";
import { useTodayISO } from "@/lib/today";
import { PROOF_DAY_LABEL, SENDING_DAY_KINDS, proofKindsFor } from "./proof";

const NOTE_MAX = 500;
/** From this many characters left, the note says how many remain. */
const NOTE_COUNT_FROM = 100;
/** What the file picker offers (the server checks every file like any upload). */
const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,.eml,message/rfc822,text/plain";
export const FILE_REQUIRED = "Choose the photo or PDF of the proof.";

export interface AddProofDialogProps {
  open: boolean;
  onClose: () => void;
  draftId: string;
  channel: string | null;
  /** The day the letter went out: a posting receipt, fax report, sent e-mail or cancel page shows it. */
  sentOn?: string | null;
  /** The kind to start with (the next one that fits the channel). */
  suggested: ProofKind;
  /** Change this proof's kind, day or note instead of adding a new one. */
  editing?: ProofEntry | null;
}

/** The day a new proof of `kind` starts with: the sending day for proofs of the sending, else none. */
export function startDay(kind: ProofKind, sentOn: string | null | undefined): string {
  return sentOn && SENDING_DAY_KINDS.includes(kind) ? sentOn : "";
}

/**
 * "Add proof": a photo or PDF of a receipt (kept on this computer, never read by Claude), what it is,
 * the day it shows and a note. A proof of the sending starts with the sending day (so an undated
 * receipt never looks like a later posting). Mistakes are said — and the field focused and marked —
 * when the person adds it; the button never sits disabled without a reason. The note is a few lines
 * (it can be read whole while it is edited), counting down near its limit. In edit mode only the
 * kind, day and note change.
 */
export function AddProofDialog({ open, onClose, draftId, channel, sentOn, suggested, editing }: AddProofDialogProps) {
  const today = useTodayISO();
  // a paired phone sends the proof to the computer: "your computer"
  const phone = usePhoneCompanion();
  const add = useAddProof();
  const update = useUpdateProof();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<ProofKind>(editing?.proof.kind ?? suggested);
  const [onDate, setOnDate] = useState(editing ? (editing.proof.on_date ?? "") : startDay(suggested, sentOn));
  const [dayTouched, setDayTouched] = useState(Boolean(editing));
  const [note, setNote] = useState(editing?.proof.note ?? "");
  const [tried, setTried] = useState(false);
  const ids = useId();
  const fileId = `${ids}-file`;
  const fileHint = `${ids}-file-hint`;
  const fileError = `${ids}-file-error`;
  const dayId = `${ids}-day`;
  const noteId = `${ids}-note`;
  const dateOk = !onDate || (/^\d{4}-\d{2}-\d{2}$/.test(onDate) && onDate <= today);
  const noteOk = note.length <= NOTE_MAX;
  const noteLeft = NOTE_MAX - note.length;
  const fileMissing = !editing && !file;
  const pending = add.isPending || update.isPending;
  const hint = copyFor(PROOF_KIND_COPY, kind).hint;

  const chooseKind = (next: ProofKind) => {
    setKind(next);
    if (!dayTouched && !editing) setOnDate(startDay(next, sentOn));
  };

  const submit = () => {
    if (pending) return;
    setTried(true);
    const firstInvalid = fileMissing ? fileId : !dateOk ? dayId : !noteOk ? noteId : null;
    if (firstInvalid) {
      document.getElementById(firstInvalid)?.focus();
      return;
    }
    if (editing) {
      update.mutate(
        { id: draftId, proofId: editing.proof.id, patch: { kind, on_date: onDate || null, note: note.trim() || null } },
        {
          onSuccess: () => {
            toast.success("Proof updated", { description: copyFor(PROOF_KIND_COPY, kind).label });
            onClose();
          },
        },
      );
      return;
    }
    add.mutate(
      { id: draftId, upload: { file: file!, kind, onDate: onDate || null, note } },
      {
        onSuccess: (overview) => {
          const label = copyFor(PROOF_KIND_COPY, kind).label;
          // a file already in Ordnung is what it is: the server says whether Claude read it
          if (overview.notice) toast({ tone: "info", title: "Proof added", description: `${label} — ${overview.notice}` });
          else toast.success("Proof added", { description: `${label} — kept private, never sent to Claude.` });
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={editing ? "Change this proof" : "Add proof"}
      description={
        editing
          ? "Say what it is and the day it shows. The file stays as it is."
          : "A photo or PDF of the posting receipt, the delivery record, a fax report, the sent e-mail or the cancel button's confirmation."
      }
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={editing ? Save : Plus} loading={pending} onClick={submit}>
            {editing ? "Save" : "Add proof"}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {!editing ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={fileId} className="text-sm font-medium text-ink">
              File
            </label>
            <input
              id={fileId}
              type="file"
              accept={ACCEPT}
              required
              aria-invalid={tried && fileMissing ? true : undefined}
              aria-describedby={tried && fileMissing ? `${fileError} ${fileHint}` : fileHint}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              // missing, the field is marked like any invalid field: a red edge on its button, and a red ring
              // while focused — also when it was focused for the person after a click (no :focus-visible then)
              className="block w-full min-w-0 rounded-lg text-sm text-muted file:mr-3 file:inline-flex file:h-9 file:cursor-pointer file:rounded-lg file:border file:border-line-strong/80 file:bg-surface file:px-3.5 file:text-sm file:font-medium file:text-ink hover:file:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-invalid:file:border-danger aria-invalid:focus:outline-2 aria-invalid:focus:outline-offset-2 aria-invalid:focus:outline-danger"
            />
            {tried && fileMissing ? (
              <p id={fileError} className="text-sm font-medium leading-5 text-danger-ink">
                {FILE_REQUIRED}
              </p>
            ) : null}
            <p id={fileHint} className="flex items-start gap-1.5 text-sm leading-5 text-muted">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>Kept on {theComputer(phone)} with the letter, and never sent to Claude.</span>
            </p>
          </div>
        ) : null}

        <Field label="What is it?" hint={hint}>
          <Select value={kind} onChange={(e) => chooseKind(e.target.value as ProofKind)}>
            {proofKindsFor(channel).map((k) => (
              <option key={k} value={k}>
                {copyFor(PROOF_KIND_COPY, k).label}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          id={dayId}
          label={PROOF_DAY_LABEL[kind]}
          optional
          hint={dateOk ? "The day the proof shows. Without a day it is listed apart, never on the day you added it." : undefined}
          error={dateOk ? undefined : "Choose a day up to today."}
        >
          <Input
            type="date"
            value={onDate}
            max={today}
            onChange={(e) => {
              setDayTouched(true);
              setOnDate(e.target.value);
            }}
            className="w-48 max-w-full"
          />
        </Field>

        <Field
          id={noteId}
          label="Note"
          optional
          hint={noteLeft <= NOTE_COUNT_FROM ? `${noteLeft} ${noteLeft === 1 ? "character" : "characters"} left` : undefined}
          error={noteOk ? undefined : `Keep it under ${NOTE_MAX} characters — ${-noteLeft} too many.`}
        >
          {/* grows with the note (up to about eight lines, then it scrolls), so it is read whole while edited */}
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={NOTE_MAX + 20} placeholder="e.g. Post office on Hauptstraße, 14:32" className="min-h-16 max-h-48 [field-sizing:content]" />
        </Field>
      </form>
    </Dialog>
  );
}
