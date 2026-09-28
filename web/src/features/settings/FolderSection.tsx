/**
 * "Watched folder" (SPEC § 8.1): the folder a scanner or a phone app saves into. New PDFs, photos and
 * e-mails there are added like letters dropped into the app — and wait in the Inbox for "Read these"
 * unless Claude may read new files at once (docs/privacy.md, "The watched folder").
 *
 * - The path is checked by the server; its reason ("… can't be your whole home folder") shows under
 *   the field, never only in a toast. An empty field stops watching.
 * - "Use Ordnung's own inbox folder" fills in the folder inside Ordnung's data folder (created on
 *   save) and focus goes to the field; its path can be copied (file pickers often hide that folder).
 * - The auto-read switch says honestly what it does: only files that arrive later are read at once,
 *   the ones already in the folder wait; a cloud-synced folder is already shared. Where nothing can be
 *   read (the demo), it says files always wait.
 * - The save note says what changed. The status card: watching (and whether new files wait or are
 *   read), a problem (missing, not readable, too many files), or off; the letters waiting; the last
 *   files the folder brought in and what became of each. "Stop watching" leaves focus on the field.
 */
import { useId, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CircleX, CloudAlert, Copy, FileCheck, Files, FolderOpen, Hourglass, type LucideIcon } from "lucide-react";
import { api } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { qk, useFolder } from "@/api/hooks";
import type { AppSettings, FolderPickup, FolderStatus, SettingsPatch } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { cn, plural } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Field, Input, Switch } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, SkeletonText } from "@/components/ui/Skeleton";
import { StatusPill } from "@/components/ui/StatusPill";
import { toast } from "@/components/ui/Toast";
import { copyText } from "@/features/document/actions";
import { reasonClause } from "@/features/document/EmailParts";
import { SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type FolderForm = { folder: string; autoRead: boolean };
const pick = (s: AppSettings): FolderForm => ({ folder: s.inbox_dir ?? "", autoRead: s.inbox_auto_read });

const focusFolderField = () => requestAnimationFrame(() => document.getElementById("folder-path")?.focus());

/** The note after saving: what changed (the folder, or only whether new files wait or are read). */
export function savedNote(before: FolderForm, after: FolderForm): string {
  if (!after.folder) return "Ordnung doesn't watch a folder any more.";
  if (after.folder !== before.folder)
    return after.autoRead
      ? "Ordnung watches this folder now. Files already in it wait for you; new ones are read with Claude."
      : "Ordnung watches this folder now. Its files wait for you in the Inbox.";
  return after.autoRead ? "New files from the folder are read with Claude from now on." : "New files from the folder wait for you from now on.";
}

/**
 * Saves the folder settings. A path the server refuses (422) is the form's mistake, shown under the
 * field; anything else is a failed save, which the toast explains.
 */
function useSaveFolder(onRefused: (reason: string) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SettingsPatch) => api.updateSettings(patch),
    meta: { silent: true },
    onSuccess: (settings) => {
      qc.setQueryData(qk.settings, settings);
      void qc.invalidateQueries({ queryKey: qk.folder });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 422) onRefused(err.message);
      else toast.error("Couldn't save your settings", { description: err instanceof Error ? err.message : undefined });
    },
  });
}

