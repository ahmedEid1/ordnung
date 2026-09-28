import type { ReactNode, RefObject } from "react";
import { Download, Trash2 } from "lucide-react";
import { api } from "@/api/endpoints";
import type { Document, ProofKind } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { PROOF_KIND_COPY, copyFor } from "@/lib/copy";

export interface RemoveProofDialogProps {
  open: boolean;
  onClose: () => void;
  /** The proof's kind: the title names it ("Remove the posting receipt (Einlieferungsbeleg)?"). */
  kind: ProofKind | null;
  /** Its file (`null`: a proof without one). */
  document: Document | null;
  /** Removing is under way: the button spins. */
  pending: boolean;
  onRemove: () => void;
  /** Where focus goes when the dialog closes without removing (the control that opened it may be gone). */
  returnFocus?: RefObject<HTMLElement | null>;
}

const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

/** What removing a proof does to its file, naming it: deleted for good, or (a letter it was linked to) kept. */
export function removalWords(document: Document | null): ReactNode {
  if (!document) return "Its entry is removed from this letter.";
  // a file name is one long word: it wraps anywhere rather than widen the dialog
  return (
    <span className="[overflow-wrap:anywhere]">
      {document.source === "proof" ? `“${document.filename}” is deleted from Ordnung for good — this can't be undone.` : `“${document.filename}” stays in Ordnung; only its link to this letter goes.`}
    </span>
  );
}

/**
 * "Remove the posting receipt?" — the one confirmation for removing a proof, on the letter's proof card
 * and on the proof's own page alike: it names the proof and its file, says the file is deleted for good
 * (docs/decisions/0014) and offers to download it first, as a photographed receipt may be the only copy.
 */
export function RemoveProofDialog({ open, onClose, kind, document, pending, onRemove, returnFocus }: RemoveProofDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      returnFocus={returnFocus}
      size="sm"
      title={kind ? `Remove the ${lowerFirst(copyFor(PROOF_KIND_COPY, kind).label)}?` : "Remove this proof?"}
      description={open ? removalWords(document) : undefined}
      footer={
        <>
          <Button onClick={onClose}>Keep it</Button>
          <Button variant="danger" icon={Trash2} loading={pending} onClick={onRemove}>
            Remove
          </Button>
        </>
      }
    >
      {document && document.source === "proof" ? (
        <p className="text-[13.5px] leading-5 text-ink/85">
          If it's your only copy,{" "}
          <a href={api.fileUrl(document.id)} download={document.filename} className="inline-flex min-h-6 items-center gap-1 font-medium text-accent underline underline-offset-2">
            <Download className="size-3.5" aria-hidden />
            download it first
          </a>
          .
        </p>
      ) : null}
    </Dialog>
  );
}
