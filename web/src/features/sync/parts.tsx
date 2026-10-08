/**
 * Pieces of hand-off sync that Settings → Your computers and the standing-by screen share: a problem with what can
 * be done about it, the passphrase typed again, the folder chosen again, what is arriving, and the notices.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { Download, FolderSearch, KeyRound, X } from "lucide-react";
import { ApiError } from "@/api/client";
import { useConnectSync, useDownloadKept, useRefillSync, useSyncPassphrase, useUpdateSync } from "@/api/hooks";
import type { SyncArriving, SyncNotice, SyncProblem, SyncProblemAction, SyncProgress, SyncStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Field, Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { saveBlob } from "@/features/settings/backup";
import { ACTION_LABELS, arrivalAdvice, arrivingLine, problemTitle } from "@/features/settings/sync";
import { formatFileSize } from "@/lib/format";
import { cn } from "@/lib/utils";

const failed = (err: unknown) => (err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?");

/** The passphrase typed again (the password store lost it): checked against the folder, then kept there. */
export function PassphraseAgain({ id = "sync-passphrase-again" }: { id?: string }) {
  const again = useSyncPassphrase();
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!passphrase) {
      setError("Type the sync passphrase.");
      document.getElementById(id)?.focus();
      return;
    }
    again.mutate(passphrase, {
      onSuccess: () => {
        setPassphrase("");
        setError(null);
        toast.success("Saved in this computer's password store", { description: "Sync goes on." });
      },
      onError: (err) => {
        setError(failed(err));
        document.getElementById(id)?.focus();
      },
    });
  };
  return (
    <form onSubmit={submit} noValidate className="mt-2 flex flex-wrap items-end gap-2">
      <Field id={id} label="Sync passphrase" error={error ?? undefined} className="min-w-0 flex-1 basis-56">
        <Input
          type="password"
          value={passphrase}
          onChange={(e) => {
            setPassphrase(e.target.value);
            setError(null);
          }}
          autoComplete="current-password"
          readOnly={again.isPending}
        />
      </Field>
      <Button type="submit" variant="primary" icon={KeyRound} loading={again.isPending}>
        Save passphrase
      </Button>
    </form>
  );
}

/** The folder chosen again (it went missing or moved): only a folder of this very sync is accepted. */
function FolderAgain({ status }: { status: SyncStatus }) {
  const connect = useConnectSync();
  const [folder, setFolder] = useState(status.folder ?? "");
  const [error, setError] = useState<string | null>(null);
  const id = "sync-folder-again";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!folder.trim()) {
      setError("Enter the folder's whole path.");
      document.getElementById(id)?.focus();
      return;
    }
    connect.mutate(
      { folder: folder.trim(), name: status.this_computer ?? status.suggested_name, passphrase: "", keep: null },
      {
        onSuccess: () => toast.success("Sync goes on with that folder"),
        onError: (err) => {
          setError(failed(err));
          document.getElementById(id)?.focus();
        },
      },
    );
  };
  return (
    <form onSubmit={submit} noValidate className="mt-2 flex flex-wrap items-end gap-2">
      <Field id={id} label="The sync folder" hint="Where it is now, if you moved it." error={error ?? undefined} className="min-w-0 flex-1 basis-56">
        <Input value={folder} onChange={(e) => setFolder(e.target.value)} autoCapitalize="none" autoCorrect="off" spellCheck={false} readOnly={connect.isPending} />
      </Field>
      <Button type="submit" icon={FolderSearch} loading={connect.isPending}>
        Use this folder
      </Button>
    </form>
  );
}

/**
 * A problem: its title and message for people, and what can be done about it (the main action first). "Set up as a
 * new computer" disconnects first, through the Disconnect dialog (`onNewComputer`), which asks twice when needed.
 */