export function FolderSection({ settings }: { settings: AppSettings }) {
  const status = useFolder();
  const saved = pick(settings);
  const [form, setForm] = useState<FolderForm>(saved);
  // the settings changed elsewhere ("Stop watching" below): fields not being edited follow them
  const [base, setBase] = useState<FolderForm>(saved);
  if (base.folder !== saved.folder || base.autoRead !== saved.autoRead) {
    setBase(saved);
    setForm((f) => ({
      folder: f.folder.trim() === base.folder ? saved.folder : f.folder,
      autoRead: f.autoRead === base.autoRead ? saved.autoRead : f.autoRead,
    }));
  }
  const [refused, setRefused] = useState<string | null>(null);
  // the server's reason goes under the field, and focus with it (like any other mistake in Settings)
  const save = useSaveFolder((reason) => {
    setRefused(reason);
    focusFolderField();
  });
  const dirty = form.folder.trim() !== saved.folder || form.autoRead !== saved.autoRead;
  const suggested = status.data?.suggested ?? "";
  const canRead = status.data?.can_read ?? true;

  const onSave = () =>
    save.mutateAsync({ inbox_dir: form.folder.trim() || null, inbox_auto_read: form.autoRead }).then((s) => {
      setForm(pick(s));
      setRefused(null);
      return savedNote(saved, pick(s));
    });

  return (
    <section aria-labelledby="set-folder">
      <SectionHeading
        id="set-folder"
        title="Watched folder"
        description="Point Ordnung at the folder your scanner or phone app saves into — a folder just for letters. New PDFs, photos and e-mails there are added like letters you drop in. Ordnung only reads the folder — it never changes, moves or deletes your files."
      />
      <div className="space-y-5">
        <SettingsCard
          footer={
            <SaveBar
              dirty={dirty}
              saving={save.isPending}
              onSave={onSave}
              invalid={Boolean(refused) && dirty}
              onInvalid={() => document.getElementById("folder-path")?.focus()}
              onDiscard={() => {
                setForm(saved);
                setRefused(null);
              }}
            />
          }
        >
          <div className="grid gap-5">
            <div>
              <Field label="Folder" hint="A full path, like /home/you/Scans. Leave it empty to stop watching." error={refused ?? undefined} id="folder-path">
                <Input
                  value={form.folder}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, folder: e.target.value }));
                    setRefused(null);
                  }}
                  placeholder="/home/you/Scans"
                  spellCheck={false}
                  autoCapitalize="off"
                  autoCorrect="off"
                  className="w-full"
                />
              </Field>
              {suggested && form.folder.trim() !== suggested ? (
                <div className="mt-2 flex max-w-full items-start gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setForm((f) => ({ ...f, folder: suggested }));
                      setRefused(null);
                      focusFolderField(); // the button goes once the field holds its folder
                    }}
                    className="inline-flex min-h-7 min-w-0 items-start gap-1.5 rounded-md text-left text-sm text-accent hover:underline"
                  >
                    <FolderOpen className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span className="min-w-0">
                      <span className="font-medium">Use Ordnung's own inbox folder</span>
                      <span className="block break-all font-mono text-[12.5px] text-muted">{suggested}</span>
                    </span>
                  </button>
                  <IconButton icon={Copy} label="Copy the inbox folder's path" size="sm" variant="ghost" className="shrink-0 text-muted" onClick={() => void copyText(suggested, "The folder's path")} />
                </div>
              ) : null}
              {suggested && form.folder.trim() === suggested ? (
                <p className="mt-2 text-[13px] leading-5 text-muted">File pickers often hide this folder: copy its path and paste it into your scanner app.</p>
              ) : null}
            </div>
            <Switch
              checked={form.autoRead}
              onCheckedChange={(v) => setForm((f) => ({ ...f, autoRead: v }))}
              label="Read new files with Claude straight away"
              description={
                canRead
                  ? "Off: files wait in your Inbox until you choose “Read these” — nothing is sent to Claude before that. On: files that arrive in the folder from now on are sent to Claude as soon as they appear. The files already in the folder when you choose it, and the ones already waiting, still wait for you."
                  : "This demo reads no new letters with Claude: files from the folder always wait in your Inbox, whatever this switch says. In the installed app, files that arrive later are sent to Claude as soon as they appear; the ones already in the folder still wait."
              }
            />
            <Callout icon={CloudAlert} title="A cloud-synced folder is already shared">
              If this folder is inside Dropbox, iCloud Drive, OneDrive or Google Drive, that provider has copies of every file in it — whatever Ordnung does. Choose a
              folder on this computer only if that matters to you.
            </Callout>
          </div>
        </SettingsCard>

        <SettingsCard title="Status" id="folder-status" description="Whether Ordnung is watching, and the last files the folder brought in.">
          {status.isPending ? (
            <div aria-busy="true">
              <LoadingLabel>Loading the folder's status…</LoadingLabel>
              <SkeletonText lines={4} />
            </div>
          ) : status.isError || !status.data ? (
            <LoadError
              what="the folder's status"
              error={status.error}
              onRetry={() => void status.refetch()}
              retrying={status.isFetching}
              headingLevel={3}
              variant="plain"
              size="sm"
            />
          ) : (
            <FolderState status={status.data} />
          )}
        </SettingsCard>
      </div>
    </section>
  );
}

/** What happens to a new file, in words (the privacy-relevant fact the Status card shows). */
export function newFilesLine(status: Pick<FolderStatus, "auto_read" | "can_read">): string {
  if (!status.can_read) return "New files wait for you — this demo reads nothing with Claude.";
  return status.auto_read ? "New files are read with Claude as soon as they arrive." : "New files wait for you before anything is sent to Claude.";
}

