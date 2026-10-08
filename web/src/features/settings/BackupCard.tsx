import { Fragment, useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { CircleCheck, Download, HardDriveDownload, KeyRound, LockKeyhole } from "lucide-react";
import { ApiError } from "@/api/client";
import { useBackupInfo, useDownloadBackup } from "@/api/hooks";
import type { BackupInfo } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { LoadError } from "@/components/ui/LoadError";
import { Skeleton } from "@/components/ui/Skeleton";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { focusWhenReady } from "@/features/today/focus";
import { formatFileSize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isStaticDemo } from "@/mocks/mode";
import { backupContents, backupStrengthLine, backupSummary, failureSentence, leftOutSentence, MIN_PASSPHRASE, passphraseProblem, restoreCommand, restoreCommandPieces, saveBlob, type PassphraseProblem } from "./backup";
import { suggestPassphrase } from "./passphrase";
import { PassphraseFields } from "./PassphraseFields";
import { FOOTER_ACTION, SettingsCard } from "./SettingsCard";

const ERROR_ID = "backup-error";

/** The backup the browser just saved (what the card confirms). */
interface SavedBackup {
  name: string;
  size: number;
}

/**
 * "Download an encrypted backup": a passphrase typed twice (or a suggested one) — as strong as a new sync
 * folder's, its strength said while it is typed — then the local server makes the backup and the browser
 * saves it. The passphrase goes only to this computer's Ordnung and is forgotten when the dialog closes.
 */
function BackupDialog({
  open,
  onClose,
  onSaved,
  info,
  returnFocus,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (saved: SavedBackup) => void;
  info: BackupInfo | undefined;
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  const download = useDownloadBackup();
  const [passphrase, setPassphrase] = useState("");
  const [repeat, setRepeat] = useState("");
  const [visible, setVisible] = useState(false);
  const [problem, setProblem] = useState<PassphraseProblem | null>(null);
  const [suggested, setSuggested] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const stopRef = useRef<HTMLButtonElement>(null);
  const min = info?.min_passphrase ?? MIN_PASSPHRASE;
  const strength = suggested ? null : backupStrengthLine(passphrase, min);
  const busy = download.isPending;

  const reset = () => {
    setPassphrase("");
    setRepeat("");
    setVisible(false);
    setProblem(null);
    setSuggested(false);
    download.reset();
  };
  const close = () => {
    abort.current?.abort();
    reset();
    onClose();
  };
  // a backup still being made when the dialog goes away is stopped
  useEffect(() => () => abort.current?.abort(), []);

  const suggest = () => {
    const value = suggestPassphrase();
    setPassphrase(value);
    setRepeat(value);
    setVisible(true);
    setSuggested(true);
    setProblem(null);
    firstRef.current?.focus();
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (busy) return;
    const wrong = passphraseProblem(passphrase, repeat, min);
    setProblem(wrong);
    if (wrong) {
      document.getElementById(wrong.field === "passphrase" ? "backup-passphrase" : "backup-repeat")?.focus();
      return;
    }
    const controller = new AbortController();
    abort.current = controller;
    // the pressed button turns into "Encrypting…" (disabled): focus goes to "Stop", inside the dialog
    if (document.activeElement === submitRef.current) stopRef.current?.focus();
    download.mutate(
      { passphrase, signal: controller.signal },
      {
        onSuccess: (blob) => {
          const name = info?.file_name ?? "ordnung-backup.ordnung-backup";
          saveBlob(blob, name);
          reset();
          onClose();
          onSaved({ name, size: blob.size });
        },
        onError: (err) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          if (err instanceof ApiError && err.status === 422) {
            setProblem({ field: "passphrase", message: err.message });
            focusWhenReady(() => document.getElementById("backup-passphrase"), 5000, { always: true });
            return;
          }
          // below the fields, perhaps under a phone's fold: the reason is brought into view and read
          focusWhenReady(() => document.getElementById(ERROR_ID), 5000, { always: true });
        },
      },
    );
  };

  const failed = download.error && !(download.error instanceof DOMException) && !(download.error instanceof ApiError && download.error.status === 422);

  return (
    <Dialog
      open={open}
      onClose={close}
      size="md"
      title="Download an encrypted backup"
      description="Choose a passphrase to lock the backup. Ordnung never stores it — without it nobody can open the backup, not even you."
      initialFocus={firstRef}
      returnFocus={returnFocus}
      dismissible={!busy}
      footer={
        <>
          <Button ref={stopRef} onClick={close}>
            {busy ? "Stop" : "Cancel"}
          </Button>
          <Button ref={submitRef} type="submit" form="backup-form" variant="primary" icon={Download} loading={busy}>
            {busy ? "Encrypting…" : "Download backup"}
          </Button>
        </>
      }
    >
      <form id="backup-form" onSubmit={submit} noValidate className="space-y-4">
        {info ? (
          <p className="flex items-start gap-2 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px] leading-5 text-ink/85">
            <HardDriveDownload className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
            <span className="min-w-0">
              {backupSummary(info)} — {backupContents(info.left_out)}
            </span>
          </p>
        ) : null}
        {info?.left_out.length ? (
          <Callout tone="warn" title="Not in the backup">
            <span className="[overflow-wrap:anywhere]">{leftOutSentence(info.left_out)}</span>
          </Callout>
        ) : null}
        <PassphraseFields
          idPrefix="backup"
          passphrase={passphrase}
          onPassphraseChange={(value) => {
            setPassphrase(value);
            setSuggested(false);
            setProblem(null);
          }}
          repeat={repeat}
          onRepeatChange={(value) => {
            setRepeat(value);
            setProblem(null);
          }}
          problem={problem}
          visible={visible}
          onVisibleChange={setVisible}
          onSuggest={suggest}
          suggested={suggested}
          hint="Five or more words that don't belong together — or take the suggested one."
          suggestedHint="Save this passphrase in your password manager (or write it down) before you download."
          status={
            strength ? (
              <p aria-live="polite" className={cn("text-[13px] leading-5", strength.tone === "ok" ? "text-ok-ink" : "text-warn-ink")}>
                {strength.text}
              </p>
            ) : null
          }
          busy={busy}
          firstRef={firstRef}
        />
        {failed ? (
          <div id={ERROR_ID} tabIndex={-1} className="rounded-xl">
            <Callout tone="danger" title="Couldn't make the backup" alert>
              {failureSentence(download.error)} Nothing was saved.
            </Callout>
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}

/** The restore command as shown: it breaks between the command and the file name's parts, never in a date. */
function RestoreCommandText({ fileName }: { fileName: string }) {
  return (
    <>
      {restoreCommandPieces(fileName).map((piece, i) => (
        <Fragment key={i}>
          {i > 0 ? <wbr /> : null}
          {piece}
        </Fragment>
      ))}
    </>
  );
}

/**
 * Settings → Data: "Encrypted backup" — what it holds, the download, and how to restore it. `open`
 * and `onOpenChange` let the page open the dialog (the "Delete everything" dialog offers it).
 */
export function BackupCard({
  open: openProp,
  onOpenChange,
  returnFocus,
}: { open?: boolean; onOpenChange?: (open: boolean) => void; returnFocus?: RefObject<HTMLElement | null> } = {}) {
  const info = useBackupInfo();
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const setOpen = onOpenChange ?? setOpenState;
  const [saved, setSaved] = useState<SavedBackup | null>(null);
  const staticDemo = isStaticDemo();
  const fileName = saved?.name ?? info.data?.file_name ?? "ordnung-backup.ordnung-backup";

  return (
    <SettingsCard
      title="Encrypted backup"
      id="set-data-backup"
      description="Everything in one file, locked with a passphrase you choose: the database, your original letters, page images and letter PDFs. Keep it on another drive or in the cloud — without the passphrase nobody can read it."
      footer={
        <>
          {/* the confirmation stays in the card (a toast would cover the page below it); the live
              region takes no room, so an empty one leaves no gap above the phone-wide button */}
          <span role="status" className="sr-only">
            {saved ? `Downloaded ${saved.name} (${formatFileSize(saved.size)}). Keep the passphrase safe: you need it to restore.` : ""}
          </span>
          {saved ? (
            <p aria-hidden className="mr-auto flex min-w-0 items-start gap-1.5 text-sm leading-5 text-ok-ink">
              <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="min-w-0 [overflow-wrap:anywhere]">
                <span className="font-medium">Downloaded</span> {saved.name} ({formatFileSize(saved.size)}).{" "}
                <span className="text-ink/80">Keep the passphrase safe: you need it to restore.</span>
              </span>
            </p>
          ) : null}
          {/* the whole row on phones like every Data card's action, without its icon: the label alone just
              fits a 320 px card's footer */}
          <Button variant="primary" icon={LockKeyhole} onClick={() => setOpen(true)} disabled={staticDemo} className={`${FOOTER_ACTION} max-sm:[&>svg]:hidden`}>
            Download encrypted backup…
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {info.isError && !staticDemo ? (
          <LoadError
            title="Couldn't load what the backup would hold"
            description="The backup itself doesn't need this summary — but Ordnung didn't answer. Is it still running?"
            error={info.error}
            onRetry={() => void info.refetch()}
            retrying={info.isFetching}
            headingLevel={4}
            variant="plain"
            size="sm"
          />
        ) : (
          // a div, not a p: the loading line is a block (a <div> inside a <p> is invalid HTML)
          <div className="flex min-h-5 items-start gap-2 text-sm leading-5 text-muted">
            <KeyRound className="mt-0.5 size-4 shrink-0" aria-hidden />
            {info.isPending && !staticDemo ? (
              <Skeleton className="h-4 w-64 max-w-full" />
            ) : info.data && !staticDemo ? (
              <span className="min-w-0">
                <span className="font-medium text-ink">Now: </span>
                {backupSummary(info.data)}
              </span>
            ) : (
              // the online demo has nothing of the visitor's to count
              <span>AES-256 encryption, checked in full when it is restored.</span>
            )}
          </div>
        )}
        {staticDemo ? (
          <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
            Not available in the online demo — it keeps nothing on your computer. Install Ordnung to back up your own letters.
          </p>
        ) : (
          <div>
            <p className="text-sm leading-5 text-ink/85">To restore it — on this computer or a new one — run this in the folder you saved it in:</p>
            <CopyCommand command={restoreCommand(fileName)} display={<RestoreCommandText fileName={fileName} />} label="restore the backup" className="mt-2" />
            <p className="mt-2 text-[12.5px] leading-5 text-muted">
              It never replaces data that is already there unless you add <code className="font-mono text-ink">--force</code> (then the old folder is kept
              next to it). A changed or damaged backup, or a wrong passphrase, is refused.
            </p>
          </div>
        )}
      </div>
      <BackupDialog open={open} onClose={() => setOpen(false)} onSaved={setSaved} info={info.data} returnFocus={returnFocus} />
    </SettingsCard>
  );
}
