/**
 * Setting hand-off sync up (design §19.1, card 1), in Settings → Your computers and on `/join`:
 *
 * 1. **The folder** your sync tool keeps in step. Looked at when the field is left (or on Next): a new sync starts
 *    there, or it holds one to join, or it can't be used (the reason under the field). A warning when Ordnung's data
 *    folder is itself inside a synced folder (the sync tool would upload it unencrypted).
 * 2. **This computer's name**, the host name by default (a name already taken gets “ (2)”).
 * 3. **The passphrase**: for a new sync twice, with a suggested five-word one and its strength said as it is typed
 *    (about 70 bits, the server's own estimator); to join, once.
 * 4. Joining while this computer has letters of its own asks first which Ordnung to keep (the other is kept as an
 *    encrypted copy).
 *
 * A refusal is said next to the field it concerns (`ApiError.code`); the passphrase only travels to this computer's
 * Ordnung, which keeps it in the password store.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Check, CloudUpload, FolderSync, Layers, Link2Off, LockKeyhole, OctagonAlert, Split } from "lucide-react";
import { ApiError } from "@/api/client";
import { useConnectSync, useInspectSyncFolder } from "@/api/hooks";
import type { SyncChoice, SyncFolderInfo, SyncSide, SyncStatus } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Field, Input } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { SideOption } from "@/features/sync/ChoiceDialog";
import { focusWhenReady } from "@/features/today/focus";
import { cn } from "@/lib/utils";
import type { PassphraseProblem } from "./backup";
import { PassphraseFields } from "./PassphraseFields";
import { SettingsCard } from "./SettingsCard";
import { fieldFor, looksAbsolute, PASSPHRASE_WORDING, strengthLine, suggestSyncPassphrase, syncFormProblem, type SetupField } from "./sync";

/** The card's heading, in both its places: where focus goes after disconnecting. */
export const SETUP_HEADING_ID = "set-sync";
const FORM_ID = "sync-setup-form";
const FORM_ERROR_ID = "sync-setup-error";
const CHOICE_ID = "sync-setup-choice";

/** What hand-off sync is, in three facts. */
export const SYNC_FACTS: { icon: typeof Layers; text: string }[] = [
  { icon: Layers, text: "In use on one computer at a time — the others stand by" },
  { icon: LockKeyhole, text: "Only encrypted files go to the folder, under names that say nothing" },
  { icon: Split, text: "Nothing is merged or thrown away: if both changed, you choose" },
];

type Errors = Partial<Record<SetupField, string>>;

function focusField(field: SetupField) {
  const id = field === "form" ? FORM_ERROR_ID : `sync-${field}`;
  document.getElementById(id)?.focus();
}

function errorsFrom(err: unknown): Errors {
  if (err instanceof ApiError) return { [fieldFor(err.code)]: err.message };
  return { form: "Ordnung didn't answer. Is it still running?" };
}

/** No usable password store (or the demo): say why, and the command that makes it work when there is one. */
export function SyncUnavailable({ status }: { status: SyncStatus }) {
  if (status.install_command)
    return (
      <Callout tone="warn" title="One more package, then this works">
        <p>{status.unavailable}</p>
        <CopyCommand command={status.install_command} label="install the password store" className="mt-2" />
        <p className="mt-2">Then restart Ordnung.</p>
      </Callout>
    );
  return (
    <p className="rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
      {status.unavailable ?? "Hand-off sync can't be used on this computer."}
    </p>
  );
}

/** Ordnung's data folder is inside a synced folder: the sync tool uploads it unencrypted (a warning, never a refusal). */
export function DataFolderSyncedWarning() {
  return (
    <Callout tone="danger" title="Ordnung's data folder is inside a synced folder">
      Your sync tool uploads that folder as it is — your letters and the database, unencrypted. Move Ordnung's data folder out of it, or exclude it in your sync
      tool. Hand-off sync puts only encrypted files into the folder you choose here.
    </Callout>
  );
}

/** What the folder turned out to be, under its field (a refusal is the field's error instead). */
function folderLine(info: SyncFolderInfo, join: boolean): string | null {
  if (info.kind === "new") return join ? null : "A new sync starts in this folder.";
  if (info.kind === "existing") return "This folder holds a sync from your other computer: type its passphrase to join it.";
  return null;
}