function FolderState({ status }: { status: FolderStatus }) {
  const stop = useSaveFolder((reason) => toast.error("Couldn't stop watching", { description: reason }));
  const listId = useId();
  return (
    <div className="space-y-5">
      {status.folder ? (
        <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
          <div className="min-w-0 flex-1 basis-60">
            {status.state === "watching" ? (
              <Badge tone="ok" dot>
                Watching
              </Badge>
            ) : status.state === "problem" ? (
              <Badge tone="warn" dot>
                Not watching right now
              </Badge>
            ) : (
              <Badge tone="neutral" dot>
                Not watching
              </Badge>
            )}
            <div className="mt-2 flex items-start gap-1">
              <p className="min-w-0 flex-1 break-all font-mono text-[13px] leading-5 text-ink/85">{status.folder}</p>
              <IconButton icon={Copy} label="Copy the folder's path" size="sm" variant="ghost" className="-my-1 shrink-0 text-muted" onClick={() => void copyText(status.folder!, "The folder's path")} />
            </div>
            <p className="mt-1 text-[13.5px] leading-5 text-muted">{newFilesLine(status)}</p>
          </div>
          <Button
            size="sm"
            loading={stop.isPending}
            onClick={() =>
              stop
                .mutateAsync({ inbox_dir: null })
                .then(() => {
                  toast.success("Stopped watching the folder", { description: "Files already added stay in Ordnung; the folder is left as it is." });
                  focusFolderField(); // this button goes: focus stays in the section, on the (now empty) folder field
                })
                .catch(() => undefined)
            }
          >
            Stop watching
          </Button>
        </div>
      ) : (
        <p className="text-base text-muted">No folder is watched. Choose one above — the files already in it are added once and wait for you, then every new one.</p>
      )}

      {status.problem ? <Callout tone="warn">{status.problem}</Callout> : null}

      {status.waiting ? (
        <Link to="/inbox" className="flex items-center gap-3 rounded-xl border border-accent/25 bg-accent-soft/60 px-4 py-3 transition-colors hover:bg-accent-soft">
          <Hourglass className="size-4 shrink-0 text-accent" aria-hidden />
          <span className="min-w-0 flex-1 text-[14px] font-medium text-ink">{plural(status.waiting, "letter")} waiting for you in the Inbox</span>
          <ArrowRight className="size-4 shrink-0 text-accent" aria-hidden />
        </Link>
      ) : null}

      <div>
        <h4 id={listId} className="eyebrow mb-2">
          Last files from the folder
        </h4>
        {status.recent.length ? (
          <ul aria-labelledby={listId} className="divide-y divide-line rounded-xl border border-line">
            {status.recent.map((p, i) => (
              <PickupRow key={`${p.at}-${i}`} pickup={p} />
            ))}
          </ul>
        ) : (
          <p className="rounded-xl border border-dashed border-line-strong px-4 py-3 text-sm leading-5 text-muted">
            {status.folder
              ? "Nothing picked up yet. Save a PDF or a phone photo into the folder — it shows up in your Inbox within a few seconds."
              : "Nothing picked up yet. Once a folder is watched, the files it brings in are listed here."}
          </p>
        )}
      </div>
    </div>
  );
}

const PICKUP_ICON: Record<FolderPickup["outcome"], { icon: LucideIcon; cls: string }> = {
  added: { icon: FileCheck, cls: "bg-accent-soft text-accent" },
  known: { icon: Files, cls: "bg-surface-2 text-muted" },
  refused: { icon: CircleX, cls: "bg-danger-soft text-danger" },
};

function PickupRow({ pickup: p }: { pickup: FolderPickup }) {
  const today = useTodayISO();
  const { icon: Icon, cls } = PICKUP_ICON[p.outcome];
  const when = formatDateTime(p.at, { today });
  return (
    <li className="relative flex items-start gap-3 px-3.5 py-3 sm:px-4">
      <span className={cn("mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg", cls)}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        {p.doc_id ? (
          <Link
            to={`/documents/${p.doc_id}`}
            title={p.filename}
            className="line-clamp-2 break-words text-[14px] font-medium leading-snug text-ink outline-none [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] hover:text-accent focus-visible:after:rounded-[inherit] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
          >
            {p.filename}
          </Link>
        ) : (
          <p title={p.filename} className="line-clamp-2 break-words text-[14px] font-medium leading-snug text-ink [overflow-wrap:anywhere]">
            {p.filename}
          </p>
        )}
        {/* one run of text: the "·" stays at the end of a line when the date wraps, never at the start of one */}
        <p className="mt-1 text-[12.5px] leading-6 text-muted">
          {p.outcome === "added" && p.status ? (
            <StatusPill of="document" status={p.status} className="align-middle" />
          ) : p.outcome === "added" ? (
            <span>Added — the letter is in the trash</span>
          ) : p.outcome === "known" ? (
            <span>Already in Ordnung</span>
          ) : (
            <span className="text-danger-ink">{p.detail ? `Not added — ${reasonClause(p.detail)}` : "Not added"}</span>
          )}
          {"\u00a0· "}
          <span className="whitespace-nowrap">{when}</span>
        </p>
      </div>
    </li>
  );
}
