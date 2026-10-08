/**
 * Settings → Your computers → This computer (design §19.1, card 2): its name and what it is now (in use, standing
 * by, needs a choice, paused), the sync folder, the last save — or what is arriving — the problem with what can be
 * done about it, and **Save now** (in use) or **Use Ordnung here** (standing by), **Rename…** and **Disconnect…**.
 *
 * Disconnecting asks a second time while no other computer has this one's latest changes (finding 2): those would
 * reach no other computer.
 */
import { useRef, useState, type FormEvent } from "react";
import { ArrowRightLeft, CloudUpload, Link2Off, Pencil, Split } from "lucide-react";
import { ApiError } from "@/api/client";
import { useDisconnectSync, useSaveSync, useTakeOver, useUpdateSync } from "@/api/hooks";
import type { SyncStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Checkbox, Field, Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { ChoiceDialog } from "@/features/sync/ChoiceDialog";
import { ArrivingNote, ProgressLine, SyncProblemCallout } from "@/features/sync/parts";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import { BreakablePath } from "./DataSection";
import { SettingsCard } from "./SettingsCard";
import { DataFolderSyncedWarning, SETUP_HEADING_ID } from "./SyncSetupCard";
import { inUseName, lastSavedLine, modeLabel, nameProblem, standbyStatusLine, unreceivedLine } from "./sync";

export const THIS_COMPUTER_ID = "sync-this-computer";
const DISCONNECT_ERROR_ID = "sync-disconnect-error";

const failed = (err: unknown) => (err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?");

/** What a progress bar is about. */
const PROGRESS_WHAT: Record<SyncStatus["activity"], string> = {
  idle: "Done",
  saving: "Saving to the sync folder",
  waiting: "Waiting for your sync tool",
  bringing_over: "Bringing Ordnung over",
  keeping: "Keeping a copy of this computer's data",
};

/**
 * "Disconnect this computer?": what stays where, the passphrase in the password store, and — while no other
 * computer has this one's latest changes — a second confirmation (also when the server says so: 409 `not_received`).
 */
export function DisconnectDialog({ open, onClose, status }: { open: boolean; onClose: () => void; status: SyncStatus }) {
  const disconnect = useDisconnectSync();
  const [forget, setForget] = useState(true);
  const [anyway, setAnyway] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const unreceived = status.mode === "in_use" ? unreceivedLine(status) : null;
  const second = unreceived ?? refused;
  const close = () => {
    if (disconnect.isPending) return;
    setForget(true);
    setAnyway(false);
    setRefused(null);
    disconnect.reset();
    onClose();
  };
  const confirm = () =>
    disconnect.mutate(
      { forget_passphrase: forget, unreceived_ok: Boolean(second) && anyway },
      {
        onSuccess: () => {
          close();
          // the card becomes the setup form: its heading takes the focus of the gone "Disconnect…"
          focusWhenReady(() => document.getElementById(SETUP_HEADING_ID));
          toast.success("This computer stopped syncing", { description: "Its data stays here. The sync folder and your other computers keep everything." });
        },
        onError: (err) => {
          if (err instanceof ApiError && err.code === "not_received") {
            setRefused(err.message);
            disconnect.reset();
          }
          focusWhenReady(() => document.getElementById(DISCONNECT_ERROR_ID), 5000, { always: true });
        },
      },
    );
  return (
    <Dialog
      open={open}
      onClose={close}
      size="sm"
      title="Disconnect this computer?"
      description="This computer stops syncing. Its data stays here as it is; the sync folder and your other computers keep everything. Kept copies stay in Your computers."
      initialFocus={cancelRef}
      dismissible={!disconnect.isPending}
      footer={
        <>
          <Button ref={cancelRef} onClick={close} disabled={disconnect.isPending}>
            Cancel
          </Button>
          <Button variant="danger" icon={Link2Off} loading={disconnect.isPending} disabled={Boolean(second) && !anyway} onClick={confirm}>
            {second ? "Disconnect anyway" : "Disconnect"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Checkbox
          checked={forget}
          onChange={(e) => setForget(e.target.checked)}
          label="Also remove the passphrase from this computer's password store"
          description="Set up again later, you type it once more."
        />
        {second ? (
          <div id={DISCONNECT_ERROR_ID} tabIndex={-1} className="space-y-3 rounded-xl">
            <Callout tone="warn" title="Your latest changes haven't reached another computer">
              <span className="[overflow-wrap:anywhere]">{unreceived ?? refused}</span>
            </Callout>
            <Checkbox checked={anyway} onChange={(e) => setAnyway(e.target.checked)} label="Disconnect anyway" description="This computer's latest changes then stay only here." />
          </div>
        ) : null}
        {disconnect.error ? (
          <div id={second ? undefined : DISCONNECT_ERROR_ID} tabIndex={-1} className="rounded-xl">
            <Callout tone="danger" alert title="Nothing was changed">
              <span className="[overflow-wrap:anywhere]">{failed(disconnect.error)}</span>
            </Callout>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

/** "Rename this computer" (how the other computers name it). */
function RenameDialog({ open, onClose, status }: { open: boolean; onClose: () => void; status: SyncStatus }) {
  const update = useUpdateSync();
  const [name, setName] = useState(status.this_computer ?? "");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const close = () => {
    if (update.isPending) return;
    setName(status.this_computer ?? "");
    setError(null);
    onClose();
  };
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const wrong = nameProblem(name);
    if (wrong) {
      setError(wrong);
      inputRef.current?.focus();
      return;
    }
    update.mutate(
      { name: name.trim() },
      {
        onSuccess: (after) => {
          setError(null);
          onClose();
          toast.success(`This computer is ${after.this_computer ?? name.trim()} now`);
        },
        onError: (err) => {
          setError(failed(err));
          inputRef.current?.focus();
        },
      },
    );
  };
  return (
    <Dialog
      open={open}
      onClose={close}
      size="sm"
      title="Rename this computer"
      description="How your other computers name this one."
      initialFocus={inputRef}
      dismissible={!update.isPending}
      footer={
        <>
          <Button onClick={close} disabled={update.isPending}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="sync-rename-form" loading={update.isPending}>
            Rename
          </Button>
        </>
      }
    >
      <form id="sync-rename-form" onSubmit={submit} noValidate>
        <Field id="sync-rename" label="Name" error={error ?? undefined}>
          <Input ref={inputRef} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" maxLength={80} readOnly={update.isPending} />
        </Field>
      </form>
    </Dialog>
  );
}

/** This computer: what it is now, the folder, the last save or what arrives, the problem, and what can be done. */
export function ThisComputerCard({ status }: { status: SyncStatus }) {
  const save = useSaveSync();
  const takeOver = useTakeOver();
  const [disconnecting, setDisconnecting] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const badge = modeLabel(status);
  const inUse = status.mode === "in_use";
  const standing = status.mode === "standing_by";
  const progress = status.progress && status.activity !== "idle" ? status.progress : null;

  const saveNow = () => save.mutate({}, { onSuccess: (after) => toast.success("Saved to the sync folder", { description: after.computers.some((c) => !c.this) ? "Your sync tool takes it to your other computers." : undefined }) });
  const takeOverHere = () =>
    takeOver.mutate(
      {},
      {
        onSuccess: (after) => (after.mode === "in_use" ? toast.success("Ordnung is in use here now") : undefined),
        onError: (err) => toast.error("Ordnung isn't in use here yet", { description: failed(err) }),
      },
    );

  return (
    <SettingsCard title="This computer" id={THIS_COMPUTER_ID} description="Ordnung is in use on one computer at a time; the others stand by and change nothing.">
      <div className="space-y-4">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] text-ink">
          <span className="min-w-0 font-semibold [overflow-wrap:anywhere]">{status.this_computer}</span>
          <Badge tone={badge.tone} dot>
            {badge.label}
          </Badge>
        </p>
        {status.folder ? (
          <p className="min-w-0 text-[13px] leading-5 text-muted">
            Sync folder: <code className="font-mono text-[12.5px] text-ink wrap-anywhere"><BreakablePath path={status.folder} /></code>
          </p>
        ) : null}
        <p role="status" className={cn("text-[13.5px] leading-5", status.problem ? "text-warn-ink" : "text-ink/85")}>
          {inUse ? lastSavedLine(status) : standing ? `In use on ${inUseName(status)}. ${standbyStatusLine(status)}` : "Looking at the sync folder…"}
        </p>
        {progress ? <ProgressLine progress={progress} what={PROGRESS_WHAT[status.activity]} /> : null}
        {status.arriving && !standing ? <ArrivingNote arriving={status.arriving} /> : null}
        {status.data_folder_synced ? <DataFolderSyncedWarning /> : null}
        {status.choice ? (
          <Callout
            tone="warn"
            title="Your two computers both have changes."
            icon={Split}
            action={
              <Button size="sm" variant="primary" onClick={() => setChoosing(true)}>
                Choose…
              </Button>
            }
          >
            Nothing is lost: choose which computer's Ordnung to keep. The other is saved as an encrypted backup on its own computer.
          </Callout>
        ) : null}
        {status.problem ? <SyncProblemCallout status={status} problem={status.problem} onNewComputer={() => setDisconnecting(true)} /> : null}
        <div className="flex flex-wrap gap-2">
          {inUse ? (
            <Button size="sm" variant="secondary" icon={CloudUpload} onClick={saveNow} loading={save.isPending}>
              Save now
            </Button>
          ) : standing ? (
            <Button size="sm" variant="primary" icon={ArrowRightLeft} onClick={takeOverHere} loading={takeOver.isPending} disabled={Boolean(status.choice)}>
              Use Ordnung here
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setRenaming(true)}>
            Rename…
          </Button>
          <Button size="sm" variant="ghost" icon={Link2Off} onClick={() => setDisconnecting(true)}>
            Disconnect…
          </Button>
        </div>
      </div>
      <DisconnectDialog open={disconnecting} onClose={() => setDisconnecting(false)} status={status} />
      <RenameDialog key={status.this_computer ?? ""} open={renaming} onClose={() => setRenaming(false)} status={status} />
      <ChoiceDialog open={choosing} onClose={() => setChoosing(false)} status={status} />
    </SettingsCard>
  );
}