/** "Which do you want to keep?" when joining while this computer has letters of its own (the joining wording). */
function JoiningChoice({ choice, picked, onPick, disabled }: { choice: SyncChoice; picked: number | null; onPick: (key: number) => void; disabled: boolean }) {
  const name = useId();
  const here = choice.sides.find((s) => s.this);
  const other = choice.sides.find((s) => !s.this);
  return (
    <fieldset id={CHOICE_ID} tabIndex={-1} className="rounded-xl outline-none">
      <legend className="text-[14px] leading-5 text-ink">
        <span className="font-semibold">This computer already has its own Ordnung ({here ? `${here.letters} ${here.letters === 1 ? "letter" : "letters"}` : "its own letters"}).</span>{" "}
        {other ? `${other.computer}'s has ${other.letters} ${other.letters === 1 ? "letter" : "letters"}. ` : ""}Which do you want to keep?
      </legend>
      <p className="mt-1 text-[13px] leading-5 text-muted">The other is saved as an encrypted backup on its own computer, so nothing is thrown away.</p>
      <div className="mt-3 space-y-2">
        {choice.sides.map((side: SyncSide) => (
          <SideOption key={side.key} side={side} name={name} checked={picked === side.key} onChoose={() => onPick(side.key)} joining disabled={disabled} />
        ))}
      </div>
    </fieldset>
  );
}

/**
 * The setup form. `join`: on `/join`, a folder that holds a sync is expected (the computer has nothing yet). After
 * connecting, `onConnected` gets the status (Settings shows the connected cards by itself).
 */