export function SyncProblemCallout({ status, problem, onNewComputer, className }: { status: SyncStatus; problem: SyncProblem; onNewComputer?: () => void; className?: string }) {
  const update = useUpdateSync();
  const refill = useRefillSync();
  const [error, setError] = useState<string | null>(null);
  const pending = update.isPending || refill.isPending;
  const answer = (action: SyncProblemAction) => {
    setError(null);
    const onError = (err: unknown) => setError(failed(err));
    switch (action) {
      case "refill":
        refill.mutate(undefined, { onSuccess: () => toast.success("The sync folder is filled again"), onError });
        break;
      case "same_computer":
        update.mutate({ confirm_same_computer: true }, { onSuccess: () => toast.success("Sync goes on on this computer"), onError });
        break;
      case "keep_as_is":
        update.mutate({ keep_as_is: true }, { onSuccess: () => toast.success("This computer's data stays as it is"), onError });
        break;
      case "abandon":
        update.mutate({ abandon_pull: true }, { onSuccess: () => toast.success("Bringing it over was given up", { description: "This computer keeps what it has and stands by." }), onError });
        break;
      case "new_computer":
        onNewComputer?.();
        break;
      case "passphrase":
      case "choose_folder":
        break; // a form of its own, below
    }
  };
  const buttons = problem.actions.filter((a) => a !== "passphrase" && a !== "choose_folder" && (a !== "new_computer" || onNewComputer));
  const tone = problem.code === "forgotten" || problem.code === "local_damaged" || problem.code === "damaged" ? "danger" : "warn";
  return (
    <Callout
      tone={tone}
      title={problemTitle(problem)}
      className={className}
      action={
        buttons.length ? (
          <>
            {buttons.map((action, i) => (
              <Button key={action} size="sm" variant={i === 0 ? "primary" : "secondary"} loading={pending && i === 0} disabled={pending} onClick={() => answer(action)}>
                {ACTION_LABELS[action]}
              </Button>
            ))}
          </>
        ) : undefined
      }
    >
      <p className="[overflow-wrap:anywhere]">{problem.message}</p>
      {problem.actions.includes("passphrase") ? <PassphraseAgain /> : null}
      {problem.actions.includes("choose_folder") ? <FolderAgain status={status} /> : null}
      {error ? (
        <p role="alert" className="mt-2 font-medium text-danger-ink [overflow-wrap:anywhere]">
          {error}
        </p>
      ) : null}
    </Callout>
  );
}

/** How far a save or a pull has got (a status line, read out as it changes). */
export function ProgressLine({ progress, what }: { progress: SyncProgress; what: string }) {
  const share = progress.bytes_total ? Math.round((100 * progress.bytes_done) / progress.bytes_total) : progress.total ? Math.round((100 * progress.done) / progress.total) : 0;
  return (
    <div role="status" className="space-y-1.5">
      <p className="text-[13px] leading-5 text-ink/85">
        {what}: {progress.done} of {progress.total} files
        {progress.bytes_total ? ` (${formatFileSize(progress.bytes_done)} of ${formatFileSize(progress.bytes_total)})` : ""}
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
        <div className="h-full rounded-full bg-accent transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${Math.min(100, share)}%` }} />
      </div>
    </div>
  );
}

/** What is still arriving from the sync tool, and what to do when it doesn't (online-only files, a stall). */
export function ArrivingNote({ arriving, className, children }: { arriving: SyncArriving; className?: string; children?: ReactNode }) {
  const advice = arrivalAdvice(arriving);
  return (
    <div className={cn("space-y-2", className)}>
      <p role="status" className="text-[13.5px] leading-5 text-ink/85">
        {arrivingLine(arriving)}
      </p>
      {advice ? (
        <Callout tone="warn" title={arriving.online_only ? "Some files are online only here" : "Nothing more has arrived"}>
          {advice}
        </Callout>
      ) : null}
      {children}
    </div>
  );
}

/** Things to know about once, as dismissible notes (a kept copy can be downloaded from its note). */
export function SyncNotices({ notices, className }: { notices: SyncNotice[]; className?: string }) {
  const update = useUpdateSync();
  const download = useDownloadKept();
  if (!notices.length) return null;
  return (
    <div className={cn("space-y-3", className)}>
      {notices.map((notice) => (
        <Callout
          key={notice.id}
          title={NOTICE_TITLES[notice.code]}
          action={
            <>
              {notice.kept ? (
                <Button size="sm" icon={Download} loading={download.isPending && download.variables === notice.kept} onClick={() => download.mutate(notice.kept!, { onSuccess: (blob) => saveBlob(blob, notice.kept!) })}>
                  Download
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" icon={X} loading={update.isPending && update.variables?.dismiss_notice === notice.id} onClick={() => update.mutate({ dismiss_notice: notice.id })}>
                Dismiss
              </Button>
            </>
          }
        >
          <span className="[overflow-wrap:anywhere]">{notice.message}</span>
        </Callout>
      ))}
    </div>
  );
}

/** A notice's title (its message says the rest). */
export const NOTICE_TITLES: Record<SyncNotice["code"], string> = {
  chosen_elsewhere: "A choice was made on your other computer",
  kept: "A copy of this computer's data was kept",
  rolled_back: "This computer's data was put back",
  take_over_cancelled: "Ordnung stopped waiting to take over",
  brought_in: "A change that arrived late was brought in",
  pull_abandoned: "Bringing Ordnung over was given up",
};
