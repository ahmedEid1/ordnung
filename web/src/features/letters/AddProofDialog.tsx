import { useId, useState } from "react";
import { Lock, Plus, Save } from "lucide-react";
import type { ProofEntry, ProofKind } from "@/api/types";
import { useAddProof, useUpdateProof } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { PROOF_KIND_COPY, copyFor } from "@/lib/copy";
import { useTodayISO } from "@/lib/today";
import { PROOF_DAY_LABEL, proofKindsFor } from "./proof";

const NOTE_MAX = 500;
/** What the file picker offers (the server checks every file like any upload). */
const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,.eml,message/rfc822,text/plain";

export interface AddProofDialogProps {
  open: boolean;
  onClose: () => void;
  draftId: string;
  channel: string | null;
  /** The kind to start with (the next one that fits the channel). */
  suggested: ProofKind;
  /** Change this proof's kind, day or note instead of adding a new one. */
  editing?: ProofEntry | null;
}

/**
 * "Add proof": a photo or PDF of a receipt (kept on this computer, never read by AI), what it is,
 * the day it shows and a note. In edit mode only the kind, day and note change.
 */
export function AddProofDialog({ open, onClose, draftId, channel, suggested, editing }: AddProofDialogProps) {
  const today = useTodayISO();
  const add = useAddProof();
  const update = useUpdateProof();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<ProofKind>(editing?.proof.kind ?? suggested);
  const [onDate, setOnDate] = useState(editing?.proof.on_date ?? "");
  const [note, setNote] = useState(editing?.proof.note ?? "");
  const fileHint = useId();
  const dateOk = !onDate || (/^\d{4}-\d{2}-\d{2}$/.test(onDate) && onDate <= today);
  const ready = (editing || file) && dateOk && note.length <= NOTE_MAX;
  const pending = add.isPending || update.isPending;

  const submit = () => {
    if (!ready || pending) return;
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
        onSuccess: () => {
          toast.success("Proof added", { description: `${copyFor(PROOF_KIND_COPY, kind).label} — kept private, never sent to AI.` });
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
          <Button variant="primary" icon={editing ? Save : Plus} disabled={!ready} loading={pending} onClick={submit}>
            {editing ? "Save" : "Add proof"}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {!editing ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${fileHint}-file`} className="text-sm font-medium text-ink">
              File
            </label>
            <input
              id={`${fileHint}-file`}
              type="file"
              accept={ACCEPT}
              aria-describedby={fileHint}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full min-w-0 text-sm text-muted file:mr-3 file:inline-flex file:h-9 file:cursor-pointer file:rounded-lg file:border file:border-line-strong/80 file:bg-surface file:px-3.5 file:text-sm file:font-medium file:text-ink hover:file:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
            <p id={fileHint} className="flex items-start gap-1.5 text-sm leading-5 text-muted">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>Kept on this computer with the letter, and never sent to AI.</span>
            </p>
          </div>
        ) : null}

        <Field label="What is it?">
          <Select value={kind} onChange={(e) => setKind(e.target.value as ProofKind)}>
            {proofKindsFor(channel).map((k) => (
              <option key={k} value={k}>
                {copyFor(PROOF_KIND_COPY, k).label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label={PROOF_DAY_LABEL[kind]} optional hint={dateOk ? "The day the proof shows — it goes into the timeline." : undefined} error={dateOk ? undefined : "Choose a day up to today."}>
          <Input type="date" value={onDate} max={today} onChange={(e) => setOnDate(e.target.value)} className="w-48 max-w-full" />
        </Field>

        <Field label="Note" optional error={note.length > NOTE_MAX ? `Keep it under ${NOTE_MAX} characters.` : undefined}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={NOTE_MAX + 20} placeholder="e.g. Post office on Hauptstraße, 14:32" />
        </Field>
      </form>
    </Dialog>
  );
}
