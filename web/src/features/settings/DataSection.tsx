import { Fragment, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Check, Copy, Download, FolderOpen, RotateCcw, Trash2 } from "lucide-react";
import { api } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { useDeleteEverything } from "@/api/hooks";
import type { Health } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { isStaticDemo } from "@/mocks/mode";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { DEMO_CMD } from "@/features/onboarding/options";
import { useClipboard } from "@/features/today/clipboard";
import { useTodayISO } from "@/lib/today";
import { exportFileName } from "./logic";
import { SectionHeading, SettingsCard } from "./SettingsCard";

async function buildExport() {
  const [profile, settings, documents, items, contracts, parties, drafts, suggestions] = await Promise.all([
    api.profile(),
    api.settings(),
    api.documents(), // no limit: every letter (the API caps an explicit limit at 1000)
    api.items({ include_undated: true }), // no limit: every to-do (explicit limits stop at 5000)
    api.contracts(),
    api.parties(),
    api.drafts(),
    api.suggestions(),
  ]);
  return { exported_at: new Date().toISOString(), app: "Ordnung", profile, settings, documents, items, contracts, parties, drafts, ideas: suggestions };
}

/** A folder path with a line-break opportunity (`<wbr>`) after each "/" or "\", so it wraps between names. */
export function BreakablePath({ path }: { path: string }) {
  const parts = path.split(/(?<=[/\\])/);
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 ? <wbr /> : null}
        </Fragment>
      ))}
    </>
  );
}

/** The word to type in the "Delete everything" dialog. */
const DELETE_WORD = "DELETE";

/** "Delete everything": a typed confirmation, then the API wipes the data folder and the app starts over. */
function DeleteEverythingDialog({ open, onClose, onExport, exporting }: { open: boolean; onClose: () => void; onExport: () => void; exporting: boolean }) {
  const navigate = useNavigate();
  const remove = useDeleteEverything();
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // the word in any case: "delete" typed on a keyboard means the same (the API gets "DELETE")
  const confirmed = typed.trim().toUpperCase() === DELETE_WORD;

  const close = () => {
    if (remove.isPending) return;
    setTyped("");
    remove.reset();
    onClose();
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!confirmed || remove.isPending) return;
    remove.mutate(undefined, {
      onSuccess: (result) => {
        setTyped("");
        onClose();
        const kept = result?.kept ?? [];
        toast.success("Everything was deleted", {
          description: kept.length
            ? `Ordnung started over. It left ${kept.length === 1 ? "one file" : `${kept.length} files`} it didn't create: ${kept.join(", ")}.`
            : "Ordnung started over with an empty folder.",
          duration: 8000,
        });
        navigate("/welcome", { replace: true });
      },
    });
  };

  const error = remove.error ? (remove.error instanceof ApiError ? remove.error.message : "Couldn't delete your data. Nothing was changed.") : null;

  return (
    <Dialog
      open={open}
      onClose={close}
      size="md"
      title="Delete everything?"
      description="Every letter and its original file, all dates, contracts, drafts, chats and your settings are deleted from this computer — and every file in Ordnung's own inbox folder, even ones it couldn't add. A watched folder of your own is left as it is. This can't be undone."
      initialFocus={inputRef}
      dismissible={!remove.isPending}
      footer={
        <>
          <Button onClick={close} disabled={remove.isPending}>
            Keep my data
          </Button>
          <Button variant="danger" icon={Trash2} onClick={() => submit()} disabled={!confirmed} loading={remove.isPending}>
            Delete everything
          </Button>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <p className="text-[13.5px] leading-relaxed text-ink/85">
          Want to keep a copy?{" "}
          <Button variant="link" size="sm" onClick={onExport} loading={exporting} className="align-baseline">
            Download your records first
          </Button>
          .
        </p>
        <Field
          label={
            <>
              Type <span className="font-mono font-semibold tracking-wide text-danger-ink">{DELETE_WORD}</span> to confirm
            </>
          }
          error={error ?? undefined}
        >
          <Input
            ref={inputRef}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder={DELETE_WORD}
            className="font-mono tracking-wide"
          />
        </Field>
      </form>
    </Dialog>
  );
}