export function SyncSetupCard({ status, join = false, onConnected }: { status: SyncStatus; join?: boolean; onConnected?: (status: SyncStatus) => void }) {
  const inspect = useInspectSyncFolder();
  const connect = useConnectSync();
  const [folder, setFolder] = useState("");
  const [name, setName] = useState(status.suggested_name);
  const [passphrase, setPassphrase] = useState("");
  const [repeat, setRepeat] = useState("");
  const [visible, setVisible] = useState(false);
  const [suggested, setSuggested] = useState(false);
  const [info, setInfo] = useState<SyncFolderInfo | null>(null);
  const [checked, setChecked] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [choice, setChoice] = useState<SyncChoice | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const firstPassphrase = useRef<HTMLInputElement>(null);
  const busy = inspect.isPending || connect.isPending;
  // what the folder is decides what is asked (joining from /join expects a folder that holds a sync)
  const kind = info && checked === folder.trim() && info.kind !== "refused" && !(join && info.kind === "new") ? info.kind : null;
  const newSync = kind === "new" && !join;

  // a refusal's field gets focus once the fields can be typed in again
  const focusNext = useRef<SetupField | null>(null);
  useEffect(() => {
    if (busy || !focusNext.current) return;
    focusField(focusNext.current);
    focusNext.current = null;
  }, [busy, errors]);

  const editFolder = (value: string) => {
    setFolder(value);
    setErrors({});
    setChoice(null);
    setPicked(null);
  };

  /** Look at the folder (nothing is written); `then` runs once it can be used. */
  const look = (then?: (info: SyncFolderInfo) => void) => {
    const value = folder.trim();
    if (!value || !looksAbsolute(value)) {
      setErrors({ folder: value ? "Enter the whole path, starting at the top: /home/you/Nextcloud/Ordnung." : "Enter the folder your sync tool keeps in step, like /home/you/Nextcloud/Ordnung." });
      focusNext.current = "folder";
      return;
    }
    inspect.mutate(value, {
      onSuccess: (found) => {
        setInfo(found);
        setChecked(value);
        if (found.kind === "refused") {
          setErrors({ folder: found.problem ?? "This folder can't be used for sync." });
          focusNext.current = "folder";
          return;
        }
        if (join && found.kind === "new") {
          setErrors({ folder: "No sync from your other computer is in this folder yet. Check the path — and that your sync tool has copied the folder to this computer." });
          focusNext.current = "folder";
          return;
        }
        setErrors({});
        then?.(found);
      },
      onError: (err) => {
        setErrors(errorsFrom(err));
        focusNext.current = err instanceof ApiError ? fieldFor(err.code) : "form";
      },
    });
  };

  const suggest = () => {
    const value = suggestSyncPassphrase();
    setPassphrase(value);
    setRepeat(value);
    setVisible(true);
    setSuggested(true);
    setErrors((e) => ({ ...e, passphrase: undefined, repeat: undefined }));
    firstPassphrase.current?.focus();
  };

  const connected = (after: SyncStatus, joined: boolean) => {
    if (joined) {
      const from = after.base_from && after.base_from !== after.this_computer ? after.base_from : null;
      if (after.mode === "in_use") toast.success("Ordnung is in use here now", { description: from ? `Everything from ${from} is here.` : "Syncing through the folder you chose." });
      else toast.success("Bringing Ordnung over", { description: "As soon as everything has arrived from your sync tool, it is in use here." });
    } else {
      toast.success("Syncing to your folder", {
        description: "This computer is the one in use. On your other computer, choose the same folder and passphrase — or “I already use Ordnung on another computer” when you set it up.",
      });
    }
    onConnected?.(after);
  };

  const send = (keep: "this" | "folder" | null, found: SyncFolderInfo) => {
    connect.mutate(
      { folder: found.folder, name: name.trim(), passphrase, keep },
      {
        onSuccess: (result) => {
          if (result.choice) {
            setChoice(result.choice);
            setPicked(null);
            focusWhenReady(() => document.getElementById(CHOICE_ID), 5000, { always: true });
            return;
          }
          setPassphrase("");
          setRepeat("");
          connected(result.status, found.kind === "existing");
        },
        onError: (err) => {
          const next = errorsFrom(err);
          focusNext.current = (Object.keys(next)[0] ?? "form") as SetupField;
          setErrors(next);
        },
      },
    );
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (busy || !status.available) return;
    if (!kind || !info) {
      // first the folder: what it is decides the passphrase fields (then on to the next empty one)
      look((found) => focusWhenReady(() => document.getElementById(found.kind === "existing" || join ? "sync-passphrase" : name.trim() ? "sync-passphrase" : "sync-name"), 5000, { always: true }));
      return;
    }
    const problem = syncFormProblem({ folder, name, passphrase, repeat }, kind);
    if (problem) {
      setErrors({ [problem.field]: problem.message });
      focusField(problem.field);
      return;
    }
    setErrors({});
    if (choice) {
      const side = choice.sides.find((s) => s.key === picked);
      if (!side) return;
      send(side.this ? "this" : "folder", info);
      return;
    }
    send(null, info);
  };

  const passphraseProblem: PassphraseProblem | null = errors.passphrase ? { field: "passphrase", message: errors.passphrase } : errors.repeat ? { field: "repeat", message: errors.repeat } : null;
  const strength = newSync && !suggested ? strengthLine(passphrase) : null;
  const label = !kind ? "Next" : choice ? "Keep this one" : newSync ? "Start syncing" : "Bring it here";
  const icon = !kind ? ArrowRight : choice ? Check : newSync ? CloudUpload : FolderSync;
  const line = info && kind ? folderLine(info, join) : null;

  return (
    <SettingsCard
      title={join ? "Bring Ordnung over from your other computer" : "Use Ordnung on more than one computer"}
      id={SETUP_HEADING_ID}
      description={
        join
          ? "Choose the folder your sync tool keeps in step with your other computer, and type the passphrase you chose there. Everything comes over, encrypted on the way."
          : "Ordnung saves an encrypted copy into a folder your own sync tool already keeps in step — Nextcloud, Syncthing, Dropbox, iCloud Drive or a network drive. On another computer, one click, “Use Ordnung here”, brings everything over."
      }
      footer={
        status.available ? (
          <>
            {errors.form ? (
              <p id={FORM_ERROR_ID} role="alert" tabIndex={-1} className="mr-auto flex min-w-0 basis-full items-start gap-1.5 rounded-sm text-sm leading-5 text-danger-ink sm:basis-0 sm:flex-1">
                <OctagonAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="min-w-0 [overflow-wrap:anywhere]">{errors.form}</span>
              </p>
            ) : null}
            <Button type="submit" form={FORM_ID} variant="primary" icon={icon} loading={busy} disabled={Boolean(choice) && picked === null}>
              {label}
            </Button>
          </>
        ) : undefined
      }
    >
      {!join ? (
        <ul className="mb-5 grid gap-2 sm:grid-cols-3">
          {SYNC_FACTS.map((f) => (
            <li key={f.text} className="flex min-w-0 items-start gap-2 rounded-xl bg-surface-2/60 px-3 py-2.5 text-[13.5px] leading-5 text-ink/85">
              <f.icon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <span className="min-w-0">{f.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {!status.available ? (
        <SyncUnavailable status={status} />
      ) : (
        <form id={FORM_ID} onSubmit={submit} noValidate className="space-y-4">
          <div>
            <Field
              id="sync-folder"
              label="Sync folder"
              hint="A folder of its own inside the folder your sync tool keeps in step, like /home/you/Nextcloud/Ordnung. Ordnung creates it if it isn't there."
              error={errors.folder}
            >
              <Input
                value={folder}
                onChange={(e) => editFolder(e.target.value)}
                onBlur={() => {
                  if (folder.trim() && folder.trim() !== checked && !busy) look();
                }}
                placeholder="/home/you/Nextcloud/Ordnung"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                readOnly={busy}
              />
            </Field>
            {line && !errors.folder ? (
              <p role="status" className="mt-1.5 text-[13px] leading-5 text-ink/85">
                {line}
              </p>
            ) : (
              <span role="status" className="sr-only">
                {line && !errors.folder ? line : ""}
              </span>
            )}
          </div>
          {info?.data_folder_synced ? <DataFolderSyncedWarning /> : null}
          {info?.links_left_out.length ? (
            <Callout tone="warn" title="Left out of sync" icon={Link2Off}>
              {info.links_left_out.map((l) => `“${l}”`).join(", ")} {info.links_left_out.length === 1 ? "is a link" : "are links"} to somewhere outside the data folder, and
              sync never follows links. Move {info.links_left_out.length === 1 ? "it" : "them"} into the data folder to bring {info.links_left_out.length === 1 ? "it" : "them"} along.
            </Callout>
          ) : null}
          <Field id="sync-name" label="This computer's name" hint="How your other computers name this one. A name already taken gets “ (2)”." error={errors.name}>
            <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" maxLength={80} readOnly={busy} className="sm:max-w-sm" />
          </Field>
          {kind ? (
            <div className={cn("space-y-4 border-t border-line pt-4")}>
              <PassphraseFields
                idPrefix="sync"
                label={newSync ? "Passphrase" : "The sync passphrase"}
                passphrase={passphrase}
                onPassphraseChange={(value) => {
                  setPassphrase(value);
                  setSuggested(false);
                  setErrors((e) => ({ ...e, passphrase: undefined, repeat: undefined }));
                }}
                repeat={newSync ? repeat : undefined}
                onRepeatChange={(value) => {
                  setRepeat(value);
                  setErrors((e) => ({ ...e, repeat: undefined }));
                }}
                problem={passphraseProblem}
                visible={visible}
                onVisibleChange={setVisible}
                onSuggest={newSync ? suggest : undefined}
                suggested={suggested}
                hint={newSync ? "Five or more words that don't belong together — or take the suggested one." : "The passphrase you chose when you set up sync on your other computer."}
                suggestedHint="Five random words. Save them in your password manager (or write them down) before you start."
                status={
                  strength ? (
                    <p aria-live="polite" className={cn("text-[13px] leading-5", strength.tone === "ok" ? "text-ok-ink" : "text-warn-ink")}>
                      {strength.text}
                    </p>
                  ) : null
                }
                busy={busy}
                firstRef={firstPassphrase}
              />
              <p className="flex items-start gap-2 rounded-xl bg-surface-2/70 px-3 py-2.5 text-[13px] leading-5 text-ink/85">
                <LockKeyhole className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                <span className="min-w-0">{PASSPHRASE_WORDING}</span>
              </p>
            </div>
          ) : null}
          {choice ? <JoiningChoice choice={choice} picked={picked} onPick={setPicked} disabled={busy} /> : null}
        </form>
      )}
    </SettingsCard>
  );
}
