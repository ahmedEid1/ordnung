/**
 * Settings → Your computers → Kept copies (design §12.4, §19.1 card 4; shown only when there are some): this
 * computer's data as it was before it was replaced — after a choice, a take-over that would have lost a change of
 * yours, or a repair. Each is an ordinary encrypted backup that `ordnung restore` opens with the sync passphrase.
 * They are never synced and never deleted by themselves; they live in this computer's data folder, so they go with
 * its disk and with Delete everything (finding 35).
 */
import { useRef, useState } from "react";
import { Download, FileArchive, Trash2 } from "lucide-react";
import { useDeleteKept, useDownloadKept } from "@/api/hooks";
import type { SyncKept, SyncStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { saveBlob } from "./backup";
import { SettingsCard } from "./SettingsCard";
import { keptLine, keptRestoreCommand } from "./sync";

/** "Delete this kept copy?" — for good. */
function DeleteKeptDialog({ kept, onClose }: { kept: SyncKept | null; onClose: () => void }) {
  const remove = useDeleteKept();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirm = () => {
    if (!kept) return;
    remove.mutate(kept.name, {
      onSuccess: () => {
        onClose();
        toast.success("The kept copy was deleted");
      },
    });
  };
  return (
    <Dialog
      open={kept !== null}
      onClose={() => (remove.isPending ? undefined : onClose())}
      size="sm"
      title="Delete this kept copy?"
      description={kept ? `${kept.name} is deleted from this computer for good. ${kept.why ? `It was kept ${kept.why}.` : ""}` : undefined}
      initialFocus={cancelRef}
      dismissible={!remove.isPending}
      footer={
        <>
          <Button ref={cancelRef} onClick={onClose} disabled={remove.isPending}>
            Keep it
          </Button>
          <Button variant="danger" icon={Trash2} loading={remove.isPending} onClick={confirm}>
            Delete
          </Button>
        </>
      }
    />
  );
}

export function KeptCopiesCard({ status }: { status: SyncStatus }) {
  const download = useDownloadKept();
  const [deleting, setDeleting] = useState<SyncKept | null>(null);
  const first = status.kept[0];
  if (!first) return null;
  return (
    <SettingsCard
      title="Kept copies"
      id="sync-kept"
      description="This computer's data as it was before it was replaced, each an encrypted backup locked with the sync passphrase. They stay on this computer only — never synced, never deleted by themselves — so they go with its disk, and with Delete everything."
    >
      <div className="space-y-4">
        {status.kept_warning ? (
          <Callout tone="warn" title="Kept copies take more than 2 GB">
            Ordnung never deletes them by itself. Download the ones you want to keep somewhere else, and delete the rest.
          </Callout>
        ) : null}
        <ul className="divide-y divide-line rounded-2xl border border-line">
          {status.kept.map((k) => (
            <li key={k.name} className="flex flex-col gap-2 px-3.5 py-3 sm:flex-row sm:items-center">
              <FileArchive className="hidden size-4 shrink-0 text-muted sm:block" aria-hidden />
              <div className="min-w-0 flex-1 text-[13px] leading-5">
                <p className="font-mono text-[12.5px] text-ink [overflow-wrap:anywhere]">{k.name}</p>
                <p className="text-muted">{keptLine(k)}</p>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button
                  size="sm"
                  icon={Download}
                  loading={download.isPending && download.variables === k.name}
                  onClick={() => download.mutate(k.name, { onSuccess: (blob) => saveBlob(blob, k.name) })}
                >
                  Download <span className="sr-only">{k.name}</span>
                </Button>
                <Button size="sm" variant="ghost" icon={Trash2} onClick={() => setDeleting(k)}>
                  Delete… <span className="sr-only">{k.name}</span>
                </Button>
              </div>
            </li>
          ))}
        </ul>
        <div>
          <p className="text-sm leading-5 text-ink/85">To look inside one, restore it into a folder of its own — it asks for the sync passphrase:</p>
          <CopyCommand command={keptRestoreCommand(first)} label="restore the kept copy" className="mt-2" />
        </div>
      </div>
      <DeleteKeptDialog kept={deleting} onClose={() => setDeleting(null)} />
    </SettingsCard>
  );
}