/** "Data": where everything lives, a copy of your records, and how to delete everything. */
export function DataSection({ health }: { health: Health }) {
  const today = useTodayISO();
  const { copy, copied } = useClipboard();
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const staticDemo = isStaticDemo();

  const exportJson = async () => {
    setBusy(true);
    try {
      const data = await buildExport();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = exportFileName(today);
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Your records are downloading", { description: "Letters, dates, contracts, people and your drafts as one JSON file." });
    } catch (err) {
      toast.error("Couldn't create the export", { description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="set-data">
      <SectionHeading id="set-data" title="Data" description="Everything Ordnung knows is in one folder on this computer. You can copy it, back it up or delete it." />
      <div className="space-y-5">
        <SettingsCard title="Where your data lives" id="set-data-where" description="The database, your original files and page images.">
          <div className="flex items-start gap-2 rounded-xl border border-line bg-surface-2/50 py-1.5 pl-3 pr-1.5">
            <FolderOpen className="mt-2 size-4 shrink-0 text-muted" aria-hidden />
            {/* the whole path, wrapping after a "/" (inside a name only when one is longer than the line) */}
            <code className="min-w-0 flex-1 py-1.5 font-mono text-[13px] leading-5 text-ink wrap-anywhere">
              <BreakablePath path={health.data_dir} />
            </code>
            <Button size="sm" variant="ghost" icon={copied === health.data_dir ? Check : Copy} onClick={() => void copy(health.data_dir)}>
              {copied === health.data_dir ? "Copied" : "Copy"} <span className="sr-only">the folder path</span>
            </Button>
          </div>
          <p className="mt-3 text-sm leading-5 text-muted">To back up, copy this folder while Ordnung isn't running — for example to an external drive.</p>
        </SettingsCard>

        <SettingsCard
          title="Download a copy of your records"
          id="set-data-export"
          description="Letters (details, not the files), to-dos & dates, contracts, people & organisations, your drafts and Ideas — as a JSON file you can open anywhere."
          footer={
            <Button icon={Download} onClick={() => void exportJson()} loading={busy}>
              Download JSON
            </Button>
          }
        >
          <p className="text-sm leading-5 text-muted">Your original PDFs and photos stay in the folder above.</p>
        </SettingsCard>

        {staticDemo || health.demo ? (
          // nothing of the visitor's to delete: a calm way to start over, not a danger zone
          <SettingsCard
            title="Start over"
            id="set-data-reset"
            description={
              staticDemo
                ? "This online demo keeps nothing you do in it. Reload the page to start over with Sam's letters."
                : "This is the demo, so there is nothing of yours to delete. To start over with Sam's original letters, run this in a terminal:"
            }
            footer={
              staticDemo ? (
                <Button icon={RotateCcw} onClick={() => window.location.reload()}>
                  Start over
                </Button>
              ) : undefined
            }
          >
            {staticDemo ? null : <CopyCommand command={`${DEMO_CMD} --reset`} label="reset the demo" />}
          </SettingsCard>
        ) : (
          <section aria-labelledby="set-data-delete" className="overflow-hidden rounded-[var(--radius-card)] border border-danger/25 bg-danger-soft/30">
            <div className="p-5 sm:p-6">
              <h3 id="set-data-delete" className="flex items-center gap-2 text-[15px] font-semibold text-danger-ink">
                <Trash2 className="size-4 shrink-0" aria-hidden /> Delete everything
              </h3>
              <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink/85">
                Deletes every letter and its original file, all dates, contracts, drafts and chats, and your settings — Ordnung starts over empty. Files in
                Ordnung's own inbox folder go too, even ones it couldn't add; a watched folder of your own is never touched. There is no account and no
                copy anywhere else. Letters Claude already read were processed through your Claude account under Anthropic's terms.
              </p>
            </div>
            {/* the action where the other cards on this page have theirs: in the footer, on the right */}
            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-danger/20 bg-danger-soft/40 px-5 py-3 sm:px-6">
              <Button variant="danger" icon={Trash2} onClick={() => setDeleteOpen(true)}>
                Delete everything…
              </Button>
            </div>
          </section>
        )}
        <DeleteEverythingDialog open={deleteOpen} onClose={() => setDeleteOpen(false)} onExport={() => void exportJson()} exporting={busy} />
      </div>
    </section>
  );
}
