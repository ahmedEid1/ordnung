/**
 * "What kind of letter is this?" — the person can correct the kind Ordnung filed a letter under. The
 * kind decides which deadlines the law adds (a court order's two weeks, a dismissal's three weeks)
 * and which "get advice" card shows, so a letter Ordnung missed or misread can be put right; the
 * server recomputes its dates at once and keeps the choice when the letter is read again.
 */
import { useState } from "react";
import { Pencil } from "lucide-react";
import type { Document, DocumentKind } from "@/api/types";
import { DOCUMENT_KINDS, HIGH_STAKES_KINDS } from "@/api/types";
import { useUpdateDocument } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { Field, Select } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";
import { toast } from "@/components/ui/Toast";
import { DOCUMENT_KIND_COPY, documentKindLabel } from "@/lib/copy";

const HIGH_STAKES = new Set<string>(HIGH_STAKES_KINDS);
/** Everyday kinds by name ("Other letter" last). */
const EVERYDAY = DOCUMENT_KINDS.filter((k) => !HIGH_STAKES.has(k) && k !== "other")
  .slice()
  .sort((a, b) => documentKindLabel(a).localeCompare(documentKindLabel(b)));

function KindForm({ doc, close }: { doc: Pick<Document, "id" | "kind">; close: () => void }) {
  const update = useUpdateDocument();
  const [kind, setKind] = useState<DocumentKind>(doc.kind ?? "other");
  const hint = DOCUMENT_KIND_COPY[kind]?.hint;
  const save = () => {
    if (kind === doc.kind) return close();
    update.mutate(
      { id: doc.id, patch: { kind } },
      {
        onSuccess: () => {
          toast.success(`Filed as “${documentKindLabel(kind)}”`, { description: "Its dates and to-dos were worked out again." });
          close();
        },
      },
    );
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
      className="space-y-3"
    >
      <div>
        <h2 className="text-[15px] font-semibold text-ink">What kind of letter is this?</h2>
        <p className="mt-1 text-[13px] leading-5 text-muted">
          The kind decides which deadlines the law adds and which advice you see. Change it if Ordnung got it wrong.
        </p>
      </div>
      <Field label="Kind of letter" hint={hint}>
        <Select value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
          <optgroup label="Letters with deadlines set by law">
            {HIGH_STAKES_KINDS.map((k) => (
              <option key={k} value={k}>
                {documentKindLabel(k)}
              </option>
            ))}
          </optgroup>
          <optgroup label="Other letters">
            {[...EVERYDAY, "other" as const].map((k) => (
              <option key={k} value={k}>
                {documentKindLabel(k)}
              </option>
            ))}
          </optgroup>
        </Select>
      </Field>
      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" onClick={close}>
          Cancel
        </Button>
        <Button size="sm" type="submit" variant="primary" loading={update.isPending}>
          Save
        </Button>
      </div>
    </form>
  );
}

/** A small "Change" button next to the letter's kind, opening the kind form. */
export function KindPicker({ doc }: { doc: Pick<Document, "id" | "kind"> }) {
  return (
    <Popover label="What kind of letter is this?" placement="bottom-start" className="w-[22rem] p-4" content={(close) => <KindForm doc={doc} close={close} />}>
      <Button size="sm" variant="ghost" icon={Pencil} aria-label="Change what kind of letter this is" className="h-7 px-2 text-[12.5px]">
        Change
      </Button>
    </Popover>
  );
}
